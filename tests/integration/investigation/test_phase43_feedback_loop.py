from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.domain.enums import (
    AgentRole,
    ClaimType,
    ConflictResolutionStatus,
    ExecutionStepStatus,
    ResearchGapType,
    ResearchTaskStatus,
    RunMode,
    RunStatus,
    StepType,
    ValidationStatus,
    WorkflowPhase,
)
from marketpulse.investigation.domain.runtime import (
    ExecutionStep,
    Investigation,
    InvestigationQuestion,
    InvestigationRun,
    InvestigationScope,
    ResearchTask,
    RunBudget,
)
from marketpulse.investigation.feedback.models import FeedbackLoopConfig
from marketpulse.investigation.feedback.orchestrator import AgentFeedbackOrchestrator
from marketpulse.investigation.feedback.store import FeedbackStore, ReserveSourcesOperation
from marketpulse.investigation.feedback.trace import TraceResolver
from marketpulse.investigation.harness.calls import BoundExternalCalls
from marketpulse.investigation.harness.persistence import (
    HarnessStore,
    RunBudgetExceededError,
)
from marketpulse.investigation.harness.runtime import InvestigationHarness
from marketpulse.investigation.harness.state_machine import Route
from marketpulse.investigation.ingestion.registry import DocumentParserRegistry
from marketpulse.investigation.persistence.base import create_session_factory
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.ports.external import (
    FetchRequest,
    FetchResult,
    ModelRequest,
    ModelUsage,
    SearchRequest,
    SearchResult,
    SearchResultItem,
    StructuredModelResult,
)
from marketpulse.investigation.recording.store import RepositoryRecordedCallStore
from marketpulse.investigation.validation.integrity import EvidenceIntegrityValidator
from marketpulse.investigation.validation.models import RecognizedArtifactVersions
from marketpulse.investigation.validation.policy import ValidationPolicy

NOW = datetime(2026, 9, 22, 8, tzinfo=UTC)
INVESTIGATION_ID = "I-phase43-feedback"


class TwoRoundSearch:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, request: SearchRequest) -> SearchResult:
        self.calls += 1
        if "official" in request.query.casefold():
            item = SearchResultItem(
                title="Official final record",
                url="https://agency.example.test/final-record",
                snippet="Official confirmation",
                rank=1,
                source_type_hint="official",
                publisher="Public Agency",
                organization="Public Agency",
                author="Records Office",
                is_official=True,
                is_first_hand=True,
                quality_metadata={
                    "data_provenance": "direct agency record",
                    "methodology": "documented official finding",
                    "speculation_level": 0.0,
                    "explicit_uncertainty": True,
                },
            )
        else:
            item = SearchResultItem(
                title="Independent secondary account",
                url="https://publisher.example.test/account",
                snippet="Independent account of the event",
                rank=1,
                source_type_hint="media",
                publisher="Independent Publisher",
                author="Named Reporter",
                is_official=False,
                is_first_hand=False,
                quality_metadata={
                    "data_provenance": "named interviews and public records",
                    "methodology": "document review",
                    "speculation_level": 0.1,
                    "explicit_uncertainty": True,
                },
            )
        return SearchResult(items=(item,), provider="fixture-search", retrieved_at=NOW)


class TwoRoundFetch:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, request: FetchRequest) -> FetchResult:
        self.calls += 1
        official = "agency" in str(request.url)
        text = (
            "The agency final record confirms the public event occurred."
            if official
            else "An independent account reports that the public event occurred."
        )
        return FetchResult(
            final_url=request.url,
            status_code=200,
            content_type="text/html",
            body=f"<html><body><p>{text}</p></body></html>".encode(),
            fetched_at=NOW,
        )


