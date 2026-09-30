from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from marketpulse.investigation.domain.enums import RunMode, StepType
from marketpulse.investigation.harness.persistence import HarnessStore
from marketpulse.investigation.live_runtime import LivePorts
from marketpulse.investigation.persistence.models import (
    AuditEventRow,
    InvestigationRunRow,
)
from marketpulse.investigation.server import create_app
from tests.integration.investigation.test_live_runtime import (
    OutagePorts,
    _create,
    _drain,
    _settings,
)


def start(client: TestClient) -> str:
    return str(client.post(f"/api/investigations/{_create(client)}/runs").json()["run_id"])


def resume(client: TestClient, run_id: str, **updates: Any) -> Any:
    info = client.get(f"/api/runs/{run_id}/recovery").json()
    assert info["can_resume"], info
    body = {"expected_state_version": info["state_version"], **updates}
    return client.post(f"/api/runs/{run_id}/resume", json=body)


@pytest.mark.parametrize(
    "phase", [StepType.PLANNING, StepType.RESEARCH, StepType.ANALYSIS, StepType.VALIDATION]
)
def test_saved_response_reused_after_step_commit_failure_and_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: StepType,
) -> None:
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts()
    original = HarnessStore.complete_step
    crashed = False

    def crash(self: HarnessStore, **kwargs: Any) -> Any:
        nonlocal crashed
        from marketpulse.investigation.domain.runtime import ExecutionStep

        step = self.repository.get(ExecutionStep, kwargs["step_id"])
        if step.step_type is phase and not crashed:
            crashed = True
            raise ConnectionError("simulate response saved before step commit")
        return original(self, **kwargs)

    monkeypatch.setattr(HarnessStore, "complete_step", crash)
    settings = _settings(tmp_path)
    with TestClient(
        create_app(settings=settings, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        _drain(client)
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "FAILED"
        info = client.get(f"/api/runs/{run_id}/recovery").json()
        assert info["can_resume"], info
        assert info["unknown_calls"] == []
        used_before = info["budget"]["model_calls_used"]
    with TestClient(
        create_app(settings=settings, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        assert resume(client, run_id).status_code == 202
        _drain(client)
        run = client.get(f"/api/runs/{run_id}").json()
        assert run["run"]["status"] == "BLOCKED", run
        assert run["budget"]["model_calls_used"] >= used_before
        assert ports.contracts.count("PlanProposal") == 1
        assert ports.contracts.count("AnalysisProposal") == 1
        # Team worker calls may repeat contract names, but must never repeat saved calls.
        with client.app.state.inv_sessions() as session:
            intents = session.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.run_id == run_id,
                    AuditEventRow.event_type == "MODEL_CALL_INTENT",
                )
            ).all()
            assert all(e.metadata_payload["sequence"] == 1 for e in intents)
        assert (
            len(client.get(f"/api/investigations/{run['run']['investigation_id']}/runs").json())
            == 1
        )


def test_unknown_consent_is_per_intent_and_stale_topups_never_repeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(fail=True)
    with TestClient(
        create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        _drain(client)
        info = client.get(f"/api/runs/{run_id}/recovery").json()
        assert info["can_resume"], info
        assert len(info["unknown_calls"]) == 1
        body = {
            "expected_state_version": info["state_version"],
            "budget_increase": {"model_calls": 3},
        }
        denied = client.post(f"/api/runs/{run_id}/resume", json=body)
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "UNKNOWN_CALL_CONSENT_REQUIRED"
        body["retry_unknown_intent_ids"] = [c["intent_id"] for c in info["unknown_calls"]]
        assert client.post(f"/api/runs/{run_id}/resume", json=body).status_code == 202
        _drain(client)
        new = client.get(f"/api/runs/{run_id}/recovery").json()
        assert len(new["unknown_calls"]) == 1
        assert new["unknown_calls"] != info["unknown_calls"]
        assert new["budget"]["model_calls_used"] == info["budget"]["model_calls_used"] + 1
        assert new["budget"]["max_model_calls"] == info["budget"]["max_model_calls"] + 3
        assert client.post(f"/api/runs/{run_id}/resume", json=body).status_code == 409
        assert client.get(f"/api/runs/{run_id}/recovery").json()["budget"] == new["budget"]
        ports.fail = False
        assert (
            resume(
                client,
                run_id,
                retry_unknown_intent_ids=[c["intent_id"] for c in new["unknown_calls"]],
            ).status_code
            == 202
        )
        _drain(client)
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "BLOCKED"


@pytest.mark.parametrize("corruption", ["workflow", "schema", "blob", "profile", "replay"])
def test_incompatible_recovery_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(fail=True)
    with TestClient(
        create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        _drain(client)
        info = client.get(f"/api/runs/{run_id}/recovery").json()
        with client.app.state.inv_sessions.begin() as session:
            run = session.get(InvestigationRunRow, run_id)
            assert run
            if corruption == "workflow":
                run.workflow_version = "evidence-retrieval-v3"
            elif corruption == "replay":
                run.mode = RunMode.REPLAY
        if corruption == "schema":
            monkeypatch.setattr(
                "marketpulse.investigation.harness.checkpoints._digest", lambda _: "changed"
            )
        elif corruption == "blob":

            def corrupt_blob(*args: Any) -> bytes:
                raise OSError("simulated missing checkpoint blob")

            monkeypatch.setattr(
                client.app.state.live_investigation.blobs, "get_bytes", corrupt_blob
            )
        elif corruption == "profile":
            client.app.state.live_investigation.recovery.profile = "changed"
        assert not client.get(f"/api/runs/{run_id}/recovery").json()["can_resume"]
        response = client.post(
            f"/api/runs/{run_id}/resume", json={"expected_state_version": info["state_version"]}
        )
        assert response.status_code == 409
        assert ports.contracts == []


def test_exhausted_budget_requires_topup_and_keeps_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts()
    settings = _settings(tmp_path).model_copy(update={"max_model_calls": 1})
    with TestClient(
        create_app(settings=settings, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        _drain(client)
        info = client.get(f"/api/runs/{run_id}/recovery").json()
        assert info["can_resume"], info
        assert info["budget"]["model_calls_used"] == 1
        denied = resume(client, run_id)
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "BUDGET_INCREASE_REQUIRED"
        assert resume(client, run_id, budget_increase={"model_calls": 30}).status_code == 202
        _drain(client)
        detail = client.get(f"/api/runs/{run_id}").json()
        assert detail["budget"]["max_model_calls"] == 31
        assert detail["budget"]["model_calls_used"] > 1
        assert ports.contracts.count("PlanProposal") == 1
        assert "AnalysisProposal" in ports.contracts
        assert detail["run"]["status"] == "BLOCKED", detail


def test_resume_payload_rejects_negative_and_fractional_limits(tmp_path: Path) -> None:
    with TestClient(create_app(settings=_settings(tmp_path))) as client:
        for value in (-1, 1.5, True, "3"):
            assert (
                client.post(
                    "/api/runs/missing/resume",
                    json={
                        "expected_state_version": 0,
                        "budget_increase": {"model_calls": value},
                    },
                ).status_code
                == 422
            )


def test_cancelled_call_requires_consent_after_server_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))

    class WaitingPorts(OutagePorts):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.wait = True

        async def generate(self, request: Any) -> Any:
            self.entered.set()
            return await super().generate(request)

    ports = WaitingPorts()
    settings = _settings(tmp_path)
    with TestClient(
        create_app(settings=settings, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        assert client.portal
        client.portal.call(ports.entered.wait)
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200
        first = client.get(f"/api/runs/{run_id}/recovery").json()
        assert first["can_resume"]
        assert len(first["unknown_calls"]) == 1
    ports.wait = False
    with TestClient(
        create_app(settings=settings, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        assert resume(client, run_id).status_code == 409
        result = resume(
            client, run_id, retry_unknown_intent_ids=[first["unknown_calls"][0]["intent_id"]]
        )
        assert result.status_code == 202
        _drain(client)
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "BLOCKED"


def test_round_exhaustion_requires_explicit_round_increase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts()
    with TestClient(
        create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        _drain(client)
        info = client.get(f"/api/runs/{run_id}/recovery").json()
        assert info["can_resume"], info
        response = resume(client, run_id)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "BUDGET_INCREASE_REQUIRED"
        assert "轮次" in response.json()["detail"]["message"]


def test_report_resume_retains_terminal_outcome_without_model_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from marketpulse.investigation.domain.enums import ReportType
    from marketpulse.investigation.feedback.models import FeedbackLoopResult
    from marketpulse.investigation.feedback.orchestrator import AgentFeedbackOrchestrator
    from marketpulse.investigation.live_runtime import LiveInvestigationService

    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts()
    original_report = LiveInvestigationService._report
    # Make a non-budget stop (still reportable), then interrupt report generation.
    original_run = AgentFeedbackOrchestrator.run

    async def stop_before_plan(self: Any, run_id: str) -> FeedbackLoopResult:
        state = self.store.state(run_id)
        if state.run.current_phase.value == "CREATED":
            await self._bootstrap(state)
            return await self._blocked(run_id, [], [], "NO_ACTIONABLE_RESEARCH_TASK")
        return await original_run(self, run_id)

    async def interrupted_report(self: Any, run_id: str, report_type: ReportType) -> None:
        raise ConnectionError("report interrupted")

    monkeypatch.setattr(AgentFeedbackOrchestrator, "run", stop_before_plan)
    monkeypatch.setattr(LiveInvestigationService, "_report", interrupted_report)
    with TestClient(
        create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        _drain(client)
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "FAILED"
        from marketpulse.investigation.persistence.models import RunBudgetRow

        with client.app.state.inv_sessions.begin() as session:
            budget = session.get(RunBudgetRow, run_id)
            budget.consumed_wall_time_ms = budget.max_wall_time_ms
            budget.model_calls_used = budget.max_model_calls
        monkeypatch.setattr(LiveInvestigationService, "_report", original_report)
        assert resume(client, run_id).status_code == 202
        _drain(client)
        assert ports.contracts == []
        reports = client.get(f"/api/runs/{run_id}/reports").json()
        assert len(reports) == 1
        assert reports[0]["report_type"] == "INVESTIGATION_STATUS"
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "BLOCKED"


def test_no_progress_history_survives_failure_before_stop_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from marketpulse.investigation.feedback.information_gain import InformationGainCalculator
    from marketpulse.investigation.feedback.models import InformationGainSummary
    from marketpulse.investigation.feedback.orchestrator import AgentFeedbackOrchestrator
    from marketpulse.investigation.recovery import live_feedback_config

    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))

    def config(settings: Any) -> Any:
        return live_feedback_config(settings).model_copy(update={"no_progress_rounds": 1})

    monkeypatch.setattr("marketpulse.investigation.live_runtime.live_feedback_config", config)
    monkeypatch.setattr("marketpulse.investigation.recovery.live_feedback_config", config)

    def no_gain(*args: Any, round_number: int) -> InformationGainSummary:
        return InformationGainSummary(
            round=round_number,
            new_valid_sources=0,
            new_independent_families=0,
            new_evidence=0,
            new_claims=0,
            resolved_gaps=0,
            new_gaps=0,
            resolved_conflicts=0,
        )

    monkeypatch.setattr(InformationGainCalculator, "compare", no_gain)
    original = AgentFeedbackOrchestrator._blocked
    crashed = False

    async def crash(
        self: Any, run_id: str, trace: Any, gains: Any, reason: str, **kwargs: Any
    ) -> Any:
        nonlocal crashed
        if reason == "NO_INFORMATION_GAIN" and not crashed:
            crashed = True
            raise ConnectionError("stop transition interrupted")
        return await original(self, run_id, trace, gains, reason, **kwargs)

    monkeypatch.setattr(AgentFeedbackOrchestrator, "_blocked", crash)
    ports = OutagePorts()
    settings = _settings(tmp_path).model_copy(update={"max_research_rounds": 3})
    with TestClient(
        create_app(settings=settings, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        _drain(client)
        assert crashed
        before = list(ports.contracts)
        assert resume(client, run_id).status_code == 202
        _drain(client)
        detail = client.get(f"/api/runs/{run_id}").json()
        assert detail["run"]["status"] == "BLOCKED", detail
        assert "NO_INFORMATION_GAIN" in detail["run"]["interruption_reason"]
        assert ports.contracts == before
