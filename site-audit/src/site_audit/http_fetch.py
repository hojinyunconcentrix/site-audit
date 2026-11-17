"""리다이렉트마다 주소를 다시 검사하고, 확인한 IP로만 연결한다.

같은 호스트는 동시에 두 연결만 열고, 요청 시작 사이에는 간격을 둔다.
403·429·503이면 Retry-After만큼 쉰 뒤 한 번만 다시 보내고, 또 막히면 그 호스트는 멈춘다.
"""

from __future__ import annotations

import os
import re
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from site_audit.guard import Target, UrlRejected, check_url

USER_AGENT = "site-audit/0.1"
MAX_REDIRECTS = 5
MAX_BYTES = 2_000_000
TIMEOUT = 8
HOST_GAP = 0.4
HOST_INFLIGHT = 2
HOST_PAUSE = 15.0
BLOCK_STATUSES = frozenset({403, 429, 503})
BLOCK_MESSAGE = "이 호스트가 요청을 제한했습니다."


@dataclass(frozen=True)
class HttpResult:
    url: str
    status: int
    content_type: str
    body: bytes
    error: str = ""


def _ssl_context() -> ssl.SSLContext:
    candidates = [
        os.environ.get("SSL_CERT_FILE", ""),
        "/etc/ssl/cert.pem",
        "/etc/ssl/certs/ca-certificates.crt",
    ]
    for path in candidates:
        if path and Path(path).is_file():
            return ssl.create_default_context(cafile=path)
    return ssl.create_default_context()


def _decode_location(headers, current: str) -> str:
    location = ""
    for key, value in headers:
        if key.lower() == "location":
            location = value.strip()
            break
    if not location:
        return ""
    return urljoin(current, location)


def _unchunk(rest: bytes) -> bytes:
    pieces = bytearray()
    index = 0
    while index < len(rest):
        line_end = rest.find(b"\r\n", index)
        if line_end == -1:
            break
        size_text = rest[index:line_end].split(b";", 1)[0].strip()
        try:
            size = int(size_text, 16)
        except ValueError:
            return bytes(rest)
        if size == 0:
            break
        start = line_end + 2
        pieces += rest[start : start + size]
        index = start + size
        if rest[index : index + 2] == b"\r\n":
            index += 2
    return bytes(pieces)


def _body_bytes(rest: bytes, headers: list[tuple[str, str]]) -> bytes:
    encoding = ""
    for key, value in headers:
        if key.lower() == "transfer-encoding":
            encoding = value.lower()
    if "chunked" in encoding:
        rest = _unchunk(rest)
    return rest[:MAX_BYTES]


def _auth_header(headers: dict | None) -> str:
    if not headers:
        return ""
    token = str(headers.get("Authorization") or headers.get("authorization") or "")
    if re.fullmatch(r"Bearer [A-Za-z0-9._\-]+", token):
        return f"Authorization: {token}\r\n"
    return ""


def _request(
    target: Target,
    method: str,
    read_body: bool,
    body: bytes = b"",
    headers: dict | None = None,
) -> tuple[int, list[tuple[str, str]], bytes]:
    sock = socket.create_connection((target.ip, target.port), timeout=TIMEOUT)
    try:
        if target.scheme == "https":
            context = _ssl_context()
            sock = context.wrap_socket(sock, server_hostname=target.hostname)
        sock.settimeout(TIMEOUT)
        request_path = target.path or "/"
        header_host = target.hostname
        if (target.scheme == "https" and target.port != 443) or (
            target.scheme == "http" and target.port != 80
        ):
            header_host = f"{target.hostname}:{target.port}"
        extra = _auth_header(headers)
        if body:
            extra += f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
        payload = (
            f"{method} {request_path} HTTP/1.1\r\n"
            f"Host: {header_host}\r\n"
            f"User-Agent: {USER_AGENT}\r\n"
            "Accept: application/json,text/html,*/*;q=0.8\r\n"
            "Connection: close\r\n"
            f"{extra}\r\n"
        ).encode("ascii") + (body or b"")
        sock.sendall(payload)
        chunks = []
        total = 0
        while total < MAX_BYTES + 64_000:
            block = sock.recv(65536)
            if not block:
                break
            chunks.append(block)
            total += len(block)
        raw = b"".join(chunks)
    finally:
        try:
            sock.close()
        except OSError:
            pass
    head, _, rest = raw.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1", errors="replace").split("\r\n")
    status = 0
    if lines:
        parts = lines[0].split()
        if len(parts) >= 2 and parts[1].isdigit():
            status = int(parts[1])
    headers = []
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers.append((name.strip(), value.strip()))
    body = _body_bytes(rest, headers) if read_body else b""
    return status, headers, body