class TwoRoundModel:
    def __init__(self) -> None:
        self.calls = 0
        self.analysis_calls = 0

    async def generate(self, request: ModelRequest[Any]) -> StructuredModelResult[Any]:
        self.calls += 1
        context = json.loads(request.messages[1].content)["bounded_context"]
        name = request.response_model.__name__
        if name == "PlanProposal":
            payload: dict[str, Any] = {
                "tasks": [
                    {
                        "task_key": "initial-event-record",
                        "target_question_key": "Q-1",
                        "objective": "Find a traceable account of the event",
                        "purpose": "Establish the event from public evidence",
                        "priority": 90,
                        "preferred_source_types": ["NEWS"],
                        "desired_evidence_characteristics": ["exact event statement"],
                    }
                ]
            }
        elif name == "RouteProposal":
            gap = context["gaps"][0]
            payload = {
                "route": "COLLECT",
                "gap_keys": [gap["gap_key"]],
                "reason": "Collect a primary independent source",
                "tasks": [
                    {
                        "task_key": "official-corroboration",
                        "target_question_key": "Q-1",
                        "target_claim_key": gap.get("target_claim_key"),
                        "origin_gap_key": gap["gap_key"],
                        "objective": "Find the official primary record",
                        "purpose": "Close the independence and primary-source gap",
                        "priority": 100,
                        "preferred_source_types": ["OFFICIAL_REPORT"],
                    }
                ],
            }
        elif name == "ResearchProposal":
            official = context["round"] == 2
            payload = {
                "queries": [
                    {
                        "query_key": "official-query" if official else "secondary-query",
                        "query": (
                            "official public event final record"
                            if official
                            else "independent public event account"
                        ),
                        "target_question_key": "Q-1",
                        "purpose": (
                            "find official primary record"
                            if official
                            else "find independent event account"
                        ),
                        "max_results": 1,
                        "desired_source_role": "PRIMARY" if official else "SECONDARY",
                    }
                ]
            }
        elif name == "AnalysisProposal":
            self.analysis_calls += 1
            artifacts = context["artifacts"]
            artifact = (
                next(item for item in artifacts if item["is_official"])
                if self.analysis_calls == 2
                else artifacts[0]
            )
            evidence_key = f"event-evidence-{self.analysis_calls}"
            payload = {
                "evidence": [
                    {
                        "evidence_key": evidence_key,
                        "artifact_key": artifact["artifact_key"],
                        "quote": artifact["excerpt"],
                        "quote_hash": artifact["locator"]["quote_hash"],
                        "locator": artifact["locator"],
                    }
                ],
                "claims": [
                    {
                        "claim_key": "event-claim",
                        "statement": "The public event occurred.",
                        "canonical_statement": "The public event occurred.",
                        "claim_type": "EVENT_FACT",
                        "importance": "CRITICAL",
                        "critical": True,
                        "supporting_evidence_keys": [evidence_key],
                        "atomicity": {"is_atomic": True},
                    }
                ],
            }
        elif name == "VerificationProposal":
            payload = {
                "judgments": [
                    {
                        "claim_key": claim["claim_key"],
                        "evidence_key": evidence["evidence_key"],
                        "entailment": "ENTAILS",
                        "rationale": "The exact excerpt directly states the event fact.",
                        "semantic_confidence": 0.95,
                    }
                    for claim in context["claims"]
                    for evidence in context["evidence"]
                ]
            }
        else:
            raise AssertionError(name)
        output = request.response_model.model_validate(payload)
        return StructuredModelResult(
            output=output,
            provider="fixture-model",
            model="deterministic-structured",
            usage=ModelUsage(input_tokens=20, output_tokens=10),
        )


class CompositeFailureModel(TwoRoundModel):
    async def generate(self, request: ModelRequest[Any]) -> StructuredModelResult[Any]:
        name = request.response_model.__name__
        if name not in {"AnalysisProposal", "ClaimDecompositionProposal"}:
            return await super().generate(request)
        self.calls += 1
        context = json.loads(request.messages[1].content)["bounded_context"]
        if name == "AnalysisProposal":
            artifact = context["artifacts"][0]
            payload: dict[str, Any] = {
                "evidence": [
                    {
                        "evidence_key": "composite-evidence",
                        "artifact_key": artifact["artifact_key"],
                        "quote": artifact["excerpt"],
                        "quote_hash": artifact["locator"]["quote_hash"],
                        "locator": artifact["locator"],
                    }
                ],
                "claims": [
                    {
                        "claim_key": "composite-claim",
                        "statement": "The event occurred and the agency confirmed it.",
                        "claim_type": "EVENT_FACT",
                        "supporting_evidence_keys": ["composite-evidence"],
                        "atomicity": {
                            "is_atomic": False,
                            "issues": ["multiple propositions"],
                            "proposed_atomic_statements": ["The event occurred."],
                        },
                    }
                ],
            }
        else:
            composite = context["composite_claim"]
            payload = {"subclaims": [composite]}
        output = request.response_model.model_validate(payload)
        return StructuredModelResult(
            output=output,
            provider="fixture-model",
            model="deterministic-composite-failure",
            usage=ModelUsage(input_tokens=20, output_tokens=10),
        )


