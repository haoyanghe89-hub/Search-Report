from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch

from marketpulse.config import Settings
from marketpulse.investigation.live_runtime import LivePorts
from marketpulse.investigation.ports.external import (
    FetchRequest,
    FetchResult,
    ModelRequest,
    SearchRequest,
    SearchResult,
    SearchResultItem,
    StructuredModelResult,
)
from marketpulse.investigation.server import create_app


class OutagePorts:
    """A different event through real orchestration with only external I/O replaced."""

    def __init__(self, *, fail: bool = False, wait: bool = False) -> None:
        self.queries: list[str] = []
        self.contracts: list[str] = []
        self.fail = fail
        self.wait = wait

    async def search(self, request: SearchRequest) -> SearchResult:
        self.queries.append(request.query)
        return SearchResult(
            items=(
                SearchResultItem.model_validate(
                    {
                        "title": "CrowdStrike outage independent account",
                        "url": "https://news.example.org/crowdstrike",
                        "snippet": "A software update caused Windows hosts to crash.",
                        "rank": 1,
                        "source_type_hint": "news",
                        "publisher": "Independent test newsroom",
                    }
                ),
            ),
            provider="offline-test-search",
            retrieved_at=datetime.now(UTC),
        )

    async def fetch(self, request: FetchRequest) -> FetchResult:
        return FetchResult(
            final_url=request.url,
            status_code=200,
            content_type="text/plain",
            body=(
                b"On July 19, 2024, a CrowdStrike software update caused Windows hosts to crash. "
                b"This independent account describes the outage and does not establish the "
                b"number of affected hosts or the final cause of the defective update."
            ),
            fetched_at=datetime.now(UTC),
        )

    async def generate(self, request: ModelRequest[Any]) -> StructuredModelResult[Any]:
        if self.wait:
            await asyncio.Event().wait()
        if self.fail:
            raise RuntimeError("secret response body must not be exposed")
        name = request.response_model.__name__
        self.contracts.append(name)
        context = json.loads(request.messages[1].content)["bounded_context"]
        if name == "PlanProposal":
            assert "CrowdStrike" in context["event_description"]
            payload = {
                "tasks": [
                    {
                        "task_key": f"outage-facts-{index}",
                        "target_question_key": question["question_key"],
                        "objective": "Find CrowdStrike outage accounts",
                        "priority": 90,
                    }
                    for index, question in enumerate(context["questions"])
                ]
            }
        elif name == "ResearchProposal":
            payload = {
                "queries": [
                    {
                        "query_key": "outage-search",
                        "query": "CrowdStrike July 19 2024 outage",
                        "target_question_key": context["task"]["target_question_key"],
                        "purpose": "Find outage evidence",
                        "max_results": 1,
                    }
                ]
            }
        elif name == "AnalysisProposal":
            artifact = context["artifacts"][0]
            payload = {
                "evidence": [
                    {
                        "evidence_key": "outage-excerpt",
                        "artifact_key": artifact["artifact_key"],
                        "quote": artifact["excerpt"],
                        "locator": artifact["locator"],
                        "quote_hash": artifact["locator"]["quote_hash"],
                    }
                ],
                "claims": [
                    {
                        "claim_key": "outage",
                        "statement": "A CrowdStrike update caused Windows hosts to crash.",
                        "claim_type": "EVENT_FACT",
                        "importance": "HIGH",
                        "critical": True,
                        "supporting_evidence_keys": ["outage-excerpt"],
                        "atomicity": {"is_atomic": True},
                    }
                ],
            }
        elif name == "VerificationProposal":
            payload = {
                "judgments": [
                    {
                        "claim_key": context["claims"][0]["claim_key"],
                        "evidence_key": context["evidence"][0]["evidence_key"],
                        "entailment": "ENTAILS",
                        "rationale": "The text states the outage occurred.",
                        "semantic_confidence": 0.9,
                    }
                ]
            }
        else:
            raise AssertionError(name)
        return StructuredModelResult(
            output=request.response_model.model_validate(payload),
            provider="offline-test-model",
            model="structured-test",
        )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=SecretStr(f"sqlite:///{(tmp_path / 'live.db').as_posix()}"),
        max_research_rounds=1,
        model_auto_retry=False,  # Existing manual-consent/recovery contract tests.
    )


