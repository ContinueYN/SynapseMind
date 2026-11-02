"""SSRF guard for a user-supplied model base URL.

The browser only *saves* the URL; the API server is what calls it. Without a
check, ``https://127.0.0.1:6379`` or a hostname resolving to a private address
would turn the settings page into a request proxy for the deployment's own
network (Redis, Postgres, the Docker gateway, cloud metadata endpoints).

Policy:

* HTTPS only, no userinfo, no query/fragment (also enforced by the application
  validator; repeated here so the guard is safe on its own).
* Known provider hosts are allowed without resolving them, so an offline box can
  still save DeepSeek/OpenAI/OpenRouter.
* Every other host is resolved with ``socket.getaddrinfo`` and rejected when
  *any* answer is not globally routable (loopback, private, link-local,
  multicast, reserved, unspecified, IPv4-mapped private addresses included).
* A host that cannot be resolved is rejected: the server could not verify it,
  so it must not call it.

This is best effort, not a firewall. DNS can change between the check and the
request (rebinding), which is why the allow-list is by exact hostname and why
the request never follows redirects. It raises the cost of the obvious attacks;
it does not make a hostile URL safe.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urlsplit

from synapse.application.credentials.service import (
    KNOWN_PROVIDER_HOSTS,
    CredentialValidationError,
)

# Suffixes that name the local machine or a private network by convention. They
# are refused before DNS so a misconfigured resolver cannot make them look public.
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")

_MAX_ADDRESSES = 16


class SsrfGuard:
    """Reject URLs whose host could reach this deployment's own network."""

    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str] | None = None,
        resolver: object = None,
    ) -> None:
        self._allowed_hosts = allowed_hosts if allowed_hosts is not None else KNOWN_PROVIDER_HOSTS
        # Injectable for tests; defaults to ``socket.getaddrinfo``.
        self._resolver = resolver if resolver is not None else socket.getaddrinfo

    def check(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme.lower() != "https":
            raise CredentialValidationError("base_url 必须使用 https://。")
        host = (parts.hostname or "").strip().lower()
        if not host:
            raise CredentialValidationError("base_url 缺少主机名。")
        if host in self._allowed_hosts:
            return
        if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
            raise CredentialValidationError(
                "base_url 不能指向本机或内网地址；请使用公开可访问的 https:// 地址。"
            )

        literal = _parse_ip(host)
        if literal is not None:
            _require_global(literal)
            return

        port = parts.port or 443
        try:
            infos = self._resolve(host, port)
        except OSError as exc:
            raise CredentialValidationError(
                f"无法解析 base_url 的主机名 {host!r}；请填写可公开访问的地址。"
            ) from exc
        addresses = _addresses(infos)
        if not addresses:
            raise CredentialValidationError(
                f"无法解析 base_url 的主机名 {host!r}；请填写可公开访问的地址。"
            )
        for address in addresses[:_MAX_ADDRESSES]:
            _require_global(address)

    def _resolve(self, host: str, port: int) -> list[object]:
        resolve = self._resolver
        if not callable(resolve):  # pragma: no cover - composition always passes one
            raise OSError("no resolver")
        result = resolve(host, port, type=socket.SOCK_STREAM)
        return list(result) if isinstance(result, Iterable) else []


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _addresses(infos: Iterable[object]) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    found: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        if not isinstance(info, tuple) or len(info) < 5:
            continue
        sockaddr = info[4]
        if not isinstance(sockaddr, tuple) or not sockaddr:
            continue
        raw = sockaddr[0]
        if not isinstance(raw, str):
            continue
        parsed = _parse_ip(raw)
        if parsed is None:
            continue
        if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
            parsed = parsed.ipv4_mapped
        if parsed not in found:
            found.append(parsed)
    return found


def _require_global(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if not address.is_global:
        raise CredentialValidationError(
            "base_url 解析到了本机或内网地址；请使用公开可访问的 https:// 地址。"
        )