class TwoTaskSameRoundModel(TwoRoundModel):
    async def generate(self, request: ModelRequest[Any]) -> StructuredModelResult[Any]:
        name = request.response_model.__name__
        if name not in {"PlanProposal", "ResearchProposal"}:
            return await super().generate(request)
        self.calls += 1
        context = json.loads(request.messages[1].content)["bounded_context"]
        if name == "PlanProposal":
            payload: dict[str, Any] = {
                "tasks": [
                    {
                        "task_key": "same-round-secondary",
                        "target_question_key": "Q-1",
                        "objective": "Find an independent account",
                        "purpose": "Establish secondary support",
                        "priority": 100,
                    },
                    {
                        "task_key": "same-round-official",
                        "target_question_key": "Q-1",
                        "objective": "Find an official record",
                        "purpose": "Establish primary support",
                        "priority": 90,
                    },
                ]
            }
        else:
            official = context["task"]["task_key"] == "same-round-official"
            payload = {
                "queries": [
                    {
                        "query_key": "same-round-official" if official else "same-round-secondary",
                        "query": (
                            "official public event final record"
                            if official
                            else "independent public event account"
                        ),
                        "target_question_key": "Q-1",
                        "purpose": "find event record",
                        "max_results": 1,
                    }
                ]
            }
        return StructuredModelResult(
            output=request.response_model.model_validate(payload),
            provider="fixture-model",
            model="deterministic-same-round",
            usage=ModelUsage(input_tokens=20, output_tokens=10),
        )


class TwoClaimModel(TwoRoundModel):
    async def generate(self, request: ModelRequest[Any]) -> StructuredModelResult[Any]:
        if request.response_model.__name__ != "AnalysisProposal":
            return await super().generate(request)
        self.calls += 1
        self.analysis_calls += 1
        context = json.loads(request.messages[1].content)["bounded_context"]
        artifacts = context["artifacts"]
        official = [item for item in artifacts if item["is_official"]]
        artifact = official[0] if official else artifacts[0]
        evidence_key = f"two-claim-evidence-{self.analysis_calls}"
        payload: dict[str, Any] = {
            "evidence": [
                {
                    "evidence_key": evidence_key,
                    "artifact_key": artifact["artifact_key"],
                    "quote": artifact["excerpt"],
                    "quote_hash": artifact["locator"]["quote_hash"],
                    "locator": artifact["locator"],
                }
            ],
            "claims": [
                {
                    "claim_key": "event-claim-a",
                    "statement": "The public event occurred.",
                    "claim_type": "EVENT_FACT",
                    "importance": "CRITICAL",
                    "critical": True,
                    "supporting_evidence_keys": [evidence_key],
                    "atomicity": {"is_atomic": True},
                },
                {
                    "claim_key": "event-claim-b",
                    "statement": "The public event was recorded publicly.",
                    "claim_type": "EVENT_FACT",
                    "importance": "CRITICAL",
                    "critical": True,
                    "supporting_evidence_keys": [evidence_key],
                    "atomicity": {"is_atomic": True},
                },
            ],
        }
        return StructuredModelResult(
            output=request.response_model.model_validate(payload),
            provider="fixture-model",
            model="deterministic-two-claim",
            usage=ModelUsage(input_tokens=20, output_tokens=10),
        )


def _seed_investigation(repository: InvestigationRepository) -> None:
    repository.add(
        Investigation(
            investigation_id=INVESTIGATION_ID,
            title="Public event fixture",
            event_description="A controlled public event fixture.",
            investigation_goal="Establish whether the event occurred.",
            scope=InvestigationScope(summary="Public records and independent accounts"),
            questions=(
                InvestigationQuestion(
                    question_id="Q-1",
                    text="Did the public event occur?",
                    is_critical=True,
                ),
            ),
            critical_question_ids=("Q-1",),
            created_at=NOW,
            updated_at=NOW,
        )
    )


