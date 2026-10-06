from __future__ import annotations

import socket
from collections.abc import AsyncIterator
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from marketpulse.adapters.investigation_search import PublicSearchPortAdapter
from marketpulse.domain.research import SearchCandidate, SearchQuery
from marketpulse.investigation.adapters.fetch import HttpxFetchAdapter, is_public_host
from marketpulse.investigation.adapters.model import OpenAICompatibleModelAdapter
from marketpulse.investigation.ports.external import (
    FetchRequest,
    ModelMessage,
    ModelRequest,
    SearchRequest,
)
from marketpulse.investigation.recording.errors import ProviderCallError, SecurityBlockedError


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


@pytest.mark.asyncio
async def test_fetch_headers_and_http_500_recovery() -> None:
    calls = []
    sleeps = []

    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(500)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"record")

    async def public_host(_):
        return True

    async def sleep(delay):
        sleeps.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await HttpxFetchAdapter(
            client,
            host_validator=public_host,
            accept_language="zh-CN,zh;q=0.9,en;q=0.7",
            sleep=sleep,
        ).fetch(FetchRequest(url="https://public.test/story"))
    assert result.status_code == 200
    assert "text/html" in calls[0].headers["accept"]
    assert calls[0].headers["accept-language"].startswith("zh-CN")
    assert sleeps == [0.25]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reason", [(403, "HTTP_FORBIDDEN"), (429, "HTTP_RATE_LIMITED")])
async def test_hard_denial_cooldown_avoids_repeat_network_work(status, reason) -> None:
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(status)

    async def public_host(_):
        return True

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = HttpxFetchAdapter(client, host_validator=public_host, max_retries=0)
        request = FetchRequest(url="https://public.test/denied?secret=PRIVATE")
        for _ in range(2):
            with pytest.raises(Exception) as failure:
                await adapter.fetch(request)
            assert failure.value.reason_code == reason
            assert failure.value.diagnostics["domain"] == "public.test"
            assert "PRIVATE" not in str(failure.value.diagnostics)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_strict_fake_dns_rejection_explains_required_opt_in(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.42", 443))],
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200))
    ) as client:
        with pytest.raises(SecurityBlockedError) as failure:
            await HttpxFetchAdapter(client).fetch(FetchRequest(url="https://public.example/story"))
    assert failure.value.reason_code == "NON_PUBLIC_DNS"
    assert "MARKETPULSE_ALLOW_PROXY_DNS" in str(failure.value)


@pytest.mark.asyncio
async def test_html_challenge_is_classified_without_retrying_or_admitting_body() -> None:
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=(
                b"<html><title>Just a moment...</title>"
                b"<form id='challenge-form'>Verify human</form></html>"
            ),
        )

    async def public_host(_):
        return True

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = HttpxFetchAdapter(client, host_validator=public_host)
        for _ in range(2):
            with pytest.raises(ProviderCallError) as failure:
                await adapter.fetch(FetchRequest(url="https://public.test/story"))
            assert failure.value.reason_code == "CHALLENGE_PAGE"
            assert failure.value.diagnostics["http_status"] == 200
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address,allowed",
    [
        ("198.18.0.42", True),
        ("198.19.1.2", True),
        ("10.0.0.1", False),
        ("127.0.0.1", False),
        ("169.254.169.254", False),
    ],
)
async def test_trusted_proxy_dns_only_allows_fake_ip_range(
    monkeypatch: pytest.MonkeyPatch, address: str, allowed: bool
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
    )
    assert not await is_public_host("public.example")
    assert await is_public_host("public.example", allow_proxy_dns=True) is allowed


@pytest.mark.asyncio
async def test_proxy_mode_still_blocks_literal_fake_ip_urls() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200))
    ) as client:
        with pytest.raises(SecurityBlockedError):
            await HttpxFetchAdapter(client, allow_proxy_dns=True).fetch(
                FetchRequest(url="http://198.18.0.42/")
            )


