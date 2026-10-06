"""Offline fault injection for automatic recovery, ownership and alert policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from marketpulse.investigation.domain.enums import StepType
from marketpulse.investigation.domain.runtime import ExecutionStep
from marketpulse.investigation.harness.persistence import HarnessStore
from marketpulse.investigation.live_runtime import LivePorts
from marketpulse.investigation.operations.ownership import ServerAlreadyRunning
from marketpulse.investigation.persistence.models import AuditEventRow, InvestigationRunRow
from marketpulse.investigation.server import create_app
from tests.integration.investigation.test_live_runtime import (
    OutagePorts,
    _create,
    _drain,
    _settings,
)

pytestmark = pytest.mark.usefixtures("unfinished_legacy_runs")


def settings(tmp_path: Path) -> Any:
    return _settings(tmp_path).model_copy(
        update={"recovery_scan_seconds": 300, "auto_resume_backoff_seconds": 0}
    )


def tick(client: TestClient) -> None:
    assert client.portal
    client.portal.call(client.app.state.recovery_watchdog.tick)


def start(client: TestClient) -> str:
    return str(client.post(f"/api/investigations/{_create(client)}/runs").json()["run_id"])


def test_automatic_restart_reuses_saved_response_without_manual_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts()
    complete = HarnessStore.complete_step
    crashed = False

    def crash(self: HarnessStore, **kwargs: Any) -> Any:
        nonlocal crashed
        step = self.repository.get(ExecutionStep, kwargs["step_id"])
        if step.step_type is StepType.PLANNING and not crashed:
            crashed = True
            raise ConnectionError("crash after response saved")
        return complete(self, **kwargs)

    monkeypatch.setattr(HarnessStore, "complete_step", crash)
    with TestClient(
        create_app(settings=settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        _drain(client)
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "FAILED"
    # A restarted server scans without a POST /resume or any human authorization.
    with TestClient(
        create_app(settings=settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        tick(client)
        _drain(client)
        assert ports.contracts.count("PlanProposal") == 1
        assert "VerificationProposal" in ports.contracts
        with client.app.state.inv_sessions() as session:
            event = session.scalar(
                select(AuditEventRow).where(AuditEventRow.event_type == "RUN_RESUMED")
            )
            assert event and event.actor_type.value == "SYSTEM"
            assert event.metadata_payload["automatic"] is True
            assert not any(event.metadata_payload["budget_increase"].values())


def test_unknown_outcome_is_never_retried_and_alert_survives_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(fail=True)
    for iteration in range(2):
        with TestClient(
            create_app(settings=settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
        ) as client:
            if iteration == 0:
                run_id = start(client)
                _drain(client)
            tick(client)
            tick(client)
            detail = client.get(f"/api/runs/{run_id}").json()
            assert detail["budget"]["model_calls_used"] == 1
            alerts = client.get("/api/ops/status").json()["alerts"]
            assert len(alerts) == 1
            assert alerts[0]["code"] == "UNKNOWN_CALL_CONSENT_REQUIRED"
            assert "secret" not in str(alerts)
            with client.app.state.inv_sessions() as session:
                assert (
                    len(
                        session.scalars(
                            select(AuditEventRow).where(AuditEventRow.event_type == "OPS_ALERT")
                        ).all()
                    )
                    == 1
                )


def test_cancelled_and_budget_blocked_runs_are_not_auto_resumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(wait=True)
    with TestClient(
        create_app(settings=settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200
        tick(client)
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "CANCELLED"
    ports.wait = False
    with TestClient(
        create_app(
            settings=settings(tmp_path).model_copy(update={"max_model_calls": 1}),
            live_ports=LivePorts(ports, ports, ports),
        )
    ) as client:
        budget_id = start(client)
        _drain(client)
        tick(client)
        result = client.get(f"/api/runs/{budget_id}").json()
        assert result["run"]["status"] == "BLOCKED"
        assert result["budget"]["max_model_calls"] == 1
        # One call cannot cover both collection and protected later stages:
        # fail admission before paying the provider, rather than charge a fake call.
        assert result["budget"]["model_calls_used"] == 0
        assert "BUDGET_EXHAUSTED" in result["run"]["interruption_reason"]
        assert client.get("/api/ops/status").json()["alerts"][0]["code"] == "RUN_BLOCKED"


def test_user_cancel_keeps_step_checkpoint_and_survives_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from marketpulse.investigation.domain.enums import ExecutionStepStatus, RunStatus
    from marketpulse.investigation.persistence.models import ExecutionStepRow

    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))

    class Waiting(OutagePorts):
        def __init__(self) -> None:
            super().__init__(wait=True)
            self.entered = asyncio.Event()

        async def generate(self, request: Any) -> Any:
            self.entered.set()
            return await super().generate(request)

    ports = Waiting()
    fail_step = HarnessStore.fail_step
    saw_stop_intent = False
    cancelled_step_id = ""

    def checkpoint(self: HarnessStore, **kwargs: Any) -> None:
        nonlocal saw_stop_intent, cancelled_step_id
        cancelled_step_id = kwargs["step_id"]
        with self.sessions() as session:
            step = session.get(ExecutionStepRow, kwargs["step_id"])
            run = session.get(InvestigationRunRow, step.run_id)
            assert run.status is RunStatus.CANCELLED
            assert run.interruption_reason == "USER_CANCELLED"
            assert run.owner_instance_id == kwargs["owner_instance_id"]
            saw_stop_intent = True
        fail_step(self, **kwargs)

    monkeypatch.setattr(HarnessStore, "fail_step", checkpoint)
    config = settings(tmp_path)
    with TestClient(
        create_app(settings=config, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        assert client.portal
        client.portal.call(ports.entered.wait)
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200
        assert saw_stop_intent
        with client.app.state.inv_sessions() as session:
            step = session.get(ExecutionStepRow, cancelled_step_id)
            assert step.status is ExecutionStepStatus.INTERRUPTED
            assert step.completed_at is not None
    with TestClient(
        create_app(settings=config, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        tick(client)
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "CANCELLED"
        assert not client.app.state.live_investigation.tasks


def test_retry_limit_is_durable_across_server_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts()
    complete = HarnessStore.complete_step

    def crash(self: HarnessStore, **kwargs: Any) -> Any:
        if self.repository.get(ExecutionStep, kwargs["step_id"]).step_type is StepType.PLANNING:
            raise ConnectionError("repeat commit failure")
        return complete(self, **kwargs)

    monkeypatch.setattr(HarnessStore, "complete_step", crash)
    config = settings(tmp_path).model_copy(update={"auto_resume_max_attempts": 1})
    with TestClient(
        create_app(settings=config, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        _drain(client)
        tick(client)
        _drain(client)
    with TestClient(
        create_app(settings=config, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        tick(client)
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "FAILED"
        assert client.get("/api/ops/status").json()["alerts"][0]["code"] == "AUTO_RESUME_LIMIT"
        assert ports.contracts == ["PlanProposal"]


def test_second_api_instance_cannot_mark_first_run_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(wait=True)
    config = settings(tmp_path)
    with TestClient(
        create_app(settings=config, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        with pytest.raises(ServerAlreadyRunning):
            with TestClient(create_app(settings=config)):
                pytest.fail("must not serve")
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] not in {
            "INTERRUPTED",
            "FAILED",
        }
    with TestClient(create_app(settings=config)) as restarted:
        assert restarted.get("/api/health").status_code == 200


def test_watchdog_task_failure_changes_readiness(tmp_path: Path) -> None:
    with TestClient(create_app(settings=settings(tmp_path))) as client:
        assert client.portal
        client.portal.call(client.app.state.recovery_watchdog.close)
        assert client.get("/api/health").status_code == 503
        assert client.get("/api/ops/status").json()["healthy"] is False


def test_watchdog_does_not_interrupt_offline_recording_with_historical_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from marketpulse.investigation.domain.enums import RunStatus

    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(wait=True)
    with TestClient(
        create_app(settings=settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200
        with client.app.state.inv_sessions.begin() as session:
            row = session.get(InvestigationRunRow, run_id)
            row.workflow_version = "curated-offline-v2"
            row.status = RunStatus.RUNNING
            row.owner_instance_id = "offline-recorder"
            row.owner_heartbeat_at = datetime(2023, 2, 3, tzinfo=UTC)
        tick(client)
        with client.app.state.inv_sessions() as session:
            row = session.get(InvestigationRunRow, run_id)
            assert row.status is RunStatus.RUNNING
            assert row.owner_instance_id == "offline-recorder"
            assert not session.scalars(
                select(AuditEventRow).where(AuditEventRow.event_type == "OPS_ALERT")
            ).all()


def test_stalled_task_is_stopped_before_recovery_and_unknown_call_alerted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from datetime import UTC, datetime, timedelta

    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))

    class Waiting(OutagePorts):
        def __init__(self) -> None:
            super().__init__(wait=True)
            self.entered = asyncio.Event()

        async def generate(self, request: Any) -> Any:
            self.entered.set()
            return await super().generate(request)

    ports = Waiting()
    with TestClient(
        create_app(settings=settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        assert client.portal
        client.portal.call(ports.entered.wait)

        async def stall() -> None:
            with client.app.state.inv_sessions.begin() as session:
                row = session.get(InvestigationRunRow, run_id)
                row.owner_heartbeat_at = datetime.now(UTC) - timedelta(seconds=120)
            await client.app.state.recovery_watchdog.tick()

        client.portal.call(stall)
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "INTERRUPTED"
        assert not client.app.state.live_investigation.tasks
        tick(client)
        alerts = client.get("/api/ops/status").json()["alerts"]
        assert any(a["code"] == "UNKNOWN_CALL_CONSENT_REQUIRED" for a in alerts)
        assert client.get(f"/api/runs/{run_id}").json()["budget"]["model_calls_used"] == 1


def test_automatic_policy_rejects_consent_topups_and_respects_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from marketpulse.investigation.recovery import BudgetIncrease, RecoveryConflict, ResumeRequest

    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(fail=True)
    with TestClient(
        create_app(settings=settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        _drain(client)
        recovery = client.app.state.live_investigation.recovery
        info = recovery.inspect(run_id)
        for request in [
            ResumeRequest(
                expected_state_version=info["state_version"], retry_unknown_intent_ids=["untrusted"]
            ),
            ResumeRequest(
                expected_state_version=info["state_version"],
                budget_increase=BudgetIncrease(model_calls=1),
            ),
        ]:
            with pytest.raises(RecoveryConflict) as error:
                recovery.prepare(run_id, request, automatic=True, backoff_seconds=0)
            assert error.value.code == "AUTO_RESUME_UNSAFE"
        with pytest.raises(RecoveryConflict) as error:
            recovery.prepare(
                run_id,
                ResumeRequest(expected_state_version=info["state_version"]),
                automatic=True,
                backoff_seconds=3600,
            )
        assert error.value.code == "AUTO_RESUME_BACKOFF"


def test_watchdog_loop_automatically_scans_without_manual_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(fail=True)
    config = settings(tmp_path).model_copy(update={"recovery_scan_seconds": 0.1})
    with TestClient(
        create_app(settings=config, live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        _drain(client)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            alerts = client.get("/api/ops/status").json()["alerts"]
            if alerts:
                break
            time.sleep(0.05)
        assert alerts[0]["run_id"] == run_id
        assert alerts[0]["code"] == "UNKNOWN_CALL_CONSENT_REQUIRED"


def test_restored_archive_quarantine_blocks_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blobs = tmp_path / "blobs"
    blobs.mkdir()
    (blobs / ".restore-quarantine.json").write_text("{}")
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(blobs))
    ports = OutagePorts(fail=True)
    with TestClient(
        create_app(settings=settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = start(client)
        _drain(client)
        tick(client)
        recovery = client.get(f"/api/runs/{run_id}/recovery").json()
        assert not recovery["can_resume"]
        assert "历史备份" in recovery["reason"]
        assert client.get(f"/api/runs/{run_id}").json()["budget"]["model_calls_used"] == 1