def _seed_run(
    repository: InvestigationRepository,
    engine: Engine,
    *,
    run_id: str,
    mode: RunMode,
    max_model_calls: int = 20,
    max_sources: int = 10,
    max_fetch_calls: int = 4,
) -> HarnessStore:
    repository.add(
        InvestigationRun(
            run_id=run_id,
            investigation_id=INVESTIGATION_ID,
            mode=mode,
            status=RunStatus.CREATED,
            current_phase=WorkflowPhase.CREATED,
            checkpoint_version=0,
            state_version=0,
            workflow_version="agent-feedback-v1",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    sessions = create_session_factory(engine)
    store = HarnessStore(sessions, repository, clock=lambda: NOW)
    store.install_budget(
        RunBudget(
            run_id=run_id,
            max_research_rounds=2,
            max_search_calls=4,
            max_fetch_calls=max_fetch_calls,
            max_model_calls=max_model_calls,
            max_tokens=20_000,
            max_wall_time_ms=60_000,
            max_sources=max_sources,
            updated_at=NOW,
        )
    )
    return store


def _integrity(blobs: LocalContentAddressedBlobStorage) -> EvidenceIntegrityValidator:
    return EvidenceIntegrityValidator(
        blobs=blobs,
        recognized_versions=RecognizedArtifactVersions(
            snapshot_parsers=frozenset({("html", "1", "text-normalizer-v1")}),
            artifact_processors=frozenset({("html", "1")}),
        ),
    )


def _orchestrator(
    repository: InvestigationRepository,
    engine: Engine,
    blobs: LocalContentAddressedBlobStorage,
    harness_store: HarnessStore,
    calls: BoundExternalCalls,
    *,
    owner: str,
    config: FeedbackLoopConfig | None = None,
) -> AgentFeedbackOrchestrator:
    sessions = create_session_factory(engine)
    tick = [0.0]

    def monotonic() -> float:
        tick[0] += 0.01
        return tick[0]

    integrity = _integrity(blobs)
    return AgentFeedbackOrchestrator(
        harness=InvestigationHarness(
            harness_store,
            blobs,
            monotonic=monotonic,
            heartbeat_interval_seconds=60,
        ),
        calls=calls,
        store=FeedbackStore(sessions, repository),
        repository=repository,
        blobs=blobs,
        parsers=DocumentParserRegistry.default(),
        validation_policy=ValidationPolicy(integrity=integrity),
        integrity=integrity,
        owner_instance_id=owner,
        config=config,
        clock=lambda: NOW,
    )


def test_transaction_operation_failure_rolls_back_business_output_and_checkpoint(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    _seed_investigation(repository)
    run_id = "RUN-phase43-uow-rollback"
    store = _seed_run(
        repository,
        engine,
        run_id=run_id,
        mode=RunMode.LIVE,
        max_sources=0,
    )
    step = store.begin_step(
        run_id=run_id,
        logical_step_key="bootstrap:phase43-rollback",
        input_fingerprint=hashlib.sha256(b"phase43-rollback").hexdigest(),
        workflow_version="agent-feedback-v1",
        phase=WorkflowPhase.CREATED,
        step_type=StepType.OTHER,
        agent_role=AgentRole.HARNESS,
        owner_instance_id="worker-rollback",
    )
    before = repository.get(InvestigationRun, run_id)
    task = ResearchTask(
        task_id="T-phase43-rollback",
        investigation_id=INVESTIGATION_ID,
        run_id=run_id,
        title="Rollback probe",
        objective="Prove typed transaction operations share the completion UoW",
        purpose="Atomic completion test",
        status=ResearchTaskStatus.PENDING,
        priority=50,
        round=1,
        created_at=NOW,
        updated_at=NOW,
    )

    with pytest.raises(RunBudgetExceededError, match="source budget exhausted"):
        store.complete_step(
            step_id=step.step_id,
            owner_instance_id="worker-rollback",
            elapsed_ms=10,
            output_refs=(),
            output_schema_version="PhaseTransition",
            business_outputs=(task,),
            transaction_operations=(
                ReserveSourcesOperation(run_id=run_id, count=1, updated_at=NOW),
            ),
            route=Route.PLAN,
        )

    after = repository.get(InvestigationRun, run_id)
    assert after.checkpoint_version == before.checkpoint_version
    assert after.state_version == before.state_version
    assert repository.get(ExecutionStep, step.step_id).status is ExecutionStepStatus.RUNNING
    assert repository.get(RunBudget, run_id).sources_used == 0
    with pytest.raises(KeyError):
        repository.get(ResearchTask, task.task_id)


@pytest.mark.asyncio
async def test_failed_claim_decomposition_persists_analysis_gap_and_never_succeeds(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
) -> None:
    repository, engine, _ = investigation_store
    _seed_investigation(repository)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "analysis-gap-blobs")
    sessions = create_session_factory(engine)
    run_id = "RUN-phase43-analysis-gap"
    store = _seed_run(
        repository,
        engine,
        run_id=run_id,
        mode=RunMode.LIVE,
        max_model_calls=5,
    )
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
            live_model=CompositeFailureModel(),
        ),
        owner="worker-analysis-gap",
    ).run(run_id)

    assert result.termination == "BLOCKED"
    assert result.summary.verified_claims == ()
    state = FeedbackStore(sessions, repository).state(run_id)
    assert any(
        gap.gap_type is ResearchGapType.ANALYSIS_ERROR and "decomposition" in gap.reason.casefold()
        for gap in state.gaps
    )


