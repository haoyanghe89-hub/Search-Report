from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from marketpulse.config import Settings
from marketpulse.investigation.depth import PRESETS, depth_settings
from marketpulse.investigation.domain.enums import WorkflowPhase
from marketpulse.investigation.live_runtime import LiveInvestigationService, LivePorts
from marketpulse.investigation.persistence.models import InvestigationRunRow, ReportRow
from marketpulse.investigation.recording.errors import ProviderCallError
from marketpulse.investigation.server import create_app
from tests.integration.investigation.test_live_runtime import (
    OutagePorts,
    _create,
    _drain,
    _settings,
)


@pytest.mark.parametrize("depth", ["quick", "standard", "deep"])
def test_depth_default_and_operator_ceiling(depth):
    preset = depth_settings(Settings(), depth)
    assert preset.total_timeout_seconds == PRESETS[depth]["total_timeout_seconds"]
    assert preset.max_research_rounds == PRESETS[depth]["max_research_rounds"]
    assert preset.verify_token_reserve_fraction == Settings().verify_token_reserve_fraction
    capped = depth_settings(Settings(max_tokens=1000, max_pages=1), depth)
    assert capped.max_tokens == 1000 and capped.max_pages == 1


@pytest.mark.parametrize("phase", ["PLAN", "COLLECT", "ANALYZE", "VERIFY", "REPORT"])
@pytest.mark.parametrize("failure", ["unexpected", "timeout", "balance"])
def test_all_phases_finalize_without_external_report_call(tmp_path, monkeypatch, phase, failure):
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts()

    def orchestrator(self, run_id, *args):
        class Broken:
            async def run(inner, _):
                with self.sessions.begin() as session:
                    row = session.get(InvestigationRunRow, run_id)
                    row.current_phase = WorkflowPhase(phase)
                if failure == "balance":
                    raise ProviderCallError("private", diagnostics={"http_status": 402})
                if failure == "timeout":
                    raise TimeoutError("private")
                raise RuntimeError("private")

        return Broken()

    monkeypatch.setattr(LiveInvestigationService, "_orchestrator", orchestrator)
    with TestClient(
        create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = client.post(
            f"/api/investigations/{_create(client)}/runs", json={"depth": "quick"}
        ).json()["run_id"]
        _drain(client)
        detail = client.get(f"/api/runs/{run_id}").json()
        assert detail["run"]["status"] == "COMPLETED"
        assert detail["run"]["completed_at"]
        reports = client.get(f"/api/runs/{run_id}/reports").json()
        assert reports and reports[0]["release_status"] == "RESTRICTED"
        response = client.get(f"/api/reports/{reports[0]['report_id']}").json()
        assert "资料不足" in str(response) and "未能获取到" in str(response)
        assert "private" not in str(response)
        if failure == "balance":
            assert "余额不足" in str(response)
        assert ports.contracts == []


def test_create_depth_persists_and_start_can_override(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(fail=True)
    with TestClient(
        create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        created = client.post(
            "/api/investigations",
            json={
                "title": "T",
                "event_description": "T",
                "investigation_goal": "G",
                "depth": "quick",
            },
        )
        investigation_id = created.json()["investigation_id"]
        run_id = client.post(f"/api/investigations/{investigation_id}/runs").json()["run_id"]
        _drain(client)
        budget = client.get(f"/api/runs/{run_id}").json()["budget"]
        assert budget["max_wall_time_ms"] == 300000
        assert budget["max_sources"] == 16
        run_id = client.post(
            f"/api/investigations/{investigation_id}/runs", json={"depth": "deep"}
        ).json()["run_id"]
        _drain(client)
        assert client.get(f"/api/runs/{run_id}").json()["budget"]["max_wall_time_ms"] == 1800000
        assert (
            client.post(
                "/api/investigations",
                json={
                    "title": "T",
                    "event_description": "T",
                    "investigation_goal": "G",
                    "depth": "invalid",
                },
            ).status_code
            == 422
        )


def test_report_failures_retry_then_minimal_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    attempts = []

    async def broken(self, run_id, report_type):
        attempts.append(run_id)
        raise RuntimeError("report assembler unavailable")

    monkeypatch.setattr(LiveInvestigationService, "_report", broken)
    ports = OutagePorts(fail=True)
    with TestClient(
        create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = client.post(f"/api/investigations/{_create(client)}/runs").json()["run_id"]
        _drain(client)
        assert len(attempts) == 3
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "COMPLETED"
        assert len(client.get(f"/api/runs/{run_id}/reports").json()) == 1
        client.portal.call(client.app.state.live_investigation._finalize_run, run_id, "again")
        assert len(client.get(f"/api/runs/{run_id}/reports").json()) == 1


def test_delete_full_history_shared_blobs_and_idempotence(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts()
    with TestClient(
        create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        ids = [_create(client), _create(client)]
        runs = []
        for iid in ids:
            runs.append(client.post(f"/api/investigations/{iid}/runs").json()["run_id"])
            _drain(client)
        blobs = client.app.state.live_investigation.blobs
        blob_files = list((tmp_path / "blobs/sha256").rglob("*"))
        assert any(p.is_file() for p in blob_files)
        result = client.delete(f"/api/investigations/{ids[0]}")
        assert result.status_code == 200, result.text
        assert result.json()["deleted"]
        assert client.get(f"/api/investigations/{ids[0]}").status_code == 404
        assert client.get(f"/api/runs/{runs[0]}").status_code == 404
        # Shared source/artifact blobs must remain readable for the other archive.
        from marketpulse.infrastructure.storage.models import BlobRef
        from marketpulse.investigation.persistence.models import DocumentArtifactRow

        with client.app.state.inv_sessions() as session:
            artifacts = session.scalars(select(DocumentArtifactRow)).all()
            assert artifacts
            for artifact in artifacts:
                assert blobs.get_bytes(BlobRef.from_uri(artifact.blob_ref))
        assert client.delete(f"/api/investigations/{ids[0]}").json()["already_deleted"]
        assert client.delete(f"/api/investigations/{ids[1]}").status_code == 200
        assert not any(p.is_file() for p in (tmp_path / "blobs/sha256").rglob("*"))
        with client.app.state.inv_sessions() as session:
            assert session.scalar(select(ReportRow)) is None


def test_delete_running_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(wait=True)
    with TestClient(
        create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        iid = _create(client)
        run_id = client.post(f"/api/investigations/{iid}/runs").json()["run_id"]
        assert client.delete(f"/api/investigations/{iid}").status_code == 409
        assert client.get(f"/api/investigations/{iid}").status_code == 200
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200
        assert client.delete(f"/api/investigations/{iid}").status_code == 200


def test_report_persistence_failure_keeps_recoverable_checkpoint(tmp_path, monkeypatch):
    from marketpulse.investigation.reporting.pipeline import ReportPipeline

    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    original = ReportPipeline.minimal
    attempts = []

    async def broken_report(self, run_id, report_type):
        raise RuntimeError("assembler unavailable")

    async def broken_minimal(self, **kwargs):
        attempts.append(kwargs["run_id"])
        raise RuntimeError("database temporarily unavailable")

    monkeypatch.setattr(LiveInvestigationService, "_report", broken_report)
    monkeypatch.setattr(ReportPipeline, "minimal", broken_minimal)
    ports = OutagePorts(fail=True)
    with TestClient(
        create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = client.post(f"/api/investigations/{_create(client)}/runs").json()["run_id"]
        _drain(client)
        assert len(attempts) == 3
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        assert run["status"] == "BLOCKED" and run["completed_at"] is None
        assert "REPORT_FINALIZATION_PENDING" in run["interruption_reason"]
        assert not client.get(f"/api/runs/{run_id}/reports").json()
        model_calls = len(ports.contracts)
        monkeypatch.setattr(ReportPipeline, "minimal", original)
        client.portal.call(client.app.state.live_investigation.recover_interrupted)
        _drain(client)
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "COMPLETED"
        assert len(client.get(f"/api/runs/{run_id}/reports").json()) == 1
        assert len(ports.contracts) == model_calls


def test_deletion_permission_does_not_disable_append_only(tmp_path, monkeypatch):
    from sqlalchemy import delete, update
    from sqlalchemy.exc import IntegrityError

    from marketpulse.investigation.persistence.models import DeletionPermitRow

    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(fail=True)
    with TestClient(
        create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        iid = _create(client)
        run_id = client.post(f"/api/investigations/{iid}/runs").json()["run_id"]
        _drain(client)
        sessions = client.app.state.inv_sessions
        with pytest.raises(IntegrityError, match="append-only"), sessions.begin() as session:
            session.execute(delete(ReportRow).where(ReportRow.run_id == run_id))
        with pytest.raises(IntegrityError, match="append-only"), sessions.begin() as session:
            session.execute(update(ReportRow).where(ReportRow.run_id == run_id).values(version=2))
        with sessions() as session:
            assert session.scalar(select(DeletionPermitRow)) is None
        assert client.delete(f"/api/investigations/{iid}").status_code == 200
        with sessions() as session:
            assert session.scalar(select(DeletionPermitRow)) is None


@pytest.mark.parametrize("with_material", [False, True])
def test_emergency_report_does_not_depend_on_broken_writer(tmp_path, monkeypatch, with_material):
    from marketpulse.investigation.reporting.writer import DeterministicWriter

    async def broken(self, projection):
        raise TypeError("normal writer regression")

    monkeypatch.setattr(DeterministicWriter, "draft", broken)
    monkeypatch.setenv("INVESTIGATION_BLOB_ROOT", str(tmp_path / "blobs"))
    ports = OutagePorts(fail=not with_material)
    with TestClient(
        create_app(settings=_settings(tmp_path), live_ports=LivePorts(ports, ports, ports))
    ) as client:
        run_id = client.post(f"/api/investigations/{_create(client)}/runs").json()["run_id"]
        _drain(client)
        assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "COMPLETED"
        reports = client.get(f"/api/runs/{run_id}/reports").json()
        assert len(reports) == 1 and reports[0]["release_status"] == "RESTRICTED"
        report = client.get(f"/api/reports/{reports[0]['report_id']}").json()
        units = [
            unit
            for section in report["sections"]
            for unit in section["content"]["units"]
        ]
        assert units and all(u["unit_key"].startswith("emergency-") for u in units)
        assert all(u["content_class"] == "GOVERNANCE_DISCLOSURE" for u in units)
        assert all(not u["claim_refs"] for u in units)
        assert "不能作出已验证结论" in str(report)
        if with_material:
            assert client.get(f"/api/runs/{run_id}/sources").json()
            assert "已归档 1 个来源" in str(report)
