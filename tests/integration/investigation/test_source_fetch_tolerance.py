"""Source-local failures must not become investigation-wide failures."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.domain.claims import ResearchGap
from marketpulse.investigation.domain.enums import RunMode
from marketpulse.investigation.harness.persistence import RunBudgetExceededError
from marketpulse.investigation.ingestion.registry import DocumentParserRegistry
from marketpulse.investigation.live_runtime import LivePorts
from marketpulse.investigation.persistence.models import ExecutionStepRow
from marketpulse.investigation.ports.external import SearchResult, SearchResultItem
from marketpulse.investigation.recording.errors import (
    ProviderCallError,
    RateLimitedError,
    ReplayCacheMissError,
    SecurityBlockedError,
)
from marketpulse.investigation.server import create_app
from marketpulse.investigation.services.source_acquisition import (
    AcquisitionRequest,
    SourceAcquisitionService,
)
from tests.integration.investigation.test_live_runtime import (
    OutagePorts,
    _create,
    _drain,
    _settings,
)
from tests.integration.investigation.test_source_acquisition import (
    NOW,
    FetchFixture,
    SearchFixture,
    _seed,
)


def source_error(kind, domain="bad.example"):
    if kind == "timeout":
        return TimeoutError("PRIVATE_ERROR_TEXT")
    error_type, status, reason = {
        "rate": (RateLimitedError, 429, "HTTP_RATE_LIMITED"),
        "provider429": (ProviderCallError, 429, "HTTP_RATE_LIMITED"),
        "forbidden": (ProviderCallError, 403, "HTTP_FORBIDDEN"),
        "security": (SecurityBlockedError, None, "NON_PUBLIC_DNS"),
    }[kind]
    return error_type(
        "PRIVATE_ERROR_TEXT",
        reason_code=reason,
        diagnostics={"domain": domain, "http_status": status, "reason": reason},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 3])
@pytest.mark.parametrize("kind", ["rate", "provider429", "forbidden", "timeout", "security"])
async def test_prepare_skips_source_failure_and_keeps_good_material(
    investigation_store, tmp_path, caplog, concurrency, kind
):
    repository, _, _ = investigation_store
    _seed(repository, "TOLERANT", RunMode.LIVE)
    fetched = []

    class MixedFetch(FetchFixture):
        async def fetch(self, request):
            fetched.append(request.url.host)
            if request.url.host == "bad.example":
                raise source_error(kind)
            return await super().fetch(request)

    service = SourceAcquisitionService(
        repository=repository,
        blobs=LocalContentAddressedBlobStorage(tmp_path / "blobs"),
        search=SearchFixture(),
        fetch=MixedFetch(),
        parsers=DocumentParserRegistry.default(),
        tolerate_fetch_errors=True,
        fetch_concurrency=concurrency,
    )
    result = SearchResult(
        provider="fixture",
        retrieved_at=NOW,
        items=(
            SearchResultItem(
                title="Inaccessible record", url="https://bad.example/secret?q=PRIVATE", rank=1
            ),
            SearchResultItem(title="Accessible record", url="https://good.example/record", rank=2),
        ),
    )
    with caplog.at_level("INFO"):
        prepared = await service.prepare(
            AcquisitionRequest(
                investigation_id="I-TOLERANT", run_id="RUN-TOLERANT", query="public event"
            ),
            logical_step_key="research:mixed:round-1",
            search_result=result,
        )
    assert set(fetched) == {"bad.example", "good.example"}
    bad, good = prepared.result.sources
    assert prepared.result.valid_source_count == 1
    assert bad.discovered and not bad.fetched and not bad.valid_for_statistics
    assert not bad.artifact_ids and bad.snapshot_id is None
    assert good.fetched and good.parsed and good.evidence_eligible and good.artifact_ids
    for entity in prepared.business_outputs:
        repository.add(entity)
    gap = repository.get(ResearchGap, bad.gap_ids[0])
    assert gap.source_id == bad.source_id
    assert gap.gap_type.value == "UNREADABLE_SOURCE"
    assert gap.reason == (getattr(source_error(kind), "reason_code", None) or "FETCH_TIMEOUT")
    assert "bad.example" in " ".join(gap.suggested_actions)
    assert "稍后重试" in " ".join(gap.suggested_actions)
    if kind in {"rate", "provider429", "forbidden"}:
        assert str(source_error(kind).diagnostics["http_status"]) in " ".join(gap.suggested_actions)
    assert "PRIVATE" not in caplog.text
    assert "bad.example" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["cancel", "budget", "replay", "bug", "strict-rate"])
async def test_prepare_does_not_swallow_control_errors(investigation_store, tmp_path, kind):
    repository, _, _ = investigation_store
    _seed(repository, "STRICT", RunMode.LIVE)
    error = {
        "cancel": asyncio.CancelledError(),
        "budget": RunBudgetExceededError("fetch call budget exhausted"),
        "replay": ReplayCacheMissError(operation="fetch", request_fingerprint="missing"),
        "bug": ValueError("invalid local state"),
        "strict-rate": source_error("rate"),
    }[kind]

    class FailedFetch:
        async def fetch(self, request):
            raise error

    service = SourceAcquisitionService(
        repository=repository,
        blobs=LocalContentAddressedBlobStorage(tmp_path / "blobs"),
        search=SearchFixture(),
        fetch=FailedFetch(),
        parsers=DocumentParserRegistry.default(),
        tolerate_fetch_errors=kind != "strict-rate",
    )
    with pytest.raises(type(error)):
        await service.prepare(
            AcquisitionRequest(
                investigation_id="I-STRICT", run_id="RUN-STRICT", query="public event"
            ),
            logical_step_key="research:strict:round-1",
        )


@pytest.mark.parametrize("concurrency", [1, 4])
@pytest.mark.parametrize("all_rate_limited", [False, True])
def test_live_source_failures_continue_or_block_cleanly(
    tmp_path, monkeypatch, concurrency, all_rate_limited
):
    class MixedPorts(OutagePorts):
        def __init__(self):
            super().__init__()
            self.fetched = []

        async def search(self, request):
            result = await super().search(request)
            return result.model_copy(
                update={
                    "items": tuple(
                        SearchResultItem(
                            title="CrowdStrike public record",
                            url=f"https://{host}/record",
                            rank=index + 1,
                            publisher="Independent test newsroom",
                        )
                        for index, host in enumerate(
                            ["bad.example", "news.example.org", "timeout.example"]
                        )
                    )
                }
            )

        async def fetch(self, request):
            self.fetched.append(request.url.host)
            if all_rate_limited or request.url.host == "bad.example":
                raise source_error("rate", request.url.host)
            if request.url.host == "timeout.example":
                raise source_error("timeout")
            return await super().fetch(request)

        async def generate(self, request):
            result = await super().generate(request)
            if request.response_model.__name__ == "ResearchProposal":
                query = result.output.queries[0].model_copy(update={"max_results": 3})
                result = result.model_copy(
                    update={"output": result.output.model_copy(update={"queries": (query,)})}
                )
            return result

    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    settings = _settings(tmp_path).model_copy(
        update={
            "research_workers": 1,
            "max_search_concurrency": concurrency,
            "max_fetch_concurrency": concurrency,
        }
    )
    ports = MixedPorts()
    with TestClient(
        create_app(settings=settings, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = client.post(f"/api/investigations/{_create(client)}/runs").json()["run_id"]
        _drain(client)
        overview = client.get(f"/api/runs/{run_id}").json()
        run = overview["run"]
        assert set(ports.fetched) == {"bad.example", "news.example.org", "timeout.example"}
        assert run["status"] == "COMPLETED", run
        assert run["current_phase"] == "REPORT"
        assert "RateLimitedError" not in (run["interruption_reason"] or "")
        assert overview["budget"]["sources_used"] == 3
        assert overview["budget"]["fetch_calls_used"] == 3
        assert overview["budget"]["tokens_used"] < settings.max_tokens * 0.73
        gaps = client.get(f"/api/runs/{run_id}/gaps").json()
        failed = [g for g in gaps if g["source_id"]]
        assert len(failed) == (3 if all_rate_limited else 2)
        assert all(g["gap_type"] == "UNREADABLE_SOURCE" for g in failed)
        assert "PRIVATE" not in json.dumps(failed)
        sources = client.get(f"/api/runs/{run_id}/sources").json()
        assert len(sources) == (0 if all_rate_limited else 1)
        evidence = client.get(f"/api/runs/{run_id}/evidence").json()
        assert bool(evidence) == (not all_rate_limited)
        assert ("VerificationProposal" in ports.contracts) == (not all_rate_limited)
        if all_rate_limited:
            assert "合格来源" in run["interruption_reason"]
            assert "稍后重试" in run["interruption_reason"]
            recovery = client.get(f"/api/runs/{run_id}/recovery").json()
            # Task J has already persisted the restricted report and completed
            # this run. A new run can retry acquisition; this one is not pending.
            assert not recovery["can_resume"], recovery
            assert not recovery["unknown_calls"]
        with client.app.state.inv_sessions() as session:
            steps = session.scalars(
                select(ExecutionStepRow).where(ExecutionStepRow.run_id == run_id)
            ).all()
            assert not any(step.status.value == "FAILED" for step in steps)
            assert any(
                step.step_type.value == "RESEARCH" and step.status.value == "COMPLETED"
                for step in steps
            )
        reports = client.get(f"/api/runs/{run_id}/reports").json()
        assert len(reports) == 1 and reports[0]["report_type"] == "INVESTIGATION_STATUS"