@pytest.mark.asyncio
async def test_two_round_feedback_and_agent_level_replay(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
) -> None:
    repository, engine, _ = investigation_store
    _seed_investigation(repository)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    sessions = create_session_factory(engine)
    recordings = RepositoryRecordedCallStore(repository, blobs)
    search = TwoRoundSearch()
    fetch = TwoRoundFetch()
    model = TwoRoundModel()

    live_run = "RUN-phase43-live"
    live_store = _seed_run(repository, engine, run_id=live_run, mode=RunMode.LIVE)
    live_calls = BoundExternalCalls(
        sessions=sessions,
        repository=repository,
        recordings=recordings,
        live_search=search,
        live_fetch=fetch,
        live_model=model,
    )
    live = await _orchestrator(
        repository, engine, blobs, live_store, live_calls, owner="worker-live"
    ).run(live_run)

    assert live.termination == "READY_FOR_REPORT"
    assert live.report_input.summary == live.summary
    assert live.phase_trace == (
        "PLAN",
        "COLLECT",
        "ANALYZE",
        "VERIFY",
        "COLLECT",
        "ANALYZE",
        "VERIFY",
    )
    assert len(live.summary.verified_claims) == 1
    live_state = FeedbackStore(sessions, repository).state(live_run)
    claim = live_state.claims[0]
    validations = repository.list_validation_results(claim.claim_id)
    assert [item.status for item in validations] == [
        ValidationStatus.UNVERIFIED,
        ValidationStatus.VERIFIED,
    ]
    assert any(
        item.origin_validation_id == validations[0].validation_id for item in live_state.gaps
    )
    followup = next(item for item in live_state.tasks if item.round == 2)
    assert followup.origin_gap_id is not None
    assert followup.parent_task_id is not None
    claim_trace = TraceResolver(sessions).claim(claim.claim_id)
    assert len(claim_trace.validation_ids) == 2
    assert len(claim_trace.evidence_paths) == 2
    assert claim_trace.analyst_model_call_ids
    assert claim_trace.researcher_model_call_ids
    assert claim_trace.search_call_ids
    assert claim_trace.fetch_call_ids
    gap_trace = TraceResolver(sessions).gap(followup.origin_gap_id)
    assert followup.task_id in gap_trace.followup_task_ids
    assert live.information_gain[-1].validation_improvements == (claim.claim_id,)

    provider_counts = (search.calls, fetch.calls, model.calls)
    replay_run = "RUN-phase43-replay"
    replay_store = _seed_run(repository, engine, run_id=replay_run, mode=RunMode.REPLAY)
    replay_calls = BoundExternalCalls(
        sessions=sessions,
        repository=repository,
        recordings=recordings,
        source_run_id=live_run,
    )
    replay = await _orchestrator(
        repository, engine, blobs, replay_store, replay_calls, owner="worker-replay"
    ).run(replay_run)

    assert replay.termination == "READY_FOR_REPORT"
    assert (search.calls, fetch.calls, model.calls) == provider_counts
    replay_state = FeedbackStore(sessions, repository).state(replay_run)
    replay_claim = replay_state.claims[0]
    replay_validations = repository.list_validation_results(replay_claim.claim_id)
    assert replay_claim.claim_id != claim.claim_id
    assert {item.validation_id for item in replay_validations}.isdisjoint(
        {item.validation_id for item in validations}
    )
    assert [item.status for item in replay_validations] == [
        ValidationStatus.UNVERIFIED,
        ValidationStatus.VERIFIED,
    ]
    assert replay.phase_trace == live.phase_trace


