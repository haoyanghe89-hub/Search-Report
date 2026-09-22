from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import re
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS

from marketpulse.budget import RunBudget
from marketpulse.config import Settings
from marketpulse.domain.research import SearchCandidate, SearchQuery
from marketpulse.errors import SearchUnavailableError

Sleep = Callable[[float], Awaitable[None]]
_TRACKING_PARAMS = {"gclid", "fbclid", "mc_cid", "mc_eid", "ref", "source"}
_SEARCH_REQUEST_TIMEOUT_SECONDS = 5.0
_GENERIC_QUERY_TERMS = {
    "app",
    "best",
    "compare",
    "comparison",
    "cost",
    "demand",
    "feature",
    "market",
    "price",
    "pricing",
    "site",
    "software",
    "subscription",
    "technology",
    "tool",
    "top",
    "trend",
}


def _terms(text: str) -> set[str]:
    values = set()
    for token in re.findall(r"[a-z0-9]+", text.casefold()):
        normalized = token[:-1] if len(token) > 3 and token.endswith("s") else token
        if normalized not in _GENERIC_QUERY_TERMS and (len(normalized) >= 3 or normalized == "ai"):
            values.add(normalized)
    return values


def _is_relevant(candidate: SearchCandidate, query: SearchQuery) -> bool:
    wanted = _terms(query.text)
    if not wanted:
        return True
    haystack = _terms(f"{candidate.title} {candidate.snippet} {candidate.url}")
    required = 2 if len(wanted) >= 2 else 1
    return len(wanted & haystack) >= required


class SearchClient(Protocol):
    async def search(self, query: SearchQuery, *, limit: int = 8) -> list[SearchCandidate]: ...


def canonicalize_url(raw_url: str) -> str:
    parsed = urlparse(raw_url.strip())
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            parsed = urlparse(target)
    if parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/a"):
        encoded = parse_qs(parsed.query).get("u", [""])[0]
        if encoded.startswith("a1"):
            payload = encoded[2:]
            try:
                padding = "=" * (-len(payload) % 4)
                parsed = urlparse(base64.urlsafe_b64decode(payload + padding).decode("utf-8"))
            except (binascii.Error, UnicodeDecodeError):
                pass
    if parsed.netloc.endswith("search.yahoo.com") or parsed.netloc.endswith("r.search.yahoo.com"):
        match = re.search(r"/RU=([^/]+)/RK=", parsed.path)
        if match:
            parsed = urlparse(unquote(match.group(1)))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only public HTTP(S) URLs are accepted")
    if parsed.username or parsed.password:
        raise ValueError("credential-bearing URLs are rejected")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("local URLs are rejected")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("non-public IP URLs are rejected")
    query_pairs: list[tuple[str, str]] = []
    for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
        if key.lower().startswith("utm_") or key.lower() in _TRACKING_PARAMS:
            continue
        query_pairs.extend((key, value) for value in values)
    clean_path = parsed.path or "/"
    if clean_path != "/":
        clean_path = clean_path.rstrip("/")
    return urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), clean_path, "", urlencode(query_pairs), "")
    )


