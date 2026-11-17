"""공개 http(s)만 연다. 사설망·localhost·링크로컬·계정 포함 주소는 거부한다."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_PORTS = {80, 443}


@dataclass(frozen=True)
class Target:
    url: str
    scheme: str
    hostname: str
    port: int
    path: str
    ip: str


class UrlRejected(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _blocked_ip(raw: str) -> bool:
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return True
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    ):
        return True
    # CGNAT, 문서용, 벤치마크 대역은 공개 사이트가 아니다.
    blocked = (
        ipaddress.ip_network("100.64.0.0/10"),
        ipaddress.ip_network("192.0.2.0/24"),
        ipaddress.ip_network("198.51.100.0/24"),
        ipaddress.ip_network("203.0.113.0/24"),
        ipaddress.ip_network("198.18.0.0/15"),
    )
    return any(addr in net for net in blocked)


def check_url(url: str, resolve=socket.getaddrinfo) -> Target:
    if not isinstance(url, str) or not url.strip():
        raise UrlRejected("주소가 비어 있습니다.")
    text = url.strip()
    parts = urlsplit(text)
    scheme = (parts.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise UrlRejected("http 또는 https 주소만 검사합니다.")
    if parts.username is not None or parts.password is not None:
        raise UrlRejected("계정 정보가 섞인 주소는 열지 않습니다.")
    host = parts.hostname
    if not host:
        raise UrlRejected("주소 형식이 올바르지 않습니다.")
    host = host.lower().rstrip(".")
    port = parts.port or (443 if scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise UrlRejected("80 또는 443 포트만 엽니다.")
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _blocked_ip(str(literal)):
            raise UrlRejected("공개 웹 주소가 아닙니다.")
        ip = str(literal)
    else:
        try:
            infos = resolve(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise UrlRejected("주소를 찾지 못했습니다.") from exc
        ips = []
        for info in infos:
            candidate = info[4][0]
            if _blocked_ip(candidate):
                raise UrlRejected("공개 웹 주소가 아닙니다.")
            ips.append(candidate)
        if not ips:
            raise UrlRejected("주소를 찾지 못했습니다.")
        ip = ips[0]
    normalized = f"{scheme}://{host}"
    if (scheme == "https" and port != 443) or (scheme == "http" and port != 80):
        normalized += f":{port}"
    normalized += path
    return Target(url=normalized, scheme=scheme, hostname=host, port=port, path=path, ip=ip)