@pytest.mark.asyncio
async def test_information_gain_is_recorded_once_after_all_tasks_in_round(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
) -> None:
    repository, engine, _ = investigation_store
    _seed_investigation(repository)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "same-round-blobs")
    sessions = create_session_factory(engine)
    run_id = "RUN-phase43-same-round"
    store = _seed_run(repository, engine, run_id=run_id, mode=RunMode.LIVE)
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
            live_model=TwoTaskSameRoundModel(),
        ),
        owner="worker-same-round",
    ).run(run_id)

    assert result.termination == "READY_FOR_REPORT"
    assert tuple(item.round for item in result.information_gain) == (1,)
    assert result.information_gain[0].validation_improvements


@pytest.mark.asyncio
async def test_verifier_batches_all_claims_before_ready_for_report(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
) -> None:
    repository, engine, _ = investigation_store
    _seed_investigation(repository)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "verifier-batch-blobs")
    sessions = create_session_factory(engine)
    run_id = "RUN-phase43-verifier-batch"
    store = _seed_run(repository, engine, run_id=run_id, mode=RunMode.LIVE)
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
            live_model=TwoClaimModel(),
        ),
        owner="worker-verifier-batch",
        config=FeedbackLoopConfig(max_verification_claims=1),
    ).run(run_id)

    assert result.termination == "READY_FOR_REPORT"
    assert len(result.summary.verified_claims) == 2
    assert result.phase_trace.count("VERIFY") == 4
    assert tuple(item.round for item in result.information_gain) == (1, 2)


@pytest.mark.asyncio
async def test_budget_exhaustion_blocks_without_claiming_success(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
) -> None:
    repository, engine, _ = investigation_store
    _seed_investigation(repository)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "budget-blobs")
    sessions = create_session_factory(engine)
    run_id = "RUN-phase43-budget"
    store = _seed_run(
        repository,
        engine,
        run_id=run_id,
        mode=RunMode.LIVE,
        max_model_calls=0,
    )
    result = await _orchestrator(
        repository,
        engine,
        blobs,
        store,
        BoundExternalCalls(
            sessions=sessions,
            repository=repository,
            recordings=RepositoryRecordedCallStore(repository, blobs),
        ),
        owner="worker-budget",
    ).run(run_id)
    assert result.termination == "BLOCKED"
    assert result.reason == "BUDGET_EXHAUSTED"
    assert repository.get(InvestigationRun, run_id).status is RunStatus.BLOCKED
    assert result.summary.verified_claims == ()
    assert "BUDGET_EXHAUSTED" in result.summary.limitations


@pytest.mark.asyncio
async def test_mid_step_fetch_budget_exhaustion_becomes_explainable_block(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
) -> None:
    repository, engine, _ = investigation_store
    _seed_investigation(repository)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "fetch-budget-blobs")
    sessions = create_session_factory(engine)
    run_id = "RUN-phase43-fetch-budget"
    store = _seed_run(
        repository,
        engine,
        run_id=run_id,
        mode=RunMode.LIVE,
        max_fetch_calls=1,
    )
    result = await _orchestrator(
        repository,
        engine,
        blobs,
        store,
        BoundExternalCalls(
            sessions=sessions,
            repository=repository,
            recordings=RepositoryRecordedCallStore(repository, blobs),
            live_search=ConflictSearch(),
            live_fetch=ConflictFetch(),
            live_model=ConflictModel(),
        ),
        owner="worker-fetch-budget",
    ).run(run_id)

    assert result.termination == "BLOCKED"
    assert result.reason == "BUDGET_EXHAUSTED"
    assert repository.get(InvestigationRun, run_id).status is RunStatus.BLOCKED