class HostPacer:
    """호스트마다 동시 연결과 요청 간격을 지키고, 막히면 그 호스트를 닫는다."""

    def __init__(self, *, gap: float = HOST_GAP, inflight: int = HOST_INFLIGHT, clock=None, sleep=None, max_pause: float = HOST_PAUSE):
        self.gap = gap
        self.inflight = inflight
        self.max_pause = max_pause
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._lock = threading.Lock()
        self._hosts: dict[str, dict] = {}

    def reset(self) -> None:
        with self._lock:
            self._hosts.clear()

    def any_closed(self) -> bool:
        with self._lock:
            return any(state.get("closed") for state in self._hosts.values())

    def _state(self, host: str) -> dict:
        return self._hosts.setdefault(host, {"next": 0.0, "open": 0, "closed": False})

    def acquire(self, host: str) -> str:
        host = (host or "").lower()
        while True:
            with self._lock:
                state = self._state(host)
                if state["closed"]:
                    return BLOCK_MESSAGE
                now = self._clock()
                if state["open"] < self.inflight and now >= state["next"]:
                    state["open"] += 1
                    state["next"] = now + self.gap
                    return ""
                if state["open"] >= self.inflight:
                    delay = 0.02
                else:
                    delay = max(0.0, state["next"] - now)
            if delay:
                self._sleep(delay)

    def finish(self, host: str, status: int, retry_after: float | None, *, can_retry: bool) -> str:
        host = (host or "").lower()
        with self._lock:
            state = self._state(host)
            state["open"] = max(0, state["open"] - 1)
            if status not in BLOCK_STATUSES:
                return ""
            pause = 1.0 if retry_after is None else max(0.0, retry_after)
            pause = min(pause, self.max_pause)
            state["next"] = max(state["next"], self._clock() + pause)
            if can_retry:
                return "retry"
            state["closed"] = True
            return "stop"


_PACER = HostPacer()


def reset_host_limits() -> None:
    """새 목록 수집을 시작할 때 호스트 제한을 다시 연다."""
    _PACER.reset()


def limit_notice() -> str:
    if _PACER.any_closed():
        return BLOCK_MESSAGE
    return ""


def _retry_after(headers: list[tuple[str, str]]) -> float | None:
    raw = ""
    for key, value in headers:
        if key.lower() == "retry-after":
            raw = value.strip()
            break
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def fetch(
    url: str,
    *,
    method: str = "GET",
    read_body: bool = True,
    resolve=None,
    body: bytes | None = None,
    headers: dict | None = None,
    pacer: HostPacer | None = None,
    transport=None,
) -> HttpResult:
    gate = pacer or _PACER
    send = transport or _request
    current = url
    seen = set()
    payload = body or b""
    auth = headers
    for _ in range(MAX_REDIRECTS + 1):
        if current in seen:
            return HttpResult(url=current, status=0, content_type="", body=b"", error="리다이렉트가 반복됩니다.")
        seen.add(current)
        try:
            kwargs = {"resolve": resolve} if resolve is not None else {}
            target = check_url(current, **kwargs)
        except UrlRejected as exc:
            return HttpResult(url=current, status=0, content_type="", body=b"", error=exc.message)
        attempt = 0
        while True:
            blocked = gate.acquire(target.hostname)
            if blocked:
                return HttpResult(url=target.url, status=0, content_type="", body=b"", error=blocked)
            try:
                status, response_headers, received = send(
                    target, "POST" if payload else method, read_body, payload, auth
                )
            except (TimeoutError, socket.timeout):
                gate.finish(target.hostname, 0, None, can_retry=False)
                return HttpResult(url=target.url, status=0, content_type="", body=b"", error="시간 초과")
            except OSError:
                gate.finish(target.hostname, 0, None, can_retry=False)
                return HttpResult(url=target.url, status=0, content_type="", body=b"", error="연결 실패")
            decision = gate.finish(
                target.hostname,
                status,
                _retry_after(response_headers),
                can_retry=attempt == 0,
            )
            if decision == "retry":
                attempt += 1
                continue
            if decision == "stop":
                return HttpResult(
                    url=target.url,
                    status=status,
                    content_type="",
                    body=b"",
                    error=BLOCK_MESSAGE,
                )
            break
        if status in {301, 302, 303, 307, 308}:
            nxt = _decode_location(response_headers, target.url)
            if not nxt:
                return HttpResult(url=target.url, status=status, content_type="", body=b"", error="리다이렉트 주소 없음")
            nxt_host = (urlsplit(nxt).hostname or "").lower().rstrip(".")
            if nxt_host != target.hostname:
                auth = None
            current = nxt
            payload = b""
            continue
        content_type = ""
        for key, value in response_headers:
            if key.lower() == "content-type":
                content_type = value
                break
        return HttpResult(url=target.url, status=status, content_type=content_type, body=received)
    return HttpResult(url=current, status=0, content_type="", body=b"", error="리다이렉트가 너무 많습니다.")
