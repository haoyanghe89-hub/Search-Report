from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from marketpulse.adapters.investigation_search import PublicSearchPortAdapter
from marketpulse.domain.research import SearchCandidate, SearchQuery
from marketpulse.investigation.adapters.fetch import HttpxFetchAdapter
from marketpulse.investigation.adapters.model import OpenAICompatibleModelAdapter
from marketpulse.investigation.ports.external import (
    FetchRequest,
    ModelMessage,
    ModelRequest,
    SearchRequest,
)
from marketpulse.investigation.recording.errors import SecurityBlockedError


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


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
    assert result.provider == "public-search"


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
