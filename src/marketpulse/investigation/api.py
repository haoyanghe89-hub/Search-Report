"""Read/run JSON API for the Investigation Console.

The router exposes read-mostly endpoints over the persisted ``inv_*`` tables
plus report generation through the Phase 5 pipeline. DTOs are plain Pydantic
models local to this module; no authentication is applied here (local trusted
operator) — review authentication lives in the review router.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.investigation.domain.enums import (
    GapStatus,
    RelationStance,
    ReportType,
    RunStatus,
    StepType,
)
from marketpulse.investigation.domain.locators import deserialize_locator
from marketpulse.investigation.domain.runtime import (
    Investigation,
    InvestigationQuestion,
    InvestigationScope,
)
from marketpulse.investigation.persistence.models import (
    CitationRow,
    ClaimEvidenceRelationRow,
    ClaimRow,
    ConflictClaimRow,
    ConflictSetRow,
    EvidenceRow,
    ExecutionStepRow,
    InvestigationQuestionRow,
    InvestigationRow,
    InvestigationRunRow,
    ReportProjectionRow,
    ReportRow,
    ReportSectionClaimRow,
    ReportSectionRow,
    ResearchGapRow,
    ReviewDecisionRow,
    RunBudgetRow,
    SourceFamilyMemberRow,
    SourceFamilyRow,
    SourceRow,
    SourceSnapshotRow,
    TimelineEventRow,
    TimelineEvidenceRow,
    ValidationResultRow,
)
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.reporting.persistence import ReportGovernanceRepository
from marketpulse.investigation.reporting.pipeline import ReportPipeline
from marketpulse.investigation.reporting.writer import DeterministicWriter

router = APIRouter(prefix="/api")

_ROUND_PATTERN = re.compile(r"round-(\d+)")
_EXCERPT_LIMIT = 1200


# -- dependencies ------------------------------------------------------------


def _sessions(request: Request) -> sessionmaker[Session]:
    return cast("sessionmaker[Session]", request.app.state.inv_sessions)


def _repository(request: Request) -> InvestigationRepository:
    return cast("InvestigationRepository", request.app.state.inv_repository)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


# -- DTOs --------------------------------------------------------------------


class QuestionOut(BaseModel):
    question_id: str
    text: str
    is_critical: bool


class InvestigationSummaryOut(BaseModel):
    investigation_id: str
    title: str
    investigation_goal: str
    created_at: datetime
    updated_at: datetime
    run_count: int


class InvestigationCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    event_description: str = Field(min_length=1)
    investigation_goal: str = Field(min_length=1)
    questions: list[str] = Field(default_factory=list)


class BuiltInCaseOut(BaseModel):
    case_id: str
    title: str
    event_date: str
    location: str
    replay_ready: bool
    source_requirement: int


class ReplayCaseOut(BaseModel):
    case_id: str
    investigation_id: str
    run_id: str
    report_id: str | None
    run_status: str
    release_status: str | None


class ReplayCaseRunner(Protocol):
    async def run(self) -> ReplayCaseOut: ...


class InvestigationCountsOut(BaseModel):
    sources: int
    evidence: int
    claims: int
    conflicts: int
    open_gaps: int


class InvestigationDetailOut(BaseModel):
    investigation_id: str
    title: str
    event_description: str
    investigation_goal: str
    scope: dict[str, Any]
    questions: list[QuestionOut]
    created_at: datetime
    updated_at: datetime
    counts: InvestigationCountsOut


class RunOut(BaseModel):
    run_id: str
    investigation_id: str
    mode: str
    status: str
    current_phase: str
    workflow_version: str
    state_version: int
    checkpoint_version: int
    current_step_key: str | None
    last_completed_step_key: str | None
    interruption_reason: str | None
    origin_run_id: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class BudgetOut(BaseModel):
    max_research_rounds: int
    max_search_calls: int
    max_fetch_calls: int
    max_model_calls: int
    max_tokens: int
    max_wall_time_ms: int
    max_sources: int
    research_rounds_used: int
    search_calls_used: int
    fetch_calls_used: int
    model_calls_used: int
    tokens_used: int
    consumed_wall_time_ms: int
    sources_used: int


class RunDetailOut(BaseModel):
    run: RunOut
    budget: BudgetOut | None


class StepOut(BaseModel):
    step_id: str
    logical_step_key: str
    phase: str
    step_type: str
    agent_role: str
    status: str
    attempt: int
    research_round: int | None
    active_elapsed_ms: int
    error_code: str | None
    retryable: bool
    dependency_keys: list[str]
    started_at: datetime | None
    completed_at: datetime | None


class SourceOut(BaseModel):
    source_id: str
    canonical_url: str
    title: str
    publisher: str | None
    organization: str | None
    source_type: str
    is_official: bool
    is_first_hand: bool
    author: str | None
    published_at: datetime | None
    discovered_at: datetime
    syndication_cluster_id: str | None
    family_id: str | None
    snapshot_id: str | None
    retrieved_at: datetime | None
    http_status: int | None
    parse_status: str | None
    evidence_eligible: bool | None


class EvidenceRelationOut(BaseModel):
    claim_id: str
    stance: str
    entailment_status: str


class EvidenceOut(BaseModel):
    evidence_id: str
    run_id: str
    snapshot_id: str
    artifact_id: str | None
    source_id: str | None
    content: str
    locator_type: str
    locator_payload: dict[str, Any]
    event_time: datetime | None
    extracted_at: datetime
    extractor_name: str
    extractor_version: str
    research_task_id: str | None
    relations: list[EvidenceRelationOut]


class ClaimOut(BaseModel):
    claim_id: str
    statement: str
    claim_type: str
    importance: str
    is_critical: bool
    validation_status: str
    confidence: float | None
    confidence_basis: str | None
    validation_basis: str | None
    latest_validation_id: str | None
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    created_at: datetime
    updated_at: datetime


class ConflictOut(BaseModel):
    conflict_id: str
    conflict_type: str
    severity: str
    status: str
    resolution_status: str
    resolution_basis: str | None
    resolution_summary: str | None
    possible_causes: list[str]
    competing_values: list[Any]
    possible_explanations: list[str]
    claim_ids: list[str]
    created_at: datetime
    updated_at: datetime


class GapOut(BaseModel):
    gap_id: str
    gap_type: str
    reason: str
    severity: str
    status: str
    suggested_action: str | None
    suggested_actions: list[str]
    target_question_id: str | None
    target_claim_id: str | None
    source_id: str | None
    follow_up_task_id: str | None
    created_at: datetime
    resolved_at: datetime | None


class TimelineEventOut(BaseModel):
    timeline_event_id: str
    event_time: datetime | None
    time_precision: str
    description: str
    validation_status: str
    evidence_ids: list[str]


class ReportSummaryOut(BaseModel):
    report_id: str
    investigation_id: str
    run_id: str
    version: int
    report_type: str
    report_hash: str
    claim_set_hash: str
    citation_set_hash: str
    release_policy_version: str
    schema_version: str
    created_at: datetime
    review_status: str | None
    release_status: str | None


class ReportSectionOut(BaseModel):
    section_id: str
    section_type: str
    order_index: int
    content: dict[str, Any] | None
    claim_ids: list[str]


class ReportDetailOut(BaseModel):
    report: ReportSummaryOut
    sections: list[ReportSectionOut]


class ReportGenerateIn(BaseModel):
    report_type: Literal["FULL_INVESTIGATION", "RESTRICTED_INVESTIGATION", "INVESTIGATION_STATUS"]


class CitationOut(BaseModel):
    citation_id: str
    report_id: str
    display_ordinal: int
    section_key: str
    unit_key: str
    claim_id: str
    evidence_id: str
    canonical_locator: dict[str, Any]
    citation_hash: str
    created_at: datetime


class CitationClaimOut(BaseModel):
    claim_id: str
    statement: str
    claim_type: str
    validation_status: str
    confidence: float | None
    validation_basis: str | None


class CitationEvidenceOut(BaseModel):
    evidence_id: str
    excerpt: str
    exact_quote: str | None
    locator_type: str
    locator_payload: dict[str, Any]


class CitationSourceOut(BaseModel):
    source_id: str
    title: str
    publisher: str | None
    source_type: str
    canonical_url: str
    published_at: datetime | None
    retrieved_at: datetime | None


class CitationDetailOut(BaseModel):
    citation: CitationOut
    claim: CitationClaimOut | None
    evidence: CitationEvidenceOut | None
    source: CitationSourceOut | None


class EvaluationOut(BaseModel):
    evaluation_id: str
    policy_version: str
    decision: str
    release_status: str
    review_status: str
    evaluation_hash: str
    report_hash: str
    claim_set_hash: str
    citation_set_hash: str
    hard_finding_count: int
    governance_finding_count: int
    created_at: datetime


class FindingOut(BaseModel):
    finding_id: str
    validator: str
    severity: str
    code: str
    detail: str
    section_key: str | None
    unit_key: str | None
    created_at: datetime


class ReviewRequestOut(BaseModel):
    request_id: str
    report_id: str
    report_version: int
    policy_version: str
    trigger_reason: str
    report_hash: str
    claim_set_hash: str
    citation_set_hash: str
    evaluation_hash: str
    created_at: datetime
    expires_at: datetime


class ReviewDecisionOut(BaseModel):
    review_id: str
    report_id: str
    reviewer_id: str
    decision: str
    reason: str
    report_version: int
    report_hash: str
    claim_set_hash: str
    decision_origin: str
    created_at: datetime


class ReviewDetailOut(BaseModel):
    report_id: str
    review_status: str | None
    release_status: str | None
    evaluation: EvaluationOut | None
    findings: list[FindingOut]
    pending_request: ReviewRequestOut | None
    history: list[ReviewDecisionOut]


# -- row to DTO mapping --------------------------------------------------------


def _run_out(row: InvestigationRunRow) -> RunOut:
    return RunOut(
        run_id=row.run_id,
        investigation_id=row.investigation_id,
        mode=row.mode.value,
        status=row.status.value,
        current_phase=row.current_phase.value,
        workflow_version=row.workflow_version,
        state_version=row.state_version,
        checkpoint_version=row.checkpoint_version,
        current_step_key=row.current_step_key,
        last_completed_step_key=row.last_completed_step_key,
        interruption_reason=row.interruption_reason,
        origin_run_id=row.origin_run_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def _budget_out(row: RunBudgetRow) -> BudgetOut:
    return BudgetOut(
        max_research_rounds=row.max_research_rounds,
        max_search_calls=row.max_search_calls,
        max_fetch_calls=row.max_fetch_calls,
        max_model_calls=row.max_model_calls,
        max_tokens=row.max_tokens,
        max_wall_time_ms=row.max_wall_time_ms,
        max_sources=row.max_sources,
        research_rounds_used=row.research_rounds_used,
        search_calls_used=row.search_calls_used,
        fetch_calls_used=row.fetch_calls_used,
        model_calls_used=row.model_calls_used,
        tokens_used=row.tokens_used,
        consumed_wall_time_ms=row.consumed_wall_time_ms,
        sources_used=row.sources_used,
    )


_PHASE_BY_STEP_TYPE = {
    StepType.PLANNING: "PLAN",
    StepType.RESEARCH: "COLLECT",
    StepType.SEARCH: "COLLECT",
    StepType.FETCH: "COLLECT",
    StepType.EXTRACTION: "COLLECT",
    StepType.ANALYSIS: "ANALYZE",
    StepType.VALIDATION: "VERIFY",
    StepType.REPORTING: "REPORT",
    StepType.REVIEW: "REVIEW",
}


def _step_out(row: ExecutionStepRow) -> StepOut:
    phase = _PHASE_BY_STEP_TYPE.get(row.step_type)
    if phase is None:
        phase = "CREATED" if "enter-plan" in row.logical_step_key else "REPORT"
    round_match = _ROUND_PATTERN.search(row.logical_step_key)
    return StepOut(
        step_id=row.step_id,
        logical_step_key=row.logical_step_key,
        phase=phase,
        step_type=row.step_type.value,
        agent_role=row.agent_role.value,
        status=row.status.value,
        attempt=row.attempt,
        research_round=int(round_match.group(1)) if round_match else None,
        active_elapsed_ms=row.active_elapsed_ms,
        error_code=row.error_code,
        retryable=row.retryable,
        dependency_keys=list(row.dependency_keys),
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def _report_summary(report: ReportRow, projection: ReportProjectionRow | None) -> ReportSummaryOut:
    return ReportSummaryOut(
        report_id=report.report_id,
        investigation_id=report.investigation_id,
        run_id=report.run_id,
        version=report.version,
        report_type=report.report_type.value,
        report_hash=report.report_hash,
        claim_set_hash=report.claim_set_hash,
        citation_set_hash=report.citation_set_hash,
        release_policy_version=report.release_policy_version,
        schema_version=report.schema_version,
        created_at=report.created_at,
        review_status=projection.review_status.value if projection else None,
        release_status=projection.release_status.value if projection else None,
    )


def _citation_out(row: CitationRow) -> CitationOut:
    return CitationOut(
        citation_id=row.citation_id,
        report_id=row.report_id,
        display_ordinal=row.display_ordinal,
        section_key=row.section_key,
        unit_key=row.unit_key,
        claim_id=row.claim_id,
        evidence_id=row.evidence_id,
        canonical_locator=dict(row.canonical_locator),
        citation_hash=row.citation_hash,
        created_at=row.created_at,
    )


def _exact_quote(content: str, locator_payload: dict[str, Any]) -> str | None:
    try:
        locator = deserialize_locator(json.dumps(locator_payload))
    except ValueError:
        return None
    if locator.start >= len(content):
        return None
    return content[locator.start : min(locator.end, len(content))]


def _excerpt(content: str) -> str:
    if len(content) <= _EXCERPT_LIMIT:
        return content
    return content[:_EXCERPT_LIMIT] + "…"


# -- shared lookups ------------------------------------------------------------


def _get_run_row(session: Session, run_id: str) -> InvestigationRunRow:
    row = session.get(InvestigationRunRow, run_id)
    if row is None:
        raise _error(404, "RUN_NOT_FOUND", f"run not found: {run_id}")
    return row


def _get_investigation_row(session: Session, investigation_id: str) -> InvestigationRow:
    row = session.get(InvestigationRow, investigation_id)
    if row is None:
        raise _error(404, "INVESTIGATION_NOT_FOUND", f"investigation not found: {investigation_id}")
    return row


def _get_report_row(session: Session, report_id: str) -> ReportRow:
    row = session.get(ReportRow, report_id)
    if row is None:
        raise _error(404, "REPORT_NOT_FOUND", f"report not found: {report_id}")
    return row


def _report_detail(session: Session, report_id: str) -> ReportDetailOut:
    report = _get_report_row(session, report_id)
    projection = session.get(ReportProjectionRow, report_id)
    sections = session.scalars(
        select(ReportSectionRow)
        .where(ReportSectionRow.report_id == report_id)
        .order_by(ReportSectionRow.order_index)
    ).all()
    section_ids = [section.section_id for section in sections]
    claims_by_section: dict[str, list[str]] = {}
    if section_ids:
        links = session.scalars(
            select(ReportSectionClaimRow).where(ReportSectionClaimRow.section_id.in_(section_ids))
        ).all()
        for link in links:
            claims_by_section.setdefault(link.section_id, []).append(link.claim_id)
    return ReportDetailOut(
        report=_report_summary(report, projection),
        sections=[
            ReportSectionOut(
                section_id=section.section_id,
                section_type=section.section_type,
                order_index=section.order_index,
                content=(
                    dict(section.structured_content)
                    if section.structured_content is not None
                    else None
                ),
                claim_ids=claims_by_section.get(section.section_id, []),
            )
            for section in sections
        ],
    )


# -- investigation endpoints ---------------------------------------------------


@router.get("/cases", response_model=list[BuiltInCaseOut])
def list_built_in_cases(request: Request) -> list[BuiltInCaseOut]:
    runner = getattr(request.app.state, "east_palestine_replay", None)
    return [
        BuiltInCaseOut(
            case_id="east-palestine-2023",
            title="East Palestine hazardous-material train derailment",
            event_date="2023-02-03",
            location="East Palestine, Ohio, United States",
            replay_ready=runner is not None,
            source_requirement=10,
        )
    ]


@router.post(
    "/cases/east-palestine-2023/replay",
    response_model=ReplayCaseOut,
    status_code=202,
)
async def run_east_palestine_replay(request: Request) -> ReplayCaseOut:
    runner = cast(
        "ReplayCaseRunner | None",
        getattr(request.app.state, "east_palestine_replay", None),
    )
    if runner is None:
        raise _error(503, "REPLAY_NOT_CONFIGURED", "East Palestine replay is not configured")
    return await runner.run()


@router.get("/investigations", response_model=list[InvestigationSummaryOut])
def list_investigations(request: Request) -> list[InvestigationSummaryOut]:
    sessions = _sessions(request)
    with sessions() as session:
        rows = session.scalars(
            select(InvestigationRow).order_by(InvestigationRow.created_at.desc())
        ).all()
        run_counts: dict[str, int] = {}
        count_rows = session.execute(
            select(InvestigationRunRow.investigation_id, func.count()).group_by(
                InvestigationRunRow.investigation_id
            )
        )
        for investigation_id, count in count_rows:
            run_counts[investigation_id] = int(count)
        return [
            InvestigationSummaryOut(
                investigation_id=row.investigation_id,
                title=row.title,
                investigation_goal=row.investigation_goal,
                created_at=row.created_at,
                updated_at=row.updated_at,
                run_count=run_counts.get(row.investigation_id, 0),
            )
            for row in rows
        ]


@router.post("/investigations", response_model=InvestigationDetailOut, status_code=201)
def create_investigation(
    payload: InvestigationCreateIn, request: Request
) -> InvestigationDetailOut:
    repository = _repository(request)
    now = _utcnow()
    questions = tuple(
        InvestigationQuestion(question_id=f"Q-{uuid.uuid4().hex}", text=text, is_critical=False)
        for text in payload.questions
        if text.strip()
    )
    investigation = Investigation(
        investigation_id=f"INV-{uuid.uuid4().hex}",
        title=payload.title,
        event_description=payload.event_description,
        investigation_goal=payload.investigation_goal,
        scope=InvestigationScope(summary=payload.event_description),
        questions=questions,
        critical_question_ids=(),
        created_at=now,
        updated_at=now,
    )
    repository.add(investigation)
    return InvestigationDetailOut(
        investigation_id=investigation.investigation_id,
        title=investigation.title,
        event_description=investigation.event_description,
        investigation_goal=investigation.investigation_goal,
        scope=dict(investigation.scope.model_dump(mode="json")),
        questions=[
            QuestionOut(
                question_id=item.question_id,
                text=item.text,
                is_critical=item.is_critical,
            )
            for item in investigation.questions
        ],
        created_at=now,
        updated_at=now,
        counts=InvestigationCountsOut(sources=0, evidence=0, claims=0, conflicts=0, open_gaps=0),
    )


@router.get("/investigations/{investigation_id}", response_model=InvestigationDetailOut)
def get_investigation(investigation_id: str, request: Request) -> InvestigationDetailOut:
    sessions = _sessions(request)
    with sessions() as session:
        row = _get_investigation_row(session, investigation_id)
        questions = session.scalars(
            select(InvestigationQuestionRow).where(
                InvestigationQuestionRow.investigation_id == investigation_id
            )
        ).all()

        def _count(model: type[Any]) -> int:
            value = session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.investigation_id == investigation_id)
            )
            return int(value or 0)

        run_ids = select(InvestigationRunRow.run_id).where(
            InvestigationRunRow.investigation_id == investigation_id
        )
        evidence_count = session.scalar(
            select(func.count()).select_from(EvidenceRow).where(EvidenceRow.run_id.in_(run_ids))
        )
        open_gap_count = session.scalar(
            select(func.count())
            .select_from(ResearchGapRow)
            .where(
                ResearchGapRow.investigation_id == investigation_id,
                ResearchGapRow.status.in_([GapStatus.OPEN, GapStatus.IN_PROGRESS]),
            )
        )
        counts = InvestigationCountsOut(
            sources=_count(SourceRow),
            evidence=int(evidence_count or 0),
            claims=_count(ClaimRow),
            conflicts=_count(ConflictSetRow),
            open_gaps=int(open_gap_count or 0),
        )
        return InvestigationDetailOut(
            investigation_id=row.investigation_id,
            title=row.title,
            event_description=row.event_description,
            investigation_goal=row.investigation_goal,
            scope=dict(row.scope),
            questions=[
                QuestionOut(
                    question_id=item.question_id,
                    text=item.text,
                    is_critical=item.is_critical,
                )
                for item in questions
            ],
            created_at=row.created_at,
            updated_at=row.updated_at,
            counts=counts,
        )


@router.get("/investigations/{investigation_id}/runs", response_model=list[RunOut])
def list_investigation_runs(investigation_id: str, request: Request) -> list[RunOut]:
    sessions = _sessions(request)
    with sessions() as session:
        _get_investigation_row(session, investigation_id)
        rows = session.scalars(
            select(InvestigationRunRow)
            .where(InvestigationRunRow.investigation_id == investigation_id)
            .order_by(InvestigationRunRow.created_at.desc())
        ).all()
        return [_run_out(row) for row in rows]


# -- run endpoints -------------------------------------------------------------


@router.get("/runs/{run_id}", response_model=RunDetailOut)
def get_run(run_id: str, request: Request) -> RunDetailOut:
    sessions = _sessions(request)
    with sessions() as session:
        row = _get_run_row(session, run_id)
        budget = session.get(RunBudgetRow, run_id)
        return RunDetailOut(
            run=_run_out(row), budget=_budget_out(budget) if budget is not None else None
        )


@router.get("/runs/{run_id}/steps", response_model=list[StepOut])
def list_run_steps(run_id: str, request: Request) -> list[StepOut]:
    sessions = _sessions(request)
    with sessions() as session:
        _get_run_row(session, run_id)
        rows = session.scalars(
            select(ExecutionStepRow)
            .where(ExecutionStepRow.run_id == run_id)
            .order_by(ExecutionStepRow.started_at.asc().nulls_last(), ExecutionStepRow.step_id)
        ).all()
        return [_step_out(row) for row in rows]


@router.get("/runs/{run_id}/sources", response_model=list[SourceOut])
def list_run_sources(run_id: str, request: Request) -> list[SourceOut]:
    sessions = _sessions(request)
    with sessions() as session:
        _get_run_row(session, run_id)
        snapshots = session.scalars(
            select(SourceSnapshotRow)
            .where(SourceSnapshotRow.run_id == run_id)
            .order_by(SourceSnapshotRow.retrieved_at.desc())
        ).all()
        latest_by_source: dict[str, SourceSnapshotRow] = {}
        for snapshot in snapshots:
            latest_by_source.setdefault(snapshot.source_id, snapshot)
        source_ids = list(latest_by_source)
        if not source_ids:
            return []
        sources = session.scalars(
            select(SourceRow).where(SourceRow.source_id.in_(source_ids))
        ).all()
        family_by_source: dict[str, str] = {}
        family_pairs = session.execute(
            select(SourceFamilyMemberRow.source_id, SourceFamilyRow.family_id)
            .join(
                SourceFamilyRow,
                SourceFamilyRow.family_record_id == SourceFamilyMemberRow.family_record_id,
            )
            .where(SourceFamilyMemberRow.source_id.in_(source_ids))
        )
        for member_source_id, family_id in family_pairs:
            family_by_source.setdefault(member_source_id, family_id)
        return [
            SourceOut(
                source_id=source.source_id,
                canonical_url=source.canonical_url,
                title=source.title,
                publisher=source.publisher,
                organization=source.organization,
                source_type=source.source_type.value,
                is_official=source.is_official,
                is_first_hand=source.is_first_hand,
                author=source.author,
                published_at=source.published_at,
                discovered_at=source.discovered_at,
                syndication_cluster_id=source.syndication_cluster_id,
                family_id=family_by_source.get(source.source_id),
                snapshot_id=(snapshot := latest_by_source[source.source_id]).snapshot_id,
                retrieved_at=snapshot.retrieved_at,
                http_status=snapshot.http_status,
                parse_status=snapshot.parse_status.value,
                evidence_eligible=snapshot.evidence_eligible,
            )
            for source in sorted(sources, key=lambda item: item.discovered_at)
        ]


@router.get("/runs/{run_id}/evidence", response_model=list[EvidenceOut])
def list_run_evidence(run_id: str, request: Request) -> list[EvidenceOut]:
    sessions = _sessions(request)
    with sessions() as session:
        _get_run_row(session, run_id)
        rows = session.scalars(
            select(EvidenceRow)
            .where(EvidenceRow.run_id == run_id)
            .order_by(EvidenceRow.extracted_at)
        ).all()
        evidence_ids = [row.evidence_id for row in rows]
        relations_by_evidence: dict[str, list[EvidenceRelationOut]] = {}
        if evidence_ids:
            relations = session.scalars(
                select(ClaimEvidenceRelationRow).where(
                    ClaimEvidenceRelationRow.evidence_id.in_(evidence_ids)
                )
            ).all()
            for relation in relations:
                relations_by_evidence.setdefault(relation.evidence_id, []).append(
                    EvidenceRelationOut(
                        claim_id=relation.claim_id,
                        stance=relation.stance.value,
                        entailment_status=relation.entailment_status.value,
                    )
                )
        snapshot_ids = list({row.snapshot_id for row in rows})
        source_by_snapshot: dict[str, str] = {}
        if snapshot_ids:
            snapshot_rows = session.scalars(
                select(SourceSnapshotRow).where(SourceSnapshotRow.snapshot_id.in_(snapshot_ids))
            ).all()
            for snapshot in snapshot_rows:
                source_by_snapshot[snapshot.snapshot_id] = snapshot.source_id
        return [
            EvidenceOut(
                evidence_id=row.evidence_id,
                run_id=row.run_id,
                snapshot_id=row.snapshot_id,
                artifact_id=row.artifact_id,
                source_id=source_by_snapshot.get(row.snapshot_id),
                content=row.content,
                locator_type=row.locator_type.value,
                locator_payload=dict(row.locator_payload),
                event_time=row.event_time,
                extracted_at=row.extracted_at,
                extractor_name=row.extractor_name,
                extractor_version=row.extractor_version,
                research_task_id=row.research_task_id,
                relations=relations_by_evidence.get(row.evidence_id, []),
            )
            for row in rows
        ]


@router.get("/runs/{run_id}/claims", response_model=list[ClaimOut])
def list_run_claims(run_id: str, request: Request) -> list[ClaimOut]:
    sessions = _sessions(request)
    with sessions() as session:
        _get_run_row(session, run_id)
        rows = session.scalars(
            select(ClaimRow).where(ClaimRow.run_id == run_id).order_by(ClaimRow.created_at)
        ).all()
        claim_ids = [row.claim_id for row in rows]
        supporting: dict[str, list[str]] = {}
        contradicting: dict[str, list[str]] = {}
        if claim_ids:
            relations = session.scalars(
                select(ClaimEvidenceRelationRow).where(
                    ClaimEvidenceRelationRow.claim_id.in_(claim_ids)
                )
            ).all()
            for relation in relations:
                if relation.stance is RelationStance.SUPPORTS:
                    supporting.setdefault(relation.claim_id, []).append(relation.evidence_id)
                elif relation.stance is RelationStance.CONTRADICTS:
                    contradicting.setdefault(relation.claim_id, []).append(relation.evidence_id)
        validation_ids = [
            row.latest_validation_id for row in rows if row.latest_validation_id is not None
        ]
        basis_by_validation: dict[str, str] = {}
        if validation_ids:
            validations = session.scalars(
                select(ValidationResultRow).where(
                    ValidationResultRow.validation_id.in_(validation_ids)
                )
            ).all()
            for validation in validations:
                basis_by_validation[validation.validation_id] = validation.validation_basis
        return [
            ClaimOut(
                claim_id=row.claim_id,
                statement=row.statement,
                claim_type=row.claim_type.value,
                importance=row.importance.value,
                is_critical=row.is_critical,
                validation_status=row.validation_status.value,
                confidence=row.confidence,
                confidence_basis=row.confidence_basis,
                validation_basis=(
                    basis_by_validation.get(row.latest_validation_id)
                    if row.latest_validation_id is not None
                    else None
                ),
                latest_validation_id=row.latest_validation_id,
                supporting_evidence_ids=supporting.get(row.claim_id, []),
                contradicting_evidence_ids=contradicting.get(row.claim_id, []),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


@router.get("/runs/{run_id}/conflicts", response_model=list[ConflictOut])
def list_run_conflicts(run_id: str, request: Request) -> list[ConflictOut]:
    sessions = _sessions(request)
    with sessions() as session:
        _get_run_row(session, run_id)
        rows = session.scalars(
            select(ConflictSetRow)
            .where(ConflictSetRow.run_id == run_id)
            .order_by(ConflictSetRow.created_at)
        ).all()
        conflict_ids = [row.conflict_id for row in rows]
        claims_by_conflict: dict[str, list[str]] = {}
        if conflict_ids:
            links = session.scalars(
                select(ConflictClaimRow).where(ConflictClaimRow.conflict_id.in_(conflict_ids))
            ).all()
            for link in links:
                claims_by_conflict.setdefault(link.conflict_id, []).append(link.claim_id)
        return [
            ConflictOut(
                conflict_id=row.conflict_id,
                conflict_type=row.conflict_type.value,
                severity=row.severity.value,
                status=row.status.value,
                resolution_status=str(row.resolution_status),
                resolution_basis=row.resolution_basis,
                resolution_summary=row.resolution_summary,
                possible_causes=list(row.possible_causes),
                competing_values=list(row.competing_values),
                possible_explanations=list(row.possible_explanations),
                claim_ids=claims_by_conflict.get(row.conflict_id, []),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


@router.get("/runs/{run_id}/gaps", response_model=list[GapOut])
def list_run_gaps(run_id: str, request: Request) -> list[GapOut]:
    sessions = _sessions(request)
    with sessions() as session:
        _get_run_row(session, run_id)
        rows = session.scalars(
            select(ResearchGapRow)
            .where(ResearchGapRow.run_id == run_id)
            .order_by(ResearchGapRow.created_at)
        ).all()
        return [
            GapOut(
                gap_id=row.gap_id,
                gap_type=str(row.gap_type),
                reason=row.reason,
                severity=row.severity.value,
                status=row.status.value,
                suggested_action=row.suggested_action,
                suggested_actions=list(row.suggested_actions),
                target_question_id=row.target_question_id,
                target_claim_id=row.target_claim_id,
                source_id=row.source_id,
                follow_up_task_id=None,
                created_at=row.created_at,
                resolved_at=row.resolved_at,
            )
            for row in rows
        ]


@router.get("/runs/{run_id}/timeline", response_model=list[TimelineEventOut])
def list_run_timeline(run_id: str, request: Request) -> list[TimelineEventOut]:
    sessions = _sessions(request)
    with sessions() as session:
        _get_run_row(session, run_id)
        rows = session.scalars(
            select(TimelineEventRow)
            .where(TimelineEventRow.run_id == run_id)
            .order_by(TimelineEventRow.event_time)
        ).all()
        event_ids = [row.timeline_event_id for row in rows]
        evidence_by_event: dict[str, list[str]] = {}
        if event_ids:
            links = session.scalars(
                select(TimelineEvidenceRow).where(
                    TimelineEvidenceRow.timeline_event_id.in_(event_ids)
                )
            ).all()
            for link in links:
                evidence_by_event.setdefault(link.timeline_event_id, []).append(link.evidence_id)
        return [
            TimelineEventOut(
                timeline_event_id=row.timeline_event_id,
                event_time=row.event_time,
                time_precision=row.time_precision.value,
                description=row.description,
                validation_status=row.validation_status.value,
                evidence_ids=evidence_by_event.get(row.timeline_event_id, []),
            )
            for row in rows
        ]


@router.get("/runs/{run_id}/reports", response_model=list[ReportSummaryOut])
def list_run_reports(run_id: str, request: Request) -> list[ReportSummaryOut]:
    sessions = _sessions(request)
    with sessions() as session:
        _get_run_row(session, run_id)
        reports = session.scalars(
            select(ReportRow).where(ReportRow.run_id == run_id).order_by(ReportRow.version.desc())
        ).all()
        report_ids = [report.report_id for report in reports]
        projections: dict[str, ReportProjectionRow] = {}
        if report_ids:
            projection_rows = session.scalars(
                select(ReportProjectionRow).where(ReportProjectionRow.report_id.in_(report_ids))
            ).all()
            projections = {row.report_id: row for row in projection_rows}
        return [_report_summary(report, projections.get(report.report_id)) for report in reports]


@router.post("/runs/{run_id}/reports", response_model=ReportDetailOut, status_code=201)
async def generate_run_report(
    run_id: str, payload: ReportGenerateIn, request: Request
) -> ReportDetailOut:
    sessions = _sessions(request)
    with sessions() as session:
        run = _get_run_row(session, run_id)
        if run.status is not RunStatus.READY_FOR_REPORT:
            raise _error(
                409,
                "RUN_NOT_READY_FOR_REPORT",
                f"run {run_id} status is {run.status.value}; "
                "report generation requires READY_FOR_REPORT",
            )
    pipeline = ReportPipeline(sessions, _repository(request), DeterministicWriter())
    result = await pipeline.generate(
        run_id=run_id, report_type=ReportType(payload.report_type), now=_utcnow()
    )
    with sessions() as session:
        return _report_detail(session, result.report.report_id)


# -- report endpoints ----------------------------------------------------------


@router.get("/reports/{report_id}", response_model=ReportDetailOut)
def get_report(report_id: str, request: Request) -> ReportDetailOut:
    sessions = _sessions(request)
    with sessions() as session:
        return _report_detail(session, report_id)


@router.get("/reports/{report_id}/citations", response_model=list[CitationOut])
def list_report_citations(report_id: str, request: Request) -> list[CitationOut]:
    sessions = _sessions(request)
    with sessions() as session:
        _get_report_row(session, report_id)
        rows = session.scalars(
            select(CitationRow)
            .where(CitationRow.report_id == report_id)
            .order_by(CitationRow.display_ordinal)
        ).all()
        return [_citation_out(row) for row in rows]


@router.get("/reports/{report_id}/review", response_model=ReviewDetailOut)
def get_report_review(report_id: str, request: Request) -> ReviewDetailOut:
    sessions = _sessions(request)
    governance = ReportGovernanceRepository(sessions)
    with sessions() as session:
        _get_report_row(session, report_id)
        projection = governance.get_projection_in_session(session, report_id)
        evaluation = governance.latest_evaluation_in_session(session, report_id)
        findings = governance.findings_for_report_in_session(session, report_id)
        pending = governance.pending_request_for_report_in_session(session, report_id, _utcnow())
        decisions = session.scalars(
            select(ReviewDecisionRow)
            .where(ReviewDecisionRow.report_id == report_id)
            .order_by(ReviewDecisionRow.created_at.desc())
        ).all()
        return ReviewDetailOut(
            report_id=report_id,
            review_status=projection.review_status.value if projection else None,
            release_status=projection.release_status.value if projection else None,
            evaluation=(
                EvaluationOut(
                    evaluation_id=evaluation.evaluation_id,
                    policy_version=evaluation.policy_version,
                    decision=evaluation.decision.value,
                    release_status=evaluation.release_status.value,
                    review_status=evaluation.review_status.value,
                    evaluation_hash=evaluation.evaluation_hash,
                    report_hash=evaluation.report_hash,
                    claim_set_hash=evaluation.claim_set_hash,
                    citation_set_hash=evaluation.citation_set_hash,
                    hard_finding_count=evaluation.hard_finding_count,
                    governance_finding_count=evaluation.governance_finding_count,
                    created_at=evaluation.created_at,
                )
                if evaluation is not None
                else None
            ),
            findings=[
                FindingOut(
                    finding_id=finding.finding_id,
                    validator=finding.validator.value,
                    severity=finding.severity.value,
                    code=finding.code,
                    detail=finding.detail,
                    section_key=finding.section_key,
                    unit_key=finding.unit_key,
                    created_at=finding.created_at,
                )
                for finding in findings
            ],
            pending_request=(
                ReviewRequestOut(
                    request_id=pending.request_id,
                    report_id=pending.report_id,
                    report_version=pending.report_version,
                    policy_version=pending.policy_version,
                    trigger_reason=pending.trigger_reason,
                    report_hash=pending.report_hash,
                    claim_set_hash=pending.claim_set_hash,
                    citation_set_hash=pending.citation_set_hash,
                    evaluation_hash=pending.evaluation_hash,
                    created_at=pending.created_at,
                    expires_at=pending.expires_at,
                )
                if pending is not None
                else None
            ),
            history=[
                ReviewDecisionOut(
                    review_id=decision.review_id,
                    report_id=decision.report_id,
                    reviewer_id=decision.reviewer_id,
                    decision=decision.decision.value,
                    reason=decision.reason,
                    report_version=decision.report_version,
                    report_hash=decision.report_hash,
                    claim_set_hash=decision.claim_set_hash,
                    decision_origin=decision.decision_origin.value,
                    created_at=decision.created_at,
                )
                for decision in decisions
            ],
        )


# -- citation endpoints --------------------------------------------------------


@router.get("/citations/{citation_id}", response_model=CitationDetailOut)
def get_citation(citation_id: str, request: Request) -> CitationDetailOut:
    sessions = _sessions(request)
    with sessions() as session:
        citation = session.get(CitationRow, citation_id)
        if citation is None:
            raise _error(404, "CITATION_NOT_FOUND", f"citation not found: {citation_id}")
        claim_row = session.get(ClaimRow, citation.claim_id)
        evidence_row = session.get(EvidenceRow, citation.evidence_id)

        claim_out: CitationClaimOut | None = None
        if claim_row is not None:
            validation_basis: str | None = None
            if claim_row.latest_validation_id is not None:
                validation = session.get(ValidationResultRow, claim_row.latest_validation_id)
                if validation is not None:
                    validation_basis = validation.validation_basis
            claim_out = CitationClaimOut(
                claim_id=claim_row.claim_id,
                statement=claim_row.statement,
                claim_type=claim_row.claim_type.value,
                validation_status=claim_row.validation_status.value,
                confidence=claim_row.confidence,
                validation_basis=validation_basis,
            )

        evidence_out: CitationEvidenceOut | None = None
        source_out: CitationSourceOut | None = None
        if evidence_row is not None:
            evidence_out = CitationEvidenceOut(
                evidence_id=evidence_row.evidence_id,
                excerpt=_excerpt(evidence_row.content),
                exact_quote=_exact_quote(evidence_row.content, evidence_row.locator_payload),
                locator_type=evidence_row.locator_type.value,
                locator_payload=dict(evidence_row.locator_payload),
            )
            snapshot = session.get(SourceSnapshotRow, evidence_row.snapshot_id)
            if snapshot is not None:
                source = session.get(SourceRow, snapshot.source_id)
                if source is not None:
                    source_out = CitationSourceOut(
                        source_id=source.source_id,
                        title=source.title,
                        publisher=source.publisher,
                        source_type=source.source_type.value,
                        canonical_url=source.canonical_url,
                        published_at=source.published_at,
                        retrieved_at=snapshot.retrieved_at,
                    )
        return CitationDetailOut(
            citation=_citation_out(citation),
            claim=claim_out,
            evidence=evidence_out,
            source=source_out,
        )
