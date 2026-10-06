from __future__ import annotations

import httpx
import pytest

from marketpulse.adapters.search import PublicSearchClient, canonicalize_url
from marketpulse.budget import RunBudget
from marketpulse.config import Settings
from marketpulse.domain.research import SearchQuery
from marketpulse.errors import SearchUnavailableError


@pytest.mark.asyncio
async def test_500_backoff_and_provider_fallback_charge_only_one_search(settings: Settings) -> None:
    calls = []
    sleep_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "html.duckduckgo.com":
            return httpx.Response(500, request=request)
        return httpx.Response(
            200,
            request=request,
            text=(
                '<li class="b_algo"><h2><a href="https://acme.example/">Acme event</a></h2>'
                '<div class="b_caption"><p>Acme event records</p></div></li>'
            ),
        )

    async def sleep(delay: float) -> None:
        sleep_calls.append(delay)

    budget = RunBudget.start(settings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        search = PublicSearchClient(
            client, settings, budget, sleep=sleep, backends=("duckduckgo", "bing")
        )
        result = await search.search(SearchQuery(id="q", text="acme event", intent="product"))
        await search.search(SearchQuery(id="q2", text="acme event", intent="product"))
    assert result
    assert calls == ["html.duckduckgo.com", "html.duckduckgo.com", "www.bing.com", "www.bing.com"]
    assert sleep_calls == [0.25]
    assert budget.search_queries_used == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", 429, 500])
async def test_failed_backend_circuit_skips_then_recovers(settings: Settings, failure) -> None:
    now = [0.0]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            if failure == "timeout":
                raise httpx.ConnectTimeout("timeout", request=request)
            return httpx.Response(failure, request=request)
        return httpx.Response(
            200, request=request, text='<a class="result__a" href="https://acme.example">Acme</a>'
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        search = PublicSearchClient(
            client,
            settings.model_copy(update={"max_retries": 0}),
            RunBudget.start(settings),
            clock=lambda: now[0],
            backends=("duckduckgo",),
        )
        query = SearchQuery(id="q", text="acme", intent="product")
        with pytest.raises(SearchUnavailableError):
            await search.search(query)
        with pytest.raises(SearchUnavailableError):
            await search.search(query)
        assert calls == 1
        now[0] = 301
        assert await search.search(query)
        assert calls == 2


def test_ddgs_disabled_backend_never_falls_back_to_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import Mock

    import marketpulse.adapters.search as module

    ddgs = Mock()
    monkeypatch.setattr(module, "DDGS", ddgs)
    monkeypatch.setattr(module, "ENGINES", {"text": {"yahoo": object}})
    assert (
        PublicSearchClient._search_ddgs(
            SearchQuery(id="q", text="acme", intent="product"), 8, backend="bing"
        )
        == []
    )
    ddgs.assert_not_called()


def test_ddgs_uses_one_installed_backend_and_preserves_relevance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import Mock

    import marketpulse.adapters.search as module

    ddgs = Mock()
    ddgs.return_value.text.return_value = [
        {"title": "Acme event", "href": "https://acme.example", "body": "Acme event record"},
        {"title": "Unrelated", "href": "https://other.example", "body": "unrelated content"},
    ]
    monkeypatch.setattr(module, "DDGS", ddgs)
    monkeypatch.setattr(module, "ENGINES", {"text": {"yahoo": object}})
    result = PublicSearchClient._search_ddgs(
        SearchQuery(id="q", text="acme event", intent="product"), 8, backend="yahoo"
    )
    assert len(result) == 1
    assert ddgs.return_value.text.call_args.kwargs["backend"] == "yahoo"


@pytest.mark.asyncio
async def test_timed_out_ddgs_thread_is_bounded_across_circuit_expiry(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import threading

    import marketpulse.adapters.search as module

    release = threading.Event()
    now = [0.0]
    calls = []

    def stalled(query, limit, *, backend):
        calls.append(backend)
        release.wait(timeout=1)
        return []

    monkeypatch.setattr(module, "ENGINES", {"text": {"yahoo": object}})
    monkeypatch.setattr(module, "_DDGS_AWAIT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(PublicSearchClient, "_search_ddgs", staticmethod(stalled))
    async with httpx.AsyncClient() as client:
        search = PublicSearchClient(
            client,
            settings.model_copy(update={"max_retries": 0, "max_search_concurrency": 1}),
            RunBudget.start(settings),
            backends=("ddgs:yahoo",),
            clock=lambda: now[0],
        )
        query = SearchQuery(id="q", text="event", intent="product")
        try:
            with pytest.raises(SearchUnavailableError):
                await search.search(query)
            now[0] = 301
            with pytest.raises(SearchUnavailableError):
                await search.search(query)
            assert calls == ["yahoo"]
        finally:
            release.set()
            await asyncio.gather(*search._ddgs_tasks, return_exceptions=True)
        assert not search._ddgs_tasks


@pytest.mark.asyncio
async def test_cancellation_does_not_retry_or_switch_provider(settings: Settings) -> None:
    import asyncio

    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        raise asyncio.CancelledError()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        search = PublicSearchClient(
            client, settings, RunBudget.start(settings), backends=("duckduckgo", "bing")
        )
        with pytest.raises(asyncio.CancelledError):
            await search.search(SearchQuery(id="q", text="event", intent="product"))
    assert calls == ["html.duckduckgo.com"]


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
        search = PublicSearchClient(
            client,
            settings,
            RunBudget.start(settings),
            sleep=no_sleep,
            backends=("duckduckgo", "bing", "yahoo"),
        )
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
        search = PublicSearchClient(
            client, settings, RunBudget.start(settings), backends=("duckduckgo", "bing", "yahoo")
        )
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
        search = PublicSearchClient(
            client,
            settings,
            RunBudget.start(settings),
            backends=("duckduckgo", "bing", "yahoo"),
            sleep=lambda _: _done(),
        )
        results = await search.search(
            SearchQuery(id="q1", text="acme software pricing", intent="pricing")
        )
    assert duckduckgo_calls == 2
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
        search = PublicSearchClient(
            client, settings, RunBudget.start(settings), backends=("duckduckgo", "bing", "yahoo")
        )
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

    def fallback(_: SearchQuery, __: int, *, backend: str) -> list[object]:
        assert backend == "yahoo"
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
            backends=("duckduckgo", "bing", "yahoo", "ddgs:yahoo"),
        )
        results = await search.search(
            SearchQuery(id="q1", text="AI meeting notes software", intent="product")
        )
    assert str(results[0].url) == "https://otter.ai/"


async def _done() -> None:
    return None