class PublicSearchClient:
    duckduckgo_endpoint = "https://html.duckduckgo.com/html/"
    bing_endpoint = "https://www.bing.com/search"
    yahoo_endpoint = "https://search.yahoo.com/search"

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: Settings,
        budget: RunBudget,
        *,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.http_client = http_client
        self.settings = settings
        self.budget = budget
        self.sleep = sleep

    async def search(self, query: SearchQuery, *, limit: int = 8) -> list[SearchCandidate]:
        self.budget.reserve_search()
        last_error: Exception | None = None
        providers = (
            (self.duckduckgo_endpoint, {"q": query.text, "kl": "us-en"}, "duckduckgo"),
            (self.bing_endpoint, {"q": query.text, "setlang": "en-US"}, "bing"),
            (self.yahoo_endpoint, {"p": query.text}, "yahoo"),
        )
        for endpoint, params, provider in providers:
            for attempt in range(self.settings.max_retries + 1):
                try:
                    response = await self.http_client.get(
                        endpoint,
                        params=params,
                        headers={"User-Agent": self.settings.search_user_agent},
                        timeout=min(
                            self.settings.page_timeout_seconds,
                            _SEARCH_REQUEST_TIMEOUT_SECONDS,
                        ),
                    )
                    if response.status_code in {202, 429, 502, 503, 504}:
                        raise httpx.HTTPStatusError(
                            "search provider rejected or throttled the request",
                            request=response.request,
                            response=response,
                        )
                    response.raise_for_status()
                    if provider == "duckduckgo":
                        results = self._parse_duckduckgo(response.text, query, limit)
                    elif provider == "bing":
                        results = self._parse_bing(response.text, query, limit)
                    else:
                        results = self._parse_yahoo(response.text, query, limit)
                    if results:
                        return results
                    break
                except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                    last_error = exc
                    if isinstance(exc, httpx.TimeoutException):
                        break
                    retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                        exc.response.status_code in {429, 502, 503, 504}
                    )
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 202:
                        break
                    if attempt >= self.settings.max_retries or not retryable:
                        break
                    await self.sleep(float(2**attempt))
        try:
            resilient_results = await asyncio.wait_for(
                asyncio.to_thread(self._search_ddgs, query, limit),
                timeout=25.0,
            )
            if resilient_results:
                return resilient_results
        except Exception as exc:
            last_error = exc
        raise SearchUnavailableError(f"搜索失败: {query.text}: {type(last_error).__name__}")

    @classmethod
    def _search_ddgs(cls, query: SearchQuery, limit: int) -> list[SearchCandidate]:
        candidates: list[SearchCandidate] = []
        seen: set[str] = set()
        # Skip engines that reliably time out from CN networks (google, mojeek);
        # pick the region matching the query language for better recall.
        has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in query.text)
        region = "cn-zh" if has_cjk else "us-en"
        backend = "bing,duckduckgo,yahoo,brave,wikipedia"
        for item in DDGS(timeout=10).text(
            query.text, max_results=limit, region=region, backend=backend
        ):
            href = item.get("href")
            if not isinstance(href, str):
                continue
            candidate = cls._candidate(
                query=query,
                title=str(item.get("title") or ""),
                href=href,
                snippet=str(item.get("body") or ""),
                rank=len(candidates) + 1,
            )
            if candidate is None or not _is_relevant(candidate, query):
                continue
            url = str(candidate.url)
            if url in seen:
                continue
            seen.add(url)
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
        return candidates

    @staticmethod
    def _candidate(
        *,
        query: SearchQuery,
        title: str,
        href: str,
        snippet: str,
        rank: int,
    ) -> SearchCandidate | None:
        try:
            url = canonicalize_url(href)
        except ValueError:
            return None
        host = urlparse(url).hostname or ""
        official_tokens = {token for token in query.text.lower().split() if len(token) >= 4}
        source_hint: Literal["official", "research", "media", "other"] = (
            "official"
            if any(token in host.replace("-", "") for token in official_tokens)
            else "other"
        )
        return SearchCandidate.model_validate(
            {
                "query_id": query.id,
                "title": title or host,
                "url": url,
                "snippet": snippet[:2000],
                "rank": rank,
                "source_hint": source_hint,
            }
        )

    @classmethod
    def _parse_duckduckgo(cls, html: str, query: SearchQuery, limit: int) -> list[SearchCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[SearchCandidate] = []
        seen: set[str] = set()
        for anchor in soup.select("a.result__a"):
            href = anchor.get("href")
            if not isinstance(href, str):
                continue
            result = anchor.find_parent(class_="result")
            snippet_node = result.select_one(".result__snippet") if result else None
            candidate = cls._candidate(
                query=query,
                title=anchor.get_text(" ", strip=True),
                href=href,
                snippet=snippet_node.get_text(" ", strip=True) if snippet_node else "",
                rank=len(candidates) + 1,
            )
            if candidate is None:
                continue
            url = str(candidate.url)
            if url in seen:
                continue
            seen.add(url)
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
        return candidates

    @classmethod
    def _parse_bing(cls, html: str, query: SearchQuery, limit: int) -> list[SearchCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[SearchCandidate] = []
        seen: set[str] = set()
        for result in soup.select("li.b_algo"):
            anchor = result.select_one("h2 a")
            if anchor is None:
                continue
            href = anchor.get("href")
            if not isinstance(href, str):
                continue
            snippet_node = result.select_one(".b_caption p")
            candidate = cls._candidate(
                query=query,
                title=anchor.get_text(" ", strip=True),
                href=href,
                snippet=snippet_node.get_text(" ", strip=True) if snippet_node else "",
                rank=len(candidates) + 1,
            )
            if candidate is None:
                continue
            url = str(candidate.url)
            if (
                url in seen
                or (urlparse(url).hostname or "").endswith("bing.com")
                or not _is_relevant(candidate, query)
            ):
                continue
            seen.add(url)
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
        return candidates

    @classmethod
    def _parse_yahoo(cls, html: str, query: SearchQuery, limit: int) -> list[SearchCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[SearchCandidate] = []
        seen: set[str] = set()
        for result in soup.select("div.algo, li.algo"):
            anchor = result.select_one("h3 a")
            if anchor is None:
                continue
            href = anchor.get("href")
            if not isinstance(href, str):
                continue
            snippet_node = result.select_one(".compText, p")
            candidate = cls._candidate(
                query=query,
                title=anchor.get_text(" ", strip=True),
                href=href,
                snippet=snippet_node.get_text(" ", strip=True) if snippet_node else "",
                rank=len(candidates) + 1,
            )
            if candidate is None:
                continue
            url = str(candidate.url)
            if (
                url in seen
                or "yahoo.com" in (urlparse(url).hostname or "")
                or not _is_relevant(candidate, query)
            ):
                continue
            seen.add(url)
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
        return candidates


# Backward-compatible name retained for callers and fixtures created before Bing fallback.
DuckDuckGoSearchClient = PublicSearchClient