class ConflictSearch:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, request: SearchRequest) -> SearchResult:
        self.calls += 1
        common: dict[str, Any] = {
            "publisher": "Named Public Source",
            "author": "Named Analyst",
            "is_first_hand": True,
            "quality_metadata": {
                "data_provenance": "direct count record",
                "methodology": "documented count method",
                "speculation_level": 0.0,
                "explicit_uncertainty": True,
            },
        }
        if "final" in request.query.casefold():
            items = (
                SearchResultItem(
                    title="Final authoritative release",
                    url="https://authority.example.test/final-count",
                    snippet="Final count",
                    rank=1,
                    source_type_hint="official",
                    is_official=True,
                    organization="Public Authority",
                    **common,
                ),
            )
        else:
            items = (
                SearchResultItem(
                    title="Early count A",
                    url="https://source-a.example.test/early-count",
                    snippet="Early estimate A",
                    rank=1,
                    source_type_hint="official",
                    is_official=True,
                    organization="Agency A",
                    **common,
                ),
                SearchResultItem(
                    title="Early count B",
                    url="https://source-b.example.test/early-count",
                    snippet="Early estimate B",
                    rank=2,
                    source_type_hint="research",
                    is_official=False,
                    organization="Research Group B",
                    **common,
                ),
            )
        return SearchResult(items=items, provider="conflict-search", retrieved_at=NOW)


class ConflictFetch:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, request: FetchRequest) -> FetchResult:
        self.calls += 1
        url = str(request.url)
        text = (
            "The final count was 2000 people."
            if "final-count" in url
            else "The preliminary count was 1500 people."
            if "source-a" in url
            else "The preliminary count was 2000 people."
        )
        return FetchResult(
            final_url=request.url,
            status_code=200,
            content_type="text/html",
            body=f"<html><body>{text}</body></html>".encode(),
            fetched_at=NOW,
        )