class LegacySearchFixture:
    async def search(self, query: SearchQuery, *, limit: int = 8) -> list[SearchCandidate]:
        assert query.text == "East Palestine"
        return [
            SearchCandidate(
                query_id=query.id,
                title="NTSB report",
                url="https://www.ntsb.gov/example.pdf",
                snippet="official report",
                rank=1,
                source_hint="official",
            )
        ][:limit]


@pytest.mark.asyncio
async def test_public_search_bridge_does_not_expose_legacy_types() -> None:
    result = await PublicSearchPortAdapter(LegacySearchFixture()).search(
        SearchRequest(query="East Palestine", max_results=3)
    )
    assert result.items[0].source_type_hint == "official"
    assert result.items[0].is_official is True
    assert result.items[0].is_first_hand is False
    assert result.provider == "public-search"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://crowdstrike-news.example.org/story",
        "https://agency.gov.evil.org/story",
        "https://gov.example.org/story",
    ],
)
async def test_search_keyword_domain_match_does_not_establish_primary_provenance(url: str) -> None:
    class MisleadingSearch:
        async def search(self, query: SearchQuery, *, limit: int = 8) -> list[SearchCandidate]:
            return [
                SearchCandidate(
                    query_id=query.id,
                    title="CrowdStrike news",
                    rank=1,
                    url=url,
                    source_hint="official",
                )
            ]

    result = await PublicSearchPortAdapter(MisleadingSearch()).search(
        SearchRequest(query="CrowdStrike outage")
    )
    assert result.items[0].source_type_hint == "web"
    assert result.items[0].is_official is False
    assert result.items[0].is_first_hand is False


@pytest.mark.asyncio
async def test_http_fetch_validates_redirect_targets_and_accepts_pdf() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://public.test/report"})
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-fixture",
        )

    async def public_host(host: str) -> bool:
        return host == "public.test"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await HttpxFetchAdapter(client, host_validator=public_host).fetch(
            FetchRequest(url="https://public.test/start")
        )
    assert result.content_type == "application/pdf"
    assert result.body.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_http_fetch_blocks_private_redirect_before_second_request() -> None:
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    async def public_host(host: str) -> bool:
        return host == "public.test"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SecurityBlockedError):
            await HttpxFetchAdapter(client, host_validator=public_host).fetch(
                FetchRequest(url="https://public.test/start")
            )
    assert requests == ["https://public.test/start"]


class CountingStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.read_chunks = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in (b"12345678", b"abcdefgh", b"ignored-"):
            self.read_chunks += 1
            yield chunk

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_http_fetch_stops_streaming_when_size_limit_is_exceeded() -> None:
    stream = CountingStream()

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, stream=stream)

    async def public_host(_: str) -> bool:
        return True

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SecurityBlockedError):
            await HttpxFetchAdapter(client, host_validator=public_host).fetch(
                FetchRequest(url="https://public.test/file", max_bytes=10)
            )
    assert stream.read_chunks == 2


@pytest.mark.asyncio
async def test_http_fetch_retries_transient_503_once() -> None:
    calls = 0
    sleeps: list[float] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ready")

    async def public_host(_: str) -> bool:
        return True

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await HttpxFetchAdapter(
            client, host_validator=public_host, max_retries=1, sleep=sleep
        ).fetch(FetchRequest(url="https://public.test/file"))
    assert result.body == b"ready"
    assert calls == 2
    assert sleeps == [0.25]


class FakeCompletions:
    async def create(self, **_: object) -> object:
        return SimpleNamespace(
            id="response-1",
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"value":"typed"}'))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3),
        )


@pytest.mark.asyncio
async def test_openai_compatible_adapter_returns_typed_result() -> None:
    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    adapter = OpenAICompatibleModelAdapter(
        client, provider="deepseek", default_model="deepseek-chat"
    )
    result = await adapter.generate(
        ModelRequest[Answer](
            messages=(ModelMessage(role="user", content="answer"),),
            response_model=Answer,
            response_schema_version="answer-v1",
            prompt_version="prompt-v1",
        )
    )
    assert result.output == Answer(value="typed")
    assert result.model == "deepseek-chat"
    assert result.usage.input_tokens == 10
