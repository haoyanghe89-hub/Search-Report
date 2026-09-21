from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from marketpulse.investigation.ports.external import (
    FetchResult,
    ModelMessage,
    ModelRequest,
    SearchRequest,
)
from marketpulse.investigation.recording.canonical import canonical_request, request_fingerprint


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


def test_fetch_result_binary_body_round_trips_through_json() -> None:
    result = FetchResult(
        final_url="https://example.test/report.pdf",
        status_code=200,
        content_type="application/pdf",
        body=b"%PDF-\x00\xff",
        fetched_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    assert FetchResult.model_validate_json(result.model_dump_json()) == result


def test_canonical_request_is_stable_and_version_sensitive() -> None:
    request = SearchRequest(query="  East Palestine  ", max_results=5)
    first = canonical_request("search", request)
    assert first == canonical_request("search", request)
    assert json.loads(first)["request"]["query"] == "East Palestine"

    changed = request.model_copy(update={"config_version": "runtime-v2"})
    assert request_fingerprint("search", request) != request_fingerprint("search", changed)


def test_model_schema_is_part_of_canonical_request() -> None:
    request = ModelRequest[Answer](
        messages=(ModelMessage(role="user", content="Return a typed answer."),),
        response_model=Answer,
        response_schema_version="answer-v1",
        prompt_version="prompt-v1",
    )
    payload = json.loads(canonical_request("structured-generate", request))
    assert payload["response_schema"]["properties"]["value"]["type"] == "string"
    assert "response_model" not in payload["request"]