class ConflictModel:
    def __init__(self) -> None:
        self.calls = 0
        self.analysis_calls = 0

    async def generate(self, request: ModelRequest[Any]) -> StructuredModelResult[Any]:
        self.calls += 1
        context = json.loads(request.messages[1].content)["bounded_context"]
        name = request.response_model.__name__
        if name == "PlanProposal":
            payload: dict[str, Any] = {
                "tasks": [
                    {
                        "task_key": "compare-early-counts",
                        "target_question_key": "Q-1",
                        "objective": "Compare independent public counts",
                        "purpose": "Establish the reported quantitative value",
                        "priority": 100,
                    }
                ]
            }
        elif name == "RouteProposal":
            gap = context["gaps"][0]
            payload = {
                "route": "COLLECT",
                "gap_keys": [gap["gap_key"]],
                "reason": "Find final metadata that explains the conflict",
                "tasks": [
                    {
                        "task_key": "find-final-count",
                        "target_question_key": "Q-1",
                        "target_claim_key": gap.get("target_claim_key"),
                        "origin_gap_key": gap["gap_key"],
                        "objective": "Find the final authoritative count",
                        "purpose": "Resolve preliminary versus final reporting time",
                        "priority": 100,
                        "preferred_source_types": ["PUBLIC_DATA"],
                    }
                ],
            }
        elif name == "ResearchProposal":
            final = context["round"] == 2
            payload = {
                "queries": [
                    {
                        "query_key": "final-count" if final else "early-counts",
                        "query": (
                            "public event final authoritative count"
                            if final
                            else "public event initial quantitative reports"
                        ),
                        "target_question_key": "Q-1",
                        "purpose": (
                            "find final count metadata"
                            if final
                            else "compare early independent counts"
                        ),
                        "max_results": 2,
                    }
                ]
            }
        elif name == "AnalysisProposal":
            self.analysis_calls += 1
            artifacts = context["artifacts"]
            chosen = (
                [item for item in artifacts if "Final" in item["source_title"]]
                if self.analysis_calls == 2
                else [item for item in artifacts if "Early" in item["source_title"]]
            )
            evidence = [
                {
                    "evidence_key": f"count-evidence-{self.analysis_calls}-{index}",
                    "artifact_key": item["artifact_key"],
                    "quote": item["excerpt"],
                    "quote_hash": item["locator"]["quote_hash"],
                    "locator": item["locator"],
                }
                for index, item in enumerate(chosen, 1)
            ]
            payload = {
                "evidence": evidence,
                "claims": [
                    {
                        "claim_key": "quantitative-claim",
                        "statement": "The final reported count was 2000 people.",
                        "canonical_statement": "The final reported count was 2000 people.",
                        "claim_type": "QUANTITATIVE",
                        "importance": "CRITICAL",
                        "critical": True,
                        "supporting_evidence_keys": [item["evidence_key"] for item in evidence],
                        "time_qualifiers": {"time": "final"},
                        "scope_qualifiers": {
                            "value": 2000,
                            "unit": "people",
                            "scope": "affected population",
                            "definition": "reported count",
                            "methodology": "updated administrative count",
                        },
                        "atomicity": {"is_atomic": True},
                    }
                ],
                "conflict_observations": [
                    {
                        "claim_key": "quantitative-claim",
                        "evidence_key": item["evidence_key"],
                        "statement": item["quote"],
                        "conflict_type": "QUANTITATIVE",
                        "numeric_value": (1500 if "1500" in item["quote"] else 2000),
                        "unit": "people",
                        "report_time": (
                            "2026-09-22T10:00:00+00:00"
                            if self.analysis_calls == 2
                            else "2026-09-21T10:00:00+00:00"
                        ),
                        "report_stage": ("FINAL" if self.analysis_calls == 2 else "PRELIMINARY"),
                        "directness": 0.9,
                        "specificity": 0.9,
                    }
                    for item in evidence
                ],
            }
        elif name == "VerificationProposal":
            payload = {
                "judgments": [
                    {
                        "claim_key": claim["claim_key"],
                        "evidence_key": evidence["evidence_key"],
                        "entailment": "ENTAILS",
                        "rationale": "The excerpt reports the exact quantitative count.",
                        "semantic_confidence": 0.9,
                    }
                    for claim in context["claims"]
                    for evidence in context["evidence"]
                ]
            }
        else:
            raise AssertionError(name)
        return StructuredModelResult(
            output=request.response_model.model_validate(payload),
            provider="fixture-model",
            model="deterministic-conflict",
            usage=ModelUsage(input_tokens=20, output_tokens=10),
        )


@pytest.mark.asyncio
async def test_strong_conflict_feedback_resolves_by_reporting_time(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
) -> None:
    repository, engine, _ = investigation_store
    _seed_investigation(repository)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "conflict-blobs")
    sessions = create_session_factory(engine)
    search = ConflictSearch()
    fetch = ConflictFetch()
    model = ConflictModel()
    run_id = "RUN-phase43-conflict"
    store = _seed_run(repository, engine, run_id=run_id, mode=RunMode.LIVE)
    result = await _orchestrator(
        repository,
        engine,
        blobs,
        store,
        BoundExternalCalls(
            sessions=sessions,
            repository=repository,
            recordings=RepositoryRecordedCallStore(repository, blobs),
            live_search=search,
            live_fetch=fetch,
            live_model=model,
        ),
        owner="worker-conflict",
    ).run(run_id)

    assert result.termination == "READY_FOR_REPORT"
    state = FeedbackStore(sessions, repository).state(run_id)
    claim = state.claims[0]
    assert claim.claim_type is ClaimType.QUANTITATIVE
    validations = repository.list_validation_results(claim.claim_id)
    assert [item.status for item in validations] == [
        ValidationStatus.DISPUTED,
        ValidationStatus.VERIFIED,
    ]
    assert any(
        item.resolution_status is ConflictResolutionStatus.RESOLVED_WITH_TIME
        for item in state.conflicts
    )
    assert result.information_gain[-1].resolved_conflicts >= 1
    assert result.phase_trace[-4:] == ("VERIFY", "COLLECT", "ANALYZE", "VERIFY")
