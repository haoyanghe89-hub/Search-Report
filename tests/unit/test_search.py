from __future__ import annotations

import httpx
import pytest

from marketpulse.adapters.search import PublicSearchClient, canonicalize_url
from marketpulse.budget import RunBudget
from marketpulse.config import Settings
from marketpulse.domain.research import SearchQuery


def test_canonicalize_url_removes_tracking_and_fragment() -> None:
    value = canonicalize_url("https://Example.com/pricing/?utm_source=x&a=1#top")
    assert value == "https://example.com/pricing?a=1"


def test_canonicalize_url_decodes_bing_redirect() -> None:
    value = canonicalize_url(
        "https://www.bing.com/ck/a?!&&u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9wcmljaW5n&ntb=1"
    )
    assert value == "https://example.com/pricing"


def test_canonicalize_url_decodes_yahoo_redirect() -> None:
    value = canonicalize_url(
        "https://r.search.yahoo.com/x/RU=https%3A%2F%2Fotter.ai%2Fpricing/RK=2/RS=x"
    )
    assert value == "https://otter.ai/pricing"


@pytest.mark.parametrize(
    "url",
    ["file:///tmp/x", "http://localhost/x", "http://127.0.0.1/x", "https://u:p@x.com"],
)
def test_canonicalize_url_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError):
        canonicalize_url(url)


def test_parse_duckduckgo_html_deduplicates() -> None:
    html = """
    <div class="result"><a class="result__a" href="https://acme.com/pricing?utm_source=x">Acme</a>
    <div class="result__snippet">Plans from $10 monthly.</div></div>
    <div class="result"><a class="result__a" href="https://acme.com/pricing">Duplicate</a></div>
    <div class="result"><a class="result__a" href="https://example.org/report">Report</a></div>
    """
    query = SearchQuery(id="q1", text="acme pricing", intent="pricing")
    results = PublicSearchClient._parse_duckduckgo(html, query, 8)
    assert len(results) == 2
    assert str(results[0].url) == "https://acme.com/pricing"
    assert results[0].snippet == "Plans from $10 monthly."


@pytest.mark.asyncio
async def test_search_retries_transient_response(settings: Settings) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            request=request,
            text='<a class="result__a" href="https://example.com">Example</a>',
        )

    async def no_sleep(_: float) -> None:
        return None

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        search = PublicSearchClient(client, settings, RunBudget.start(settings), sleep=no_sleep)
        results = await search.search(SearchQuery(id="q1", text="market example", intent="demand"))
    assert calls == 2
    assert len(results) == 1


@pytest.mark.asyncio
async def test_search_falls_back_to_bing_after_duckduckgo_challenge(
    settings: Settings,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "html.duckduckgo.com":
            return httpx.Response(202, request=request, text="challenge")
        return httpx.Response(
            200,
            request=request,
            text=(
                '<li class="b_algo"><h2><a href="https://acme.example/pricing">Acme</a></h2>'
                '<div class="b_caption"><p>Plans from $20 monthly.</p></div></li>'
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        search = PublicSearchClient(client, settings, RunBudget.start(settings))
        results = await search.search(
            SearchQuery(id="q1", text="acme software pricing", intent="pricing")
        )
    assert len(results) == 1
    assert str(results[0].url) == "https://acme.example/pricing"


@pytest.mark.asyncio
async def test_search_falls_back_after_one_provider_timeout(settings: Settings) -> None:
    duckduckgo_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal duckduckgo_calls
        if request.url.host == "html.duckduckgo.com":
            duckduckgo_calls += 1
            raise httpx.ConnectTimeout("provider unavailable", request=request)
        return httpx.Response(
            200,
            request=request,
            text=(
                '<li class="b_algo"><h2><a href="https://acme.example/pricing">Acme</a></h2>'
                '<div class="b_caption"><p>Plans from $20 monthly.</p></div></li>'
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        search = PublicSearchClient(client, settings, RunBudget.start(settings))
        results = await search.search(
            SearchQuery(id="q1", text="acme software pricing", intent="pricing")
        )
    assert duckduckgo_calls == 1
    assert str(results[0].url) == "https://acme.example/pricing"


@pytest.mark.asyncio
async def test_search_falls_back_to_yahoo_when_bing_results_are_irrelevant(
    settings: Settings,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "html.duckduckgo.com":
            return httpx.Response(202, request=request, text="challenge")
        if request.url.host == "www.bing.com":
            return httpx.Response(
                200,
                request=request,
                text=(
                    '<li class="b_algo"><h2><a href="https://openai.com/">OpenAI</a></h2>'
                    '<div class="b_caption"><p>General AI research.</p></div></li>'
                ),
            )
        return httpx.Response(
            200,
            request=request,
            text=(
                '<div class="algo"><h3><a href="https://r.search.yahoo.com/x/'
                'RU=https%3A%2F%2Fotter.ai%2Fpricing/RK=2/RS=x">Otter AI Pricing</a></h3>'
                '<div class="compText">AI meeting notes plans for teams.</div></div>'
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        search = PublicSearchClient(client, settings, RunBudget.start(settings))
        results = await search.search(
            SearchQuery(id="q1", text="AI meeting notes software pricing", intent="pricing")
        )
    assert len(results) == 1
    assert str(results[0].url) == "https://otter.ai/pricing"


@pytest.mark.asyncio
async def test_search_uses_resilient_fallback_when_html_providers_fail(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, request=request)

    def fallback(_: SearchQuery, __: int) -> list[object]:
        query = SearchQuery(id="q1", text="AI meeting notes software", intent="product")
        candidate = PublicSearchClient._candidate(
            query=query,
            title="Otter AI Meeting Notes",
            href="https://otter.ai/",
            snippet="AI meeting notes and transcription for teams.",
            rank=1,
        )
        assert candidate is not None
        return [candidate]

    monkeypatch.setattr(PublicSearchClient, "_search_ddgs", staticmethod(fallback))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        search = PublicSearchClient(
            client,
            settings,
            RunBudget.start(settings),
            sleep=lambda _: _done(),
        )
        results = await search.search(
            SearchQuery(id="q1", text="AI meeting notes software", intent="product")
        )
    assert str(results[0].url) == "https://otter.ai/"


async def _done() -> None:
    return None
