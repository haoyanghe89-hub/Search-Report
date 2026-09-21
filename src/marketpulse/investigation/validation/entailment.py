from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from marketpulse.investigation.domain.claims import Claim
from marketpulse.investigation.domain.sources import Evidence
from marketpulse.investigation.validation.models import SemanticJudgment


class SemanticEntailmentJudge(Protocol):
    """Produces relation judgments only; it cannot assign Claim validation status."""

    def judge(self, *, claim: Claim, evidence: Evidence) -> SemanticJudgment: ...


class DeterministicSemanticJudge:
    """Test/replay judge backed by explicitly supplied, immutable judgments."""

    def __init__(self, judgments: Mapping[tuple[str, str], SemanticJudgment]) -> None:
        self._judgments = dict(judgments)

    def judge(self, *, claim: Claim, evidence: Evidence) -> SemanticJudgment:
        judgment = self._judgments.get((claim.claim_id, evidence.evidence_id))
        if judgment is None:
            raise KeyError(f"missing semantic judgment for {claim.claim_id}/{evidence.evidence_id}")
        if judgment.run_id != claim.run_id:
            raise ValueError("semantic judgment and Claim belong to different Runs")
        return judgment


def replayed_judgment(
    judgment: SemanticJudgment,
    *,
    recorded_judgment_ref: str,
    replayed_at: datetime | None = None,
) -> SemanticJudgment:
    """Copies a recorded semantic input without carrying any policy status."""

    return judgment.model_copy(
        update={
            "recorded_judgment_ref": recorded_judgment_ref,
            "created_at": replayed_at or datetime.now(UTC),
        }
    )
