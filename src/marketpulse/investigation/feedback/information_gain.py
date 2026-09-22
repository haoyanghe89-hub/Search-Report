from __future__ import annotations

from marketpulse.investigation.domain.enums import (
    ConflictResolutionStatus,
    ConflictStatus,
    ValidationStatus,
)
from marketpulse.investigation.feedback.models import InformationGainSummary, RoundSnapshot
from marketpulse.investigation.feedback.store import FeedbackState, FeedbackStore
from marketpulse.investigation.validation.lineage import SourceLineageResolver


class InformationGainCalculator:
    def __init__(self) -> None:
        self._lineage = SourceLineageResolver()

    def snapshot(self, store: FeedbackStore, state: FeedbackState) -> RoundSnapshot:
        eligible_sources = {item.source_id for item in state.snapshots if item.evidence_eligible}
        eligible = tuple(item for item in state.sources if item.source_id in eligible_sources)
        families = self._lineage.resolve(sources=eligible)
        latest = store.latest_validations(state)
        return RoundSnapshot(
            valid_source_ids=frozenset(eligible_sources),
            family_ids=frozenset(item.family_id for item in families.families),
            evidence_ids=frozenset(item.evidence_id for item in state.evidence),
            claim_ids=frozenset(item.claim_id for item in state.claims),
            open_gap_ids=frozenset(item.gap_id for item in store.open_gaps(state)),
            resolved_conflict_ids=frozenset(
                item.conflict_id
                for item in state.conflicts
                if item.status is ConflictStatus.RESOLVED
                or item.resolution_status is not ConflictResolutionStatus.UNRESOLVED
            ),
            validation_statuses={key: value.status for key, value in latest.items()},
        )

    @staticmethod
    def compare(
        before: RoundSnapshot,
        after: RoundSnapshot,
        *,
        round_number: int,
    ) -> InformationGainSummary:
        changed = tuple(
            sorted(
                claim_id
                for claim_id, status in after.validation_statuses.items()
                if before.validation_statuses.get(claim_id) != status
            )
        )
        improvements = tuple(
            claim_id
            for claim_id in changed
            if InformationGainCalculator._improved(
                before.validation_statuses.get(claim_id),
                after.validation_statuses[claim_id],
            )
        )
        return InformationGainSummary(
            round=round_number,
            new_valid_sources=len(after.valid_source_ids - before.valid_source_ids),
            new_independent_families=len(after.family_ids - before.family_ids),
            new_evidence=len(after.evidence_ids - before.evidence_ids),
            new_claims=len(after.claim_ids - before.claim_ids),
            resolved_gaps=len(before.open_gap_ids - after.open_gap_ids),
            new_gaps=len(after.open_gap_ids - before.open_gap_ids),
            resolved_conflicts=len(after.resolved_conflict_ids - before.resolved_conflict_ids),
            validation_improvements=improvements,
            validation_changes=changed,
        )

    @staticmethod
    def _improved(
        before: ValidationStatus | None,
        after: ValidationStatus,
    ) -> bool:
        if before in {None, ValidationStatus.PENDING, ValidationStatus.UNVERIFIED}:
            return after in {ValidationStatus.PROBABLE, ValidationStatus.VERIFIED}
        return before is ValidationStatus.PROBABLE and after is ValidationStatus.VERIFIED


class NoProgressDetector:
    def __init__(self, threshold: int) -> None:
        if threshold < 1:
            raise ValueError("no-progress threshold must be positive")
        self.threshold = threshold
        self.consecutive = 0

    def observe(self, gain: InformationGainSummary) -> bool:
        self.consecutive = 0 if gain.has_information_gain else self.consecutive + 1
        return self.consecutive >= self.threshold
