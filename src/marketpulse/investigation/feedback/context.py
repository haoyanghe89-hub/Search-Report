from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, cast

from marketpulse.infrastructure.storage.ports import BlobStoragePort
from marketpulse.investigation.agents.contracts import (
    AnalysisInput,
    BudgetView,
    ClaimCandidate,
    CoverageView,
    EvidenceCandidate,
    ExistingClaimView,
    GapView,
    InvestigationSummary,
    PlanInput,
    QuestionView,
    ResearchInput,
    SourceFamilyView,
    SourceStatistics,
    TaskProposal,
    TaskSummaryView,
    ValidatedClaimView,
    VerificationInput,
)
from marketpulse.investigation.domain.claims import (
    Claim,
    ClaimEvidenceRelation,
    ResearchGap,
)
from marketpulse.investigation.domain.enums import (
    GapStatus,
    RelationStance,
    ValidationStatus,
)
from marketpulse.investigation.domain.runtime import ResearchTask
from marketpulse.investigation.feedback.models import FeedbackLoopConfig
from marketpulse.investigation.feedback.selection import ArtifactCandidate, ArtifactSelector
from marketpulse.investigation.feedback.store import FeedbackState, FeedbackStore
from marketpulse.investigation.validation.lineage import SourceLineageResolver


def semantic_key(prefix: str, value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def claim_key(claim: Claim) -> str:
    return semantic_key(
        "CLAIM",
        {
            "statement": " ".join(claim.statement.casefold().split()),
            "claim_type": claim.claim_type.value,
            "qualifiers": claim.qualifiers,
        },
    )


def evidence_key(content_hash: str, artifact_hash: str) -> str:
    return semantic_key("EVID", {"content": content_hash, "artifact": artifact_hash})


def gap_key(gap_type: str, target_claim_key: str | None, reason: str) -> str:
    return semantic_key(
        "GAP",
        {
            "gap_type": gap_type,
            "target_claim": target_claim_key,
            "reason": " ".join(reason.casefold().split()),
        },
    )


@dataclass(frozen=True, slots=True)
class AnalysisContextBundle:
    request: AnalysisInput
    artifact_ids: dict[str, str]
    snapshot_ids: dict[str, str]
    source_ids: dict[str, str]


@dataclass(frozen=True, slots=True)
class VerificationContextBundle:
    request: VerificationInput
    claim_ids: dict[str, str]
    evidence_ids: dict[str, str]


class AgentContextBuilder:
    """Builds deterministic, bounded contexts from persisted investigation objects."""

    def __init__(
        self,
        store: FeedbackStore,
        blobs: BlobStoragePort,
        config: FeedbackLoopConfig,
    ) -> None:
        self.store = store
        self.blobs = blobs
        self.config = config
        self.lineage = SourceLineageResolver()

    def planner(self, state: FeedbackState) -> PlanInput:
        questions = self._questions(state)
        return PlanInput(
            case_key=semantic_key(
                "CASE",
                {
                    "title": state.investigation.title,
                    "goal": state.investigation.investigation_goal,
                },
            ),
            scope_summary=state.investigation.scope.summary,
            investigation_goal=state.investigation.investigation_goal,
            event_description=state.investigation.event_description,
            questions=questions,
            critical_question_keys=tuple(
                item.question_key for item in questions if item.is_critical
            ),
            max_research_rounds=state.budget.max_research_rounds,
            coverage=self.coverage(state),
            unresolved_gaps=self.gaps(state),
            prior_task_summaries=self.task_summaries(state),
            budget=self.budget(state),
        )

    def researcher(self, state: FeedbackState, task: ResearchTask) -> ResearchInput:
        question = next(
            (
                item
                for item in self._questions(state)
                if item.question_key == task.target_question_id
            ),
            None,
        )
        origin = next((gap for gap in state.gaps if gap.gap_id == task.origin_gap_id), None)
        proposal = TaskProposal(
            task_key=task.title,
            target_question_key=(
                task.target_question_id
                or (question.question_key if question is not None else "unknown")
            ),
            target_claim_key=(
                claim_key(
                    next(item for item in state.claims if item.claim_id == task.target_claim_id)
                )
                if task.target_claim_id is not None
                else None
            ),
            origin_gap_key=(self._gap_view(state, origin).gap_key if origin is not None else None),
            objective=task.objective,
            purpose=task.purpose or task.objective,
            priority=task.priority,
            preferred_source_types=task.preferred_source_types,
            suggested_queries=task.suggested_queries,
        )
        gaps = self.gaps(state)
        return ResearchInput(
            task=proposal,
            target_question=question,
            prior_source_hashes=tuple(
                sorted({item.raw_sha256 for item in state.snapshots})[
                    : self.config.max_context_items
                ]
            ),
            open_gap_keys=tuple(item.gap_key for item in gaps),
            remaining_search_calls=self.budget(state).search_calls_remaining,
            coverage=self.coverage(state),
            source_families=self.source_families(state),
            relevant_gaps=tuple(
                item for item in gaps if item.target_question_key in {None, task.target_question_id}
            )[: self.config.max_context_items],
            budget=self.budget(state),
            round=task.round,
        )

    def analyst(
        self,
        state: FeedbackState,
        task: ResearchTask,
        *,
        current_artifact_ids: frozenset[str] = frozenset(),
    ) -> AnalysisContextBundle:
        snapshots = {item.snapshot_id: item for item in state.snapshots}
        sources = {item.source_id: item for item in state.sources}
        candidates: list[ArtifactCandidate] = []
        for artifact in state.artifacts:
            snapshot = snapshots[artifact.snapshot_id]
            source = sources[snapshot.source_id]
            candidates.append(
                ArtifactCandidate(
                    artifact=artifact,
                    snapshot=snapshot,
                    source=source,
                    from_current_task=artifact.artifact_id in current_artifact_ids,
                    relevant_to_question=True,
                    related_to_gap=task.origin_gap_id is not None,
                )
            )
        views = ArtifactSelector(
            self.blobs,
            max_artifacts=self.config.max_artifacts,
            max_excerpts=self.config.max_excerpts,
            max_chars=self.config.max_context_chars,
        ).select(tuple(candidates))
        artifact_by_hash = {item.sha256: item for item in state.artifacts}
        artifact_ids: dict[str, str] = {}
        snapshot_ids: dict[str, str] = {}
        source_ids: dict[str, str] = {}
        for view in views:
            artifact = artifact_by_hash[view.content_hash]
            snapshot = snapshots[artifact.snapshot_id]
            artifact_ids[view.artifact_key] = artifact.artifact_id
            snapshot_ids[view.snapshot_key] = snapshot.snapshot_id
            source_ids[view.source_key] = snapshot.source_id
        question = next(
            (
                QuestionView(
                    question_key=item.question_id,
                    text=item.text,
                    is_critical=item.is_critical,
                )
                for item in state.investigation.questions
                if item.question_id == task.target_question_id
            ),
            None,
        )
        ordered_claims = sorted(
            state.claims,
            key=lambda item: (not item.is_critical, claim_key(item)),
        )[: self.config.max_context_items]
        existing = tuple(
            ExistingClaimView(
                claim_key=claim_key(item),
                statement=item.statement,
                claim_type=item.claim_type,
                qualifiers=item.qualifiers,
                status=item.validation_status,
            )
            for item in ordered_claims
        )
        return AnalysisContextBundle(
            request=AnalysisInput(
                artifacts=views,
                prior_claim_keys=tuple(item.claim_key for item in existing),
                target_question=question,
                existing_claims=existing,
                open_gaps=self.gaps(state),
            ),
            artifact_ids=artifact_ids,
            snapshot_ids=snapshot_ids,
            source_ids=source_ids,
        )

    def verifier(
        self,
        state: FeedbackState,
        *,
        exclude_claim_ids: frozenset[str] = frozenset(),
    ) -> VerificationContextBundle:
        artifacts = {item.artifact_id: item for item in state.artifacts}
        claim_ids: dict[str, str] = {}
        evidence_ids: dict[str, str] = {}
        claims: list[ClaimCandidate] = []
        evidence: list[EvidenceCandidate] = []
        relations_by_claim: dict[str, list[ClaimEvidenceRelation]] = {}
        for relation in state.relations:
            relations_by_claim.setdefault(relation.claim_id, []).append(relation)
        selected_claims = tuple(
            sorted(
                (item for item in state.claims if item.claim_id not in exclude_claim_ids),
                key=lambda item: (not item.is_critical, claim_key(item)),
            )[: self.config.max_verification_claims]
        )
        selected_claim_ids = {item.claim_id for item in selected_claims}
        selected_evidence_ids = {
            relation.evidence_id
            for relation in state.relations
            if relation.claim_id in selected_claim_ids
        }
        selected_evidence = tuple(
            sorted(
                (item for item in state.evidence if item.evidence_id in selected_evidence_ids),
                key=lambda item: evidence_key(
                    item.content_hash,
                    artifacts[item.artifact_id].sha256 if item.artifact_id is not None else "",
                ),
            )[: self.config.max_verification_evidence]
        )
        for evidence_item in selected_evidence:
            if evidence_item.artifact_id is None:
                continue
            artifact = artifacts[evidence_item.artifact_id]
            key = evidence_key(evidence_item.content_hash, artifact.sha256)
            evidence_ids[key] = evidence_item.evidence_id
            evidence.append(
                EvidenceCandidate(
                    evidence_key=key,
                    artifact_key=f"ART-{artifact.sha256[:24]}",
                    quote=evidence_item.content,
                    locator=evidence_item.locator,
                    quote_hash=evidence_item.content_hash,
                )
            )
        reverse_evidence = {value: key for key, value in evidence_ids.items()}
        for claim_item in selected_claims:
            key = claim_key(claim_item)
            claim_ids[key] = claim_item.claim_id
            claim_relations = relations_by_claim.get(claim_item.claim_id, [])
            claims.append(
                ClaimCandidate(
                    claim_key=key,
                    statement=claim_item.statement,
                    canonical_statement=claim_item.statement,
                    claim_type=claim_item.claim_type,
                    supporting_evidence_keys=tuple(
                        sorted(
                            reverse_evidence[relation.evidence_id]
                            for relation in claim_relations
                            if relation.stance is RelationStance.SUPPORTS
                            and relation.evidence_id in reverse_evidence
                        )
                    ),
                    contradicting_evidence_keys=tuple(
                        sorted(
                            reverse_evidence[relation.evidence_id]
                            for relation in claim_relations
                            if relation.stance is RelationStance.CONTRADICTS
                            and relation.evidence_id in reverse_evidence
                        )
                    ),
                    entity_qualifiers=claim_item.qualifiers,
                    importance=claim_item.importance,
                    critical=claim_item.is_critical,
                )
            )
        claims.sort(key=lambda item: item.claim_key)
        evidence.sort(key=lambda item: item.evidence_key)
        return VerificationContextBundle(
            request=VerificationInput(
                claims=tuple(claims),
                evidence=tuple(evidence),
                source_independence_keys=tuple(
                    sorted(
                        set(self.lineage.resolve(sources=state.sources).source_to_family.values())
                    )[: self.config.max_context_items]
                ),
                source_families=self.source_families(state),
                existing_conflict_summaries=tuple(
                    f"{item.conflict_type.value}:{item.status.value}:{item.resolution_status.value}"
                    for item in state.conflicts[: self.config.max_context_items]
                ),
                profile_expectations=(
                    "Evidence locators must resolve to immutable artifacts.",
                    "Semantic judgments are advisory inputs to ValidationPolicy.",
                ),
            ),
            claim_ids=claim_ids,
            evidence_ids=evidence_ids,
        )

    def budget(self, state: FeedbackState) -> BudgetView:
        item = state.budget
        return BudgetView(
            research_rounds_remaining=max(0, item.max_research_rounds - item.research_rounds_used),
            search_calls_remaining=max(0, item.max_search_calls - item.search_calls_used),
            fetch_calls_remaining=max(0, item.max_fetch_calls - item.fetch_calls_used),
            model_calls_remaining=max(0, item.max_model_calls - item.model_calls_used),
            tokens_remaining=max(0, item.max_tokens - item.tokens_used),
            sources_remaining=max(0, item.max_sources - item.sources_used),
            active_time_ms_remaining=max(0, item.max_wall_time_ms - item.consumed_wall_time_ms),
        )

    def coverage(self, state: FeedbackState) -> CoverageView:
        eligible = {item.source_id for item in state.snapshots if item.evidence_eligible}
        valid = [item for item in state.sources if item.source_id in eligible]
        families = self.lineage.resolve(sources=tuple(valid))
        secondary = {
            families.source_to_family[item.source_id]
            for item in valid
            if not item.is_official and not item.is_first_hand
        }
        return CoverageView(
            valid_source_count=len(valid),
            primary_official_count=sum(item.is_official or item.is_first_hand for item in valid),
            independent_secondary_families=len(secondary),
            source_types=tuple(sorted({item.source_type for item in valid}, key=str)),
            family_summaries=tuple(
                f"{item.family_id}: {len(item.member_source_ids)} source(s)"
                for item in families.families
            ),
            failed_or_unreadable_sources=tuple(
                item.reason
                for item in state.gaps
                if item.status is GapStatus.OPEN and item.source_id is not None
            ),
        )

    def gaps(self, state: FeedbackState) -> tuple[GapView, ...]:
        views = (
            self._gap_view(state, item) for item in state.gaps if item.status is GapStatus.OPEN
        )
        return tuple(sorted(views, key=lambda item: (item.gap_type.value, item.gap_key)))[
            : self.config.max_context_items
        ]

    def _gap_view(self, state: FeedbackState, gap: ResearchGap) -> GapView:
        target = next(
            (claim_key(value) for value in state.claims if value.claim_id == gap.target_claim_id),
            None,
        )
        return GapView(
            gap_key=gap_key(gap.gap_type.value, target, gap.reason),
            gap_type=gap.gap_type,
            target_question_key=gap.target_question_id,
            target_claim_key=target,
            reason=gap.reason,
            missing_requirement=gap.missing_requirement,
            suggested_action=gap.suggested_action,
        )

    def source_families(self, state: FeedbackState) -> tuple[SourceFamilyView, ...]:
        result = self.lineage.resolve(sources=state.sources, snapshots=state.snapshots)
        return tuple(
            SourceFamilyView(
                family_key=item.family_id,
                source_keys=item.member_source_ids,
                summary="; ".join(item.independence_basis),
            )
            for item in result.families
        )[: self.config.max_context_items]

    def task_summaries(self, state: FeedbackState) -> tuple[TaskSummaryView, ...]:
        return tuple(
            TaskSummaryView(
                task_key=item.title,
                target_question_key=item.target_question_id,
                purpose=item.purpose or item.objective,
                round=item.round,
                summary=f"{item.status.value}; queries={len(item.query_hints)}",
            )
            for item in sorted(
                state.tasks,
                key=lambda value: (-value.round, -value.priority, value.task_id),
            )
        )[: self.config.max_context_items]

    def summary(self, state: FeedbackState, reason: str) -> InvestigationSummary:
        relations: dict[str, list[str]] = {}
        artifacts = {item.artifact_id: item for item in state.artifacts}
        evidence_keys = {
            item.evidence_id: evidence_key(item.content_hash, artifacts[item.artifact_id].sha256)
            for item in state.evidence
            if item.artifact_id is not None
        }
        for relation in state.relations:
            relations.setdefault(relation.claim_id, []).append(evidence_keys[relation.evidence_id])
        by_status: dict[ValidationStatus, list[ValidatedClaimView]] = {
            status: []
            for status in (
                ValidationStatus.VERIFIED,
                ValidationStatus.PROBABLE,
                ValidationStatus.DISPUTED,
                ValidationStatus.UNVERIFIED,
            )
        }
        for item in state.claims:
            if item.validation_status in by_status:
                by_status[item.validation_status].append(
                    ValidatedClaimView(
                        claim_key=claim_key(item),
                        statement=item.statement,
                        status=cast(Any, item.validation_status),
                        evidence_keys=tuple(relations.get(item.claim_id, ())),
                    )
                )
        coverage = self.coverage(state)
        return InvestigationSummary(
            run_key=semantic_key("RUN", state.run.run_id),
            termination_reason=reason,
            verified_claims=tuple(by_status[ValidationStatus.VERIFIED]),
            probable_claims=tuple(by_status[ValidationStatus.PROBABLE]),
            disputed_claims=tuple(by_status[ValidationStatus.DISPUTED]),
            unverified_claims=tuple(by_status[ValidationStatus.UNVERIFIED]),
            timeline_event_keys=tuple(item.timeline_event_id for item in state.timeline_events),
            conflict_keys=tuple(item.conflict_id for item in state.conflicts),
            research_gap_keys=tuple(item.gap_id for item in self.store.open_gaps(state)),
            source_statistics=SourceStatistics(
                valid_sources=coverage.valid_source_count,
                primary_official_sources=coverage.primary_official_count,
                independent_families=len(self.source_families(state)),
                source_types=coverage.source_types,
            ),
            limitations=tuple(item.reason for item in self.store.open_gaps(state)),
            trace_refs=(state.run.run_id,),
        )

    def _questions(self, state: FeedbackState) -> tuple[QuestionView, ...]:
        return tuple(
            QuestionView(
                question_key=item.question_id,
                text=item.text,
                is_critical=item.is_critical,
            )
            for item in sorted(
                state.investigation.questions,
                key=lambda value: (not value.is_critical, value.question_id),
            )
        )[: self.config.max_context_items]
