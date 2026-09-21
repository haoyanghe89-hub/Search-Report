from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx

from marketpulse.investigation.ports.external import FetchRequest, FetchResult
from marketpulse.investigation.recording.errors import (
    ProviderCallError,
    RateLimitedError,
    SecurityBlockedError,
)

HostValidator = Callable[[str], Awaitable[bool]]
_REDIRECTS = {301, 302, 303, 307, 308}


async def is_public_host(host: str) -> bool:
    try:
        values = await asyncio.get_running_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(host, None)
        )
    except socket.gaierror:
        return False
    addresses = [ipaddress.ip_address(item[4][0]) for item in values]
    return bool(addresses) and all(address.is_global for address in addresses)


def _safe_host(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SecurityBlockedError("only HTTP(S) URLs with a host are allowed")
    if parsed.username or parsed.password:
        raise SecurityBlockedError("credential-bearing URLs are blocked")
    host = parsed.hostname.casefold().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise SecurityBlockedError("local destinations are blocked")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if not address.is_global:
        raise SecurityBlockedError("private and special-use destinations are blocked")
    return host


class HttpxFetchAdapter:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        host_validator: HostValidator = is_public_host,
        user_agent: str = "InvestigationPlatform/0.1",
        max_redirects: int = 5,
    ) -> None:
        self._client = client
        self._host_validator = host_validator
        self._user_agent = user_agent
        self._max_redirects = max_redirects

    async def fetch(self, request: FetchRequest) -> FetchResult:
        current = str(request.url)
        for redirect_count in range(self._max_redirects + 1):
            host = _safe_host(current)
            if not await self._host_validator(host):
                raise SecurityBlockedError("destination did not resolve exclusively to public IPs")
            try:
                response = await self._client.get(
                    current,
                    headers={"User-Agent": self._user_agent},
                    timeout=request.timeout_seconds,
                    follow_redirects=False,
                )
            except httpx.TimeoutException as error:
                raise TimeoutError("fetch timed out") from error
            except httpx.TransportError as error:
                raise ProviderCallError("fetch transport failed") from error

            if response.status_code in _REDIRECTS:
                location = response.headers.get("location")
                if not location or redirect_count >= self._max_redirects:
                    raise ProviderCallError("invalid or excessive redirect chain")
                current = urljoin(current, location)
                continue
            if response.status_code == 429:
                raise RateLimitedError("fetch provider rate limited the request")
            if response.status_code >= 400:
                raise ProviderCallError(f"fetch provider returned HTTP {response.status_code}")

            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type not in request.accepted_content_types:
                raise SecurityBlockedError("response MIME type is not allowed")
            if len(response.content) > request.max_bytes:
                raise SecurityBlockedError("response exceeds configured size limit")
            return FetchResult.model_validate(
                {
                    "final_url": current,
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "body": response.content,
                    "fetched_at": datetime.now(UTC),
                    "headers": {
                        key: value
                        for key, value in response.headers.items()
                        if key.casefold() in {"etag", "last-modified", "content-language"}
                    },
                }
            )
        raise ProviderCallError("redirect chain did not terminate")