def test_transient_verifier_failure_exhausts_to_blocked_preserves_sources(tmp_path, monkeypatch):
    class TimeoutPorts(OutagePorts):
        verify_attempts = 0

        async def generate(self, request):
            if request.response_model.__name__ == "VerificationProposal":
                self.verify_attempts += 1
                raise TimeoutError("transport timeout")
            return await super().generate(request)

    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = TimeoutPorts()
    settings = _settings(tmp_path).model_copy(
        update={
            "model_auto_retry": True,
            "model_retry_attempts": 2,
            "model_retry_backoff_seconds": 0,
        }
    )
    with TestClient(
        create_app(settings=settings, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        investigation_id = _create(client)
        run_id = client.post(f"/api/investigations/{investigation_id}/runs").json()["run_id"]
        _drain(client)
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        assert run["status"] == "COMPLETED"
        assert "MODEL_RETRY_EXHAUSTED" in run["interruption_reason"]
        assert ports.verify_attempts == 3
        assert len(client.get(f"/api/runs/{run_id}/sources").json()) == 1


def _create(client: TestClient) -> str:
    response = client.post(
        "/api/investigations",
        json={
            "title": "CrowdStrike outage",
            "event_description": "CrowdStrike July 2024 outage",
            "investigation_goal": "Establish the outage facts",
            "questions": ["What happened?"],
        },
    )
    assert response.status_code == 201
    return str(response.json()["investigation_id"])


def _drain(client: TestClient) -> None:
    async def wait() -> None:
        await asyncio.gather(*tuple(client.app.state.live_investigation.tasks.values()))

    assert client.portal is not None
    client.portal.call(wait)


def test_live_missing_credentials_returns_actionable_error_without_seeding(tmp_path: Path) -> None:
    with TestClient(create_app(settings=_settings(tmp_path))) as client:
        investigation_id = _create(client)
        response = client.post(f"/api/investigations/{investigation_id}/runs")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "LIVE_NOT_CONFIGURED"
        assert "DEEPSEEK_API_KEY" in response.json()["detail"]["message"]
        assert client.get(f"/api/investigations/{investigation_id}/runs").json() == []


def test_unrelated_event_uses_live_ports_and_reports_insufficient_evidence(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from marketpulse.investigation.case_replay import EastPalestineReplayService

    async def forbidden_replay(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a new event must never invoke East Palestine replay")

    monkeypatch.setattr(EastPalestineReplayService, "run_for_investigation", forbidden_replay)
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts()
    app = create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    with TestClient(app) as client:
        investigation_id = _create(client)
        response = client.post(f"/api/investigations/{investigation_id}/runs")
        assert response.status_code == 202
        assert response.json()["status"] == "CREATED"
        run_id = response.json()["run_id"]
        _drain(client)
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        assert run["mode"] == "LIVE"
        assert run["origin_run_id"] is None
        assert run["status"] == "COMPLETED", run
        assert run["started_at"] is not None
        assert run["completed_at"] is not None
        assert ports.queries == ["CrowdStrike July 19 2024 outage"]
        assert set(ports.contracts) == {
            "PlanProposal",
            "ResearchProposal",
            "AnalysisProposal",
            "VerificationProposal",
        }
        claims = client.get(f"/api/runs/{run_id}/claims").json()
        assert len(claims) == 1
        assert "CrowdStrike" in claims[0]["statement"]
        assert claims[0]["validation_status"] != "VERIFIED"
        reports = client.get(f"/api/runs/{run_id}/reports").json()
        assert len(reports) == 1
        assert reports[0]["report_type"] == "INVESTIGATION_STATUS"


def test_live_failure_persists_sanitized_reason(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(fail=True)
    with TestClient(
        create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = client.post(f"/api/investigations/{_create(client)}/runs").json()["run_id"]
        _drain(client)
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        assert run["status"] == "COMPLETED"
        assert run["completed_at"] is not None
        assert "secret response body" not in run["interruption_reason"]
        reports = client.get(f"/api/runs/{run_id}/reports").json()
        assert reports[0]["report_type"] == "INVESTIGATION_STATUS"


def test_initial_invalid_proposal_has_actionable_failed_status_report(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from marketpulse.investigation.recording.errors import InvalidProviderResponseError

    class InvalidPlanPorts(OutagePorts):
        attempts = 0

        async def generate(self, request):
            self.attempts += 1
            raise InvalidProviderResponseError("PRIVATE_MODEL_OUTPUT_MUST_NOT_LEAK")

    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = InvalidPlanPorts()
    with TestClient(
        create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = client.post(f"/api/investigations/{_create(client)}/runs").json()["run_id"]
        _drain(client)
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        assert run["status"] == "COMPLETED"
        assert "未形成可确认结论" in run["interruption_reason"]
        assert "重新调查" in run["interruption_reason"]
        assert "PRIVATE_MODEL" not in run["interruption_reason"]
        assert ports.attempts == 3
        reports = client.get(f"/api/runs/{run_id}/reports").json()
        assert reports[0]["report_type"] == "INVESTIGATION_STATUS"


def test_cancel_and_shutdown_are_persisted(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(wait=True)
    app = create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    with TestClient(app) as client:
        investigation_id = _create(client)
        run_id = client.post(f"/api/investigations/{investigation_id}/runs").json()["run_id"]
        response = client.post(f"/api/runs/{run_id}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "COMPLETED"
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "COMPLETED"
        assert client.get(f"/api/runs/{run_id}/reports").json()
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 409
        shutdown_id = client.post(f"/api/investigations/{investigation_id}/runs").json()["run_id"]
    with TestClient(create_app(settings=_settings(tmp_path))) as client:
        run = client.get(f"/api/runs/{shutdown_id}").json()["run"]
        assert run["status"] == "COMPLETED"
        assert run["interruption_reason"].startswith("SERVER_SHUTDOWN")


def test_wall_timeout_persists_failure_and_status_report(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(wait=True)
    settings = _settings(tmp_path).model_copy(update={"total_timeout_seconds": 0.1})
    with TestClient(
        create_app(settings=settings, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = client.post(f"/api/investigations/{_create(client)}/runs").json()["run_id"]
        _drain(client)
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        assert run["status"] == "COMPLETED"
        assert run["interruption_reason"].startswith("RUN_TIMEOUT")
        reports = client.get(f"/api/runs/{run_id}/reports").json()
        assert reports[0]["report_type"] == "INVESTIGATION_STATUS"


def test_startup_marks_abandoned_live_run_interrupted(tmp_path: Path) -> None:
    from marketpulse.investigation.domain.enums import RunMode, RunStatus, WorkflowPhase
    from marketpulse.investigation.domain.runtime import InvestigationRun

    app = create_app(settings=_settings(tmp_path))
    with TestClient(app) as client:
        investigation_id = _create(client)
        now = datetime.now(UTC)
        app.state.inv_repository.add(
            InvestigationRun(
                run_id="RUN-ABANDONED",
                investigation_id=investigation_id,
                mode=RunMode.LIVE,
                status=RunStatus.RUNNING,
                current_phase=WorkflowPhase.PLAN,
                checkpoint_version=0,
                state_version=0,
                workflow_version="agent-feedback-v1",
                created_at=now,
                updated_at=now,
            )
        )
    with TestClient(create_app(settings=_settings(tmp_path))) as client:
        _drain(client)
        run = client.get("/api/runs/RUN-ABANDONED").json()["run"]
        assert run["status"] == "COMPLETED"
        assert client.get("/api/runs/RUN-ABANDONED/reports").json()
        assert run["interruption_reason"].startswith("SERVER_RESTARTED")


def test_default_questions_support_new_event_live_planning(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts()
    with TestClient(
        create_app(
            settings=_settings(tmp_path).model_copy(update={"max_search_queries": 1}),
            live_ports=LivePorts(ports, ports, ports),
        )
    ) as client:
        created = client.post(
            "/api/investigations",
            json={
                "title": "CrowdStrike outage",
                "event_description": "CrowdStrike July 2024 outage",
                "investigation_goal": "Establish the outage facts",
            },
        )
        assert created.status_code == 201
        investigation = created.json()
        assert len(investigation["questions"]) == 8
        assert any(question["is_critical"] for question in investigation["questions"])
        run_id = client.post(
            f"/api/investigations/{investigation['investigation_id']}/runs",
        ).json()["run_id"]
        _drain(client)
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        assert run["status"] == "COMPLETED", run
        assert ports.queries == ["CrowdStrike July 19 2024 outage"]
        assert "VerificationProposal" in ports.contracts
