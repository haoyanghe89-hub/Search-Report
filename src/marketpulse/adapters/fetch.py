from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from marketpulse.adapters.robots import RobotsPolicy
from marketpulse.budget import RunBudget
from marketpulse.config import Settings
from marketpulse.domain.research import SearchCandidate

_ALLOWED_CONTENT_TYPES = {"text/html", "text/plain", "application/xhtml+xml"}
_PROXY_DNS_RANGE = ipaddress.ip_network("198.18.0.0/15")


@dataclass(frozen=True)
class FetchedPage:
    candidate: SearchCandidate
    final_url: str
    content_type: str
    body: bytes
    fetched_at: datetime


async def _is_public_host(hostname: str, *, allow_proxy_dns: bool = False) -> bool:
    try:
        addresses = await asyncio.get_running_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(hostname, None)
        )
    except socket.gaierror:
        return False
    parsed_addresses = [ipaddress.ip_address(item[4][0]) for item in addresses]
    return bool(parsed_addresses) and all(
        address.is_global or (allow_proxy_dns and address in _PROXY_DNS_RANGE)
        for address in parsed_addresses
    )


class PageFetcher:
    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        budget: RunBudget,
        robots: RobotsPolicy,
    ) -> None:
        self.client = client
        self.settings = settings
        self.budget = budget
        self.robots = robots

    async def fetch(self, candidate: SearchCandidate) -> FetchedPage:
        self.budget.reserve_page()
        url = str(candidate.url)
        hostname = urlparse(url).hostname or ""
        if not await _is_public_host(hostname, allow_proxy_dns=self.settings.allow_proxy_dns):
            raise ValueError("目标域名不是公开网络地址")
        if not await self.robots.allowed(url):
            raise PermissionError("robots.txt 不允许抓取")
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = await self.client.get(
                    url,
                    headers={"User-Agent": self.settings.user_agent},
                    timeout=self.settings.page_timeout_seconds,
                    follow_redirects=True,
                )
                if response.status_code in {429, 502, 503, 504}:
                    raise httpx.HTTPStatusError(
                        "transient page response", request=response.request, response=response
                    )
                response.raise_for_status()
                if not await _is_public_host(
                    response.url.host,
                    allow_proxy_dns=self.settings.allow_proxy_dns,
                ):
                    raise ValueError("重定向目标不是公开网络地址")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in _ALLOWED_CONTENT_TYPES:
                    raise ValueError(f"不支持的内容类型: {content_type or 'unknown'}")
                if len(response.content) > self.settings.max_page_bytes:
                    raise ValueError("页面超过 2 MiB 限制")
                return FetchedPage(
                    candidate=candidate,
                    final_url=str(response.url),
                    content_type=content_type,
                    body=response.content,
                    fetched_at=datetime.now(UTC),
                )
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    exc.response.status_code in {429, 502, 503, 504}
                )
                if attempt >= self.settings.max_retries or not retryable:
                    break
                await asyncio.sleep(float(2**attempt))
        if last_error:
            raise last_error
        raise RuntimeError("页面抓取失败")
