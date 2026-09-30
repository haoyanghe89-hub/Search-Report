from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.investigation.domain.enums import ExecutionStepStatus, RunMode, StepType
from marketpulse.investigation.feedback.models import AnalysisExecutionResult, FeedbackLoopConfig
from marketpulse.investigation.feedback.store import FeedbackStore
from marketpulse.investigation.harness.calls import BoundExternalCalls
from marketpulse.investigation.persistence.base import create_session_factory
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.ports.external import ModelRequest, StructuredModelResult
from marketpulse.investigation.recording.store import RepositoryRecordedCallStore
from tests.integration.investigation.test_phase43_feedback_loop import (
    TwoRoundFetch,
    TwoRoundModel,
    TwoRoundSearch,
    _orchestrator,
    _seed_investigation,
    _seed_run,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_time", ["2026-01-02/2026-01-06", "2026-02-30", "yesterday"])
async def test_invalid_candidate_dates_preserve_evidence_and_reach_verification(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
    invalid_time: str,
) -> None:
    class DatesModel(TwoRoundModel):
        async def generate(self, request: ModelRequest[Any]) -> StructuredModelResult[Any]:
            result = await super().generate(request)
            if request.response_model.__name__ == "AnalysisProposal":
                payload = result.output.model_dump(mode="json")
                evidence_key = payload["evidence"][0]["evidence_key"]
                payload["timeline_events"] = [
                    dict(
                        timeline_key="bad-date",
                        description="Unresolved date",
                        evidence_keys=[evidence_key],
                        event_time=invalid_time,
                    ),
                    dict(
                        timeline_key="good-date",
                        description="A dated event",
                        evidence_keys=[evidence_key],
                        event_time="2026-01-07T12:00:00Z",
                    ),
                ]
                payload["conflict_observations"] = [
                    dict(
                        claim_key=payload["claims"][0]["claim_key"],
                        evidence_key=evidence_key,
                        statement="A time-qualified observation",
                        conflict_type="TEMPORAL",
                        report_time=invalid_time,
                    )
                ]
                result = result.model_copy(
                    update={"output": request.response_model.model_validate(payload)}
                )
            return result

    repository, engine, _ = investigation_store
    _seed_investigation(repository)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "b")
    sessions = create_session_factory(engine)
    run_id = "RUN-date-regression"
    store = _seed_run(repository, engine, run_id=run_id, mode=RunMode.LIVE, max_sources=1)
    result = await _orchestrator(
        repository,
        engine,
        blobs,
        store,
        BoundExternalCalls(
            sessions=sessions,
            repository=repository,
            recordings=RepositoryRecordedCallStore(repository, blobs),
            live_search=TwoRoundSearch(),
            live_fetch=TwoRoundFetch(),
            live_model=DatesModel(),
        ),
        owner="date-worker",
        config=FeedbackLoopConfig(ground_model_quotes=True),
    ).run(run_id)
    state = FeedbackStore(sessions, repository).state(run_id)
    assert "VERIFY" in result.phase_trace
    assert state.evidence and state.claims
    assert len(state.timeline_events) == 1
    assert state.timeline_events[0].description == "A dated event"
    assert any("timeline event_time" in gap.reason for gap in state.gaps)
    assert any("conflict report_time" in gap.reason for gap in state.gaps)
    analysis = next(s for s in state.steps if s.step_type is StepType.ANALYSIS)
    assert analysis.status is ExecutionStepStatus.COMPLETED
    saved = AnalysisExecutionResult.model_validate_json(
        blobs.get_bytes(BlobRef.from_uri(analysis.output_refs[0]))
    )
    assert saved.proposal.timeline_events[0].event_time == invalid_time
    assert saved.proposal.conflict_observations[0].report_time == invalid_time
    assert "bad-date" in saved.rejected_candidate_keys
    assert not saved.conflict_observations
