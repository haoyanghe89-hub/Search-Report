from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import re
import time
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS
from ddgs.engines import ENGINES

from marketpulse.budget import RunBudget
from marketpulse.config import Settings
from marketpulse.domain.research import SearchCandidate, SearchQuery
from marketpulse.errors import SearchUnavailableError

Sleep = Callable[[float], Awaitable[None]]
_TRACKING_PARAMS = {"gclid", "fbclid", "mc_cid", "mc_eid", "ref", "source"}
_SEARCH_REQUEST_TIMEOUT_SECONDS = 5.0
_SEARCH_TOTAL_TIMEOUT_SECONDS = 25.0
_DDGS_AWAIT_TIMEOUT_SECONDS = 7.0
_SEARCH_CIRCUIT_SECONDS = 60.0
_SEARCH_BACKENDS = ("ddgs:yahoo", "bing", "ddgs:brave", "duckduckgo", "ddgs:wikipedia")
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
        backends: tuple[str, ...] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.http_client = http_client
        self.settings = settings
        self.budget = budget
        self.sleep = sleep
        self.backends = _SEARCH_BACKENDS if backends is None else backends
        self.clock = clock
        self._disabled_until: dict[str, float] = {}
        self._preferred_backend: str | None = None
        self._ddgs_tasks: set[asyncio.Task[list[SearchCandidate]]] = set()

    async def search(self, query: SearchQuery, *, limit: int = 8) -> list[SearchCandidate]:
        self.budget.reserve_search()
        try:
            async with asyncio.timeout(
                min(_SEARCH_TOTAL_TIMEOUT_SECONDS, self.budget.remaining_seconds)
            ):
                return await self._search(query, limit)
        except TimeoutError as exc:
            raise SearchUnavailableError("搜索后端超时；请稍后重试或补充原始来源") from exc

    async def _search(self, query: SearchQuery, limit: int) -> list[SearchCandidate]:
        last_error: Exception | None = None
        providers = sorted(self.backends, key=lambda name: name != self._preferred_backend)
        for provider in providers:
            if self.clock() < self._disabled_until.get(provider, 0):
                continue
            # Provider fallback is internal: one query still consumes one budget reservation.
            for attempt in range(min(self.settings.max_retries, 1) + 1):
                try:
                    results = await self._request_provider(provider, query, limit)
                    if results:
                        self._preferred_backend = provider
                        self._disabled_until.pop(provider, None)
                        return results
                    # A 200 challenge page is not usable search material. Try other providers.
                    self._disabled_until[provider] = self.clock() + _SEARCH_CIRCUIT_SECONDS
                    break
                except Exception as exc:
                    last_error = exc
                    retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                        exc.response.status_code == 429 or exc.response.status_code >= 500
                    )
                    cooldown = _SEARCH_CIRCUIT_SECONDS
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                        cooldown *= 2
                    self._disabled_until[provider] = self.clock() + cooldown
                    if attempt >= min(self.settings.max_retries, 1) or not retryable:
                        break
                    await self.sleep(0.25 * 2**attempt)
        category = type(last_error).__name__ if last_error else "CIRCUIT_OPEN_OR_NO_RESULTS"
        raise SearchUnavailableError(
            f"搜索后端暂不可用（{category}）；"
            "请稍后重试或补充可访问的原始来源"
        )

    async def _request_provider(
        self, provider: str, query: SearchQuery, limit: int
    ) -> list[SearchCandidate]:
        if provider.startswith("ddgs:"):
            backend = provider.partition(":")[2]
            if backend not in ENGINES.get("text", {}):
                return []
            # wait_for cannot kill a Python worker thread; cap outstanding work including
            # timed-out calls, and consume eventual exceptions without spawning more threads.
            if len(self._ddgs_tasks) >= self.settings.max_search_concurrency:
                return []
            task = asyncio.create_task(
                asyncio.to_thread(self._search_ddgs, query, limit, backend=backend)
            )
            self._ddgs_tasks.add(task)

            def finished(done: asyncio.Task[list[SearchCandidate]]) -> None:
                self._ddgs_tasks.discard(done)
                if not done.cancelled():
                    done.exception()

            task.add_done_callback(finished)
            return await asyncio.wait_for(asyncio.shield(task), timeout=_DDGS_AWAIT_TIMEOUT_SECONDS)
        providers = {
            "duckduckgo": (
                self.duckduckgo_endpoint,
                {"q": query.text, "kl": "us-en"},
                self._parse_duckduckgo,
            ),
            "bing": (self.bing_endpoint, {"q": query.text, "setlang": "en-US"}, self._parse_bing),
            "yahoo": (self.yahoo_endpoint, {"p": query.text}, self._parse_yahoo),
        }
        endpoint, params, parser = providers[provider]
        response = await self.http_client.get(
            endpoint,
            params=params,
            headers={"User-Agent": self.settings.search_user_agent},
            timeout=min(self.settings.page_timeout_seconds, _SEARCH_REQUEST_TIMEOUT_SECONDS),
        )
        if response.status_code == 202:
            raise httpx.HTTPStatusError(
                "search challenge", request=response.request, response=response
            )
        response.raise_for_status()
        return parser(response.text, query, limit)

    @classmethod
    def _search_ddgs(
        cls, query: SearchQuery, limit: int, *, backend: str = "yahoo"
    ) -> list[SearchCandidate]:
        if backend not in ENGINES.get("text", {}):
            return []
        candidates: list[SearchCandidate] = []
        seen: set[str] = set()
        # Skip engines that reliably time out from CN networks (google, mojeek);
        # pick the region matching the query language for better recall.
        has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in query.text)
        region = "cn-zh" if has_cjk else "us-en"
        for item in DDGS(timeout=5).text(
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
