"""리다이렉트마다 주소를 다시 검사하고, 확인한 IP로만 연결한다.

같은 호스트는 동시에 두 연결만 열고, 요청 시작 사이에는 간격을 둔다.
403·429·503이면 Retry-After만큼 쉰 뒤 한 번만 다시 보낸다. 429가 또 오거나 403·503이
연달아 세 번 막히면 그 호스트를 잠시 멈췄다가 다시 연다. 시간 초과와 연결 실패도 한 번 다시 보낸다.
본문이 필요 없는 확인은 헤더만 읽고 끊는다.
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
from urllib.parse import quote, urljoin, urlsplit

from site_audit.guard import Target, UrlRejected, check_url

USER_AGENT = "site-audit/0.1"
MAX_REDIRECTS = 5
MAX_BYTES = 2_000_000
CONNECT_TIMEOUT = 8
TIMEOUT = 20
HOST_GAP = 0.5
HOST_GAP_MAX = 3.0
SLOW_GAP = 5.0
HOST_INFLIGHT = 2
HOST_PAUSE = 15.0
BLOCK_PAUSE = 5.0
HOST_STRIKES = 3
HOST_COOLDOWN = 90.0
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


def _ascii_request_target(path: str) -> str:
    """요청 줄은 ASCII만 된다. 주소에 섞인 문자는 UTF-8 퍼센트로 보낸다."""
    text = path or "/"
    if text.isascii():
        return text
    return "".join(ch if ord(ch) < 128 else quote(ch, safe="") for ch in text)


def _ascii_host(host: str) -> str:
    if host.isascii():
        return host
    return host.encode("idna").decode("ascii")


def _request_bytes(
    target: Target,
    method: str,
    body: bytes = b"",
    headers: dict | None = None,
) -> bytes:
    request_path = _ascii_request_target(target.path or "/")
    header_host = _ascii_host(target.hostname)
    if (target.scheme == "https" and target.port != 443) or (
        target.scheme == "http" and target.port != 80
    ):
        header_host = f"{header_host}:{target.port}"
    extra = _auth_header(headers)
    if body:
        extra += f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
    return (
        f"{method} {request_path} HTTP/1.1\r\n"
        f"Host: {header_host}\r\n"
        f"User-Agent: {USER_AGENT}\r\n"
        "Accept: application/json,text/html,*/*;q=0.8\r\n"
        "Connection: close\r\n"
        f"{extra}\r\n"
    ).encode("ascii") + (body or b"")


def _request(
    target: Target,
    method: str,
    read_body: bool,
    body: bytes = b"",
    headers: dict | None = None,
) -> tuple[int, list[tuple[str, str]], bytes]:
    payload = _request_bytes(target, method, body, headers)
    sock = socket.create_connection((target.ip, target.port), timeout=CONNECT_TIMEOUT)
    try:
        if target.scheme == "https":
            context = _ssl_context()
            sock = context.wrap_socket(sock, server_hostname=target.hostname)
        sock.settimeout(TIMEOUT)
        sock.sendall(payload)
        chunks = []
        total = 0
        while total < MAX_BYTES + 64_000:
            block = sock.recv(65536)
            if not block:
                break
            chunks.append(block)
            total += len(block)
            # 상태와 헤더만 필요하면 본문은 받지 않는다.
            if not read_body and b"\r\n\r\n" in b"".join(chunks[-2:]):
                break
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
    """호스트마다 동시 연결과 요청 간격을 지키고, 계속 막히면 그 호스트를 잠시 닫는다."""

    def __init__(
        self,
        *,
        gap: float = HOST_GAP,
        inflight: int = HOST_INFLIGHT,
        clock=None,
        sleep=None,
        max_pause: float = HOST_PAUSE,
        strikes: int = HOST_STRIKES,
        cooldown: float = HOST_COOLDOWN,
        slow_gap: float = SLOW_GAP,
    ):
        self.slow_gap = slow_gap
        self.gap = gap
        self.inflight = inflight
        self.max_pause = max_pause
        self.strikes = strikes
        self.cooldown = cooldown
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._lock = threading.Lock()
        self._hosts: dict[str, dict] = {}

    def reset(self) -> None:
        with self._lock:
            self._hosts.clear()

    def any_closed(self) -> bool:
        with self._lock:
            now = self._clock()
            return any(self._closed(state, now) for state in self._hosts.values())

    def _state(self, host: str) -> dict:
        return self._hosts.setdefault(
            host,
            {"next": 0.0, "slow_next": 0.0, "open": 0, "closed": False, "until": 0.0, "strikes": 0, "gap": self.gap},
        )

    def hold_seconds(self, host: str) -> float:
        """그 호스트가 닫혀 있으면 다시 열릴 때까지 남은 초."""
        host = (host or "").lower()
        with self._lock:
            state = self._hosts.get(host)
            now = self._clock()
            if state is None or not self._closed(state, now):
                return 0.0
            return max(0.0, state["until"] - now)

    def _closed(self, state: dict, now: float) -> bool:
        if not state["closed"]:
            return False
        if now < state["until"]:
            return True
        # 쉬는 시간이 지나면 다시 연다. 또 막히면 바로 닫는다.
        state["closed"] = False
        state["strikes"] = max(0, self.strikes - 1)
        return False

    def acquire(self, host: str, *, slow: bool = False) -> str:
        """slow는 사이트가 더 엄하게 세는 경로다. 그 경로끼리는 훨씬 긴 간격을 따로 둔다."""
        host = (host or "").lower()
        while True:
            with self._lock:
                state = self._state(host)
                now = self._clock()
                if self._closed(state, now):
                    return BLOCK_MESSAGE
                ready = state["next"] if not slow else max(state["next"], state["slow_next"])
                if state["open"] < self.inflight and now >= ready:
                    state["open"] += 1
                    state["next"] = now + state["gap"]
                    if slow:
                        state["slow_next"] = now + self.slow_gap
                    return ""
                if state["open"] >= self.inflight:
                    delay = 0.02
                else:
                    delay = max(0.0, ready - now)
            if delay:
                self._sleep(delay)

    def finish(self, host: str, status: int, retry_after: float | None, *, can_retry: bool) -> str:
        host = (host or "").lower()
        with self._lock:
            state = self._state(host)
            state["open"] = max(0, state["open"] - 1)
            if status not in BLOCK_STATUSES:
                if status:
                    state["strikes"] = 0
                return ""
            pause = BLOCK_PAUSE if retry_after is None else max(0.0, retry_after)
            pause = min(pause, self.max_pause)
            now = self._clock()
            state["next"] = max(state["next"], now + pause)
            if can_retry:
                return "retry"
            # 403·503은 그 주소만 막힌 것일 수 있어 연달아 막힐 때만 호스트를 닫는다.
            state["strikes"] += 1
            if status == 429 or state["strikes"] >= self.strikes:
                state["closed"] = True
                state["until"] = now + self.cooldown
                # 막힌 호스트는 남은 검수 동안 더 천천히 부른다.
                if self.gap:
                    state["gap"] = min(max(HOST_GAP_MAX, self.gap), state["gap"] * 1.5)
                return "stop"
            return "blocked"


_PACER = HostPacer()


def reset_host_limits() -> None:
    """새 목록 수집을 시작할 때 호스트 제한을 다시 연다."""
    _PACER.reset()


_slow_paths: tuple[str, ...] = ()


def set_slow_paths(paths, gap: float | None = None) -> None:
    """rules.json의 느린 경로와 그 간격을 받는다."""
    global _slow_paths
    _slow_paths = tuple(str(item) for item in (paths or []) if str(item))
    if isinstance(gap, (int, float)) and gap > 0:
        _PACER.slow_gap = float(gap)


def is_slow(url: str) -> bool:
    if not _slow_paths:
        return False
    path = urlsplit(url).path
    return any(mark in path for mark in _slow_paths)


def hold_seconds(host: str) -> float:
    return _PACER.hold_seconds(host)


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
        resent = False
        while True:
            blocked = gate.acquire(target.hostname, slow=is_slow(target.url))
            if blocked:
                return HttpResult(url=target.url, status=0, content_type="", body=b"", error=blocked)
            try:
                status, response_headers, received = send(
                    target, "POST" if payload else method, read_body, payload, auth
                )
            except OSError as exc:
                gate.finish(target.hostname, 0, None, can_retry=False)
                if not resent:
                    resent = True
                    continue
                slow = isinstance(exc, (TimeoutError, socket.timeout))
                return HttpResult(
                    url=target.url, status=0, content_type="", body=b"",
                    error="시간 초과" if slow else "연결 실패",
                )
            except Exception:
                # 주소 인코딩 실패가 연결 칸을 붙잡으면 다음 검수가 끝나지 않는다.
                gate.finish(target.hostname, 0, None, can_retry=False)
                return HttpResult(
                    url=target.url, status=0, content_type="", body=b"",
                    error="이 주소는 요청할 수 없습니다.",
                )
            decision = gate.finish(
                target.hostname,
                status,
                _retry_after(response_headers),
                can_retry=attempt == 0,
            )
            if decision == "retry":
                attempt += 1
                continue
            if decision in ("stop", "blocked"):
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
