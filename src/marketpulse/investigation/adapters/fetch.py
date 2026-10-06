from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from marketpulse.investigation.ingestion.html import is_html_challenge
from marketpulse.investigation.ports.external import FetchRequest, FetchResult
from marketpulse.investigation.recording.errors import (
    ExternalCallError,
    ProviderCallError,
    RateLimitedError,
    SecurityBlockedError,
)

HostValidator = Callable[[str], Awaitable[bool]]
Sleep = Callable[[float], Awaitable[None]]
_REDIRECTS = {301, 302, 303, 307, 308}
_LOGGER = logging.getLogger(__name__)


async def is_public_host(host: str, *, allow_proxy_dns: bool = False) -> bool:
    try:
        values = await asyncio.get_running_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(host, None)
        )
    except socket.gaierror:
        return False
    addresses = [ipaddress.ip_address(item[4][0]) for item in values]
    fake_ip_range = ipaddress.ip_network("198.18.0.0/15")
    return bool(addresses) and all(
        address.is_global or (allow_proxy_dns and address in fake_ip_range) for address in addresses
    )


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
        host_validator: HostValidator | None = None,
        allow_proxy_dns: bool = False,
        user_agent: str = "InvestigationPlatform/0.1",
        max_redirects: int = 5,
        max_retries: int = 2,
        sleep: Sleep = asyncio.sleep,
        accept_language: str = "en-US,en;q=0.8",
    ) -> None:
        if max_redirects < 0 or max_retries < 0:
            raise ValueError("redirect and retry limits must be nonnegative")
        self._client = client

        async def configured_host_validator(host: str) -> bool:
            return await is_public_host(host, allow_proxy_dns=allow_proxy_dns)

        self._host_validator = host_validator or configured_host_validator
        self._user_agent = user_agent
        self._max_redirects = max_redirects
        self._max_retries = max_retries
        self._sleep = sleep
        self._accept_language = accept_language
        self._denied: dict[str, tuple[float, ExternalCallError]] = {}

    @staticmethod
    def _failure(
        error_type: type[ExternalCallError],
        reason: str,
        host: str,
        status: int | None = None,
        size: int = 0,
    ) -> ExternalCallError:
        message = reason
        if reason == "NON_PUBLIC_DNS":
            message += (
                ": public DNS required; for a trusted fake-IP proxy explicitly configure "
                "MARKETPULSE_ALLOW_PROXY_DNS"
            )
        return error_type(
            message,
            reason_code=reason,
            diagnostics={
                "domain": host,
                "http_status": status,
                "html_bytes": size,
                "reason": reason,
            },
        )

    async def fetch(self, request: FetchRequest) -> FetchResult:
        url = str(request.url)
        try:
            denied = self._denied.get(url)
            if denied and time.monotonic() < denied[0]:
                previous = denied[1]
                raise type(previous)(
                    str(previous),
                    reason_code=previous.reason_code,
                    diagnostics=previous.diagnostics.copy(),
                )
            result = await self._fetch(request)
        except (ExternalCallError, TimeoutError) as error:
            if isinstance(error, ExternalCallError) and error.reason_code in {
                "HTTP_FORBIDDEN",
                "HTTP_RATE_LIMITED",
                "CHALLENGE_PAGE",
            }:
                if len(self._denied) >= 256:
                    self._denied.pop(next(iter(self._denied)))
                self._denied[url] = (time.monotonic() + 120, error)
            values = {
                "domain": urlparse(url).hostname,
                "reason": type(error).__name__,
                **getattr(error, "diagnostics", {}),
            }
            _LOGGER.info("fetch_result %s", json.dumps(values, sort_keys=True))
            raise
        self._denied.pop(url, None)
        _LOGGER.info(
            "fetch_result %s",
            json.dumps(
                {
                    "domain": result.final_url.host,
                    "http_status": result.status_code,
                    "html_bytes": len(result.body),
                    "reason": "FETCHED",
                },
                sort_keys=True,
            ),
        )
        return result

    async def _fetch(self, request: FetchRequest) -> FetchResult:
        current = str(request.url)
        for redirect_count in range(self._max_redirects + 1):
            try:
                host = _safe_host(current)
            except SecurityBlockedError as error:
                raise self._failure(
                    SecurityBlockedError, "UNSAFE_URL", urlparse(current).hostname or ""
                ) from error
            if not await self._host_validator(host):
                raise self._failure(SecurityBlockedError, "NON_PUBLIC_DNS", host)
            for attempt in range(self._max_retries + 1):
                try:
                    async with self._client.stream(
                        "GET",
                        current,
                        headers={
                            "User-Agent": self._user_agent,
                            "Accept": (
                                "text/html,application/xhtml+xml,application/pdf,"
                                "text/plain;q=0.9,*/*;q=0.5"
                            ),
                            "Accept-Language": self._accept_language,
                        },
                        timeout=request.timeout_seconds,
                        follow_redirects=False,
                    ) as response:
                        if response.status_code == 429 or response.status_code >= 500:
                            if attempt < self._max_retries:
                                await self._sleep(0.25 * (2**attempt))
                                continue
                            if response.status_code == 429:
                                raise self._failure(
                                    RateLimitedError,
                                    "HTTP_RATE_LIMITED",
                                    host,
                                    response.status_code,
                                )
                            raise self._failure(
                                ProviderCallError, "HTTP_ERROR", host, response.status_code
                            )
                        if response.status_code in _REDIRECTS:
                            location = response.headers.get("location")
                            if not location or redirect_count >= self._max_redirects:
                                raise self._failure(
                                    ProviderCallError, "REDIRECT_ERROR", host, response.status_code
                                )
                            current = urljoin(current, location)
                            break
                        if response.status_code >= 400:
                            raise self._failure(
                                ProviderCallError,
                                "HTTP_FORBIDDEN" if response.status_code == 403 else "HTTP_ERROR",
                                host,
                                response.status_code,
                            )

                        content_type = (
                            response.headers.get("content-type", "").split(";", 1)[0].lower()
                        )
                        if content_type not in request.accepted_content_types:
                            raise self._failure(
                                SecurityBlockedError, "MIME_NOT_ALLOWED", host, response.status_code
                            )
                        length = response.headers.get("content-length")
                        if length and length.isdecimal() and int(length) > request.max_bytes:
                            raise self._failure(
                                SecurityBlockedError, "BODY_TOO_LARGE", host, response.status_code
                            )
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > request.max_bytes:
                                raise self._failure(
                                    SecurityBlockedError,
                                    "BODY_TOO_LARGE",
                                    host,
                                    response.status_code,
                                    len(body),
                                )
                            body.extend(chunk)
                        if content_type in {
                            "text/html",
                            "application/xhtml+xml",
                        } and is_html_challenge(BeautifulSoup(bytes(body[:65536]), "html.parser")):
                            raise self._failure(
                                ProviderCallError,
                                "CHALLENGE_PAGE",
                                host,
                                response.status_code,
                                len(body),
                            )
                        return FetchResult.model_validate(
                            {
                                "final_url": current,
                                "status_code": response.status_code,
                                "content_type": content_type,
                                "body": bytes(body),
                                "fetched_at": datetime.now(UTC),
                                "headers": {
                                    key: value
                                    for key, value in response.headers.items()
                                    if key.casefold()
                                    in {"etag", "last-modified", "content-language"}
                                },
                            }
                        )
                except (httpx.TimeoutException, httpx.TransportError) as error:
                    if attempt < self._max_retries:
                        await self._sleep(0.25 * (2**attempt))
                        continue
                    if isinstance(error, httpx.TimeoutException):
                        raise TimeoutError("fetch timed out") from error
                    raise ProviderCallError("fetch transport failed") from error
            else:
                raise ProviderCallError("fetch retries did not terminate")
        raise ProviderCallError("redirect chain did not terminate")
