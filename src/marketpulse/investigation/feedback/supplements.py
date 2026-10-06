import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from marketpulse.investigation.agents.contracts import QualifierSupplement
from marketpulse.investigation.agents.supplements import supplemented_qualifiers
from marketpulse.investigation.domain.claims import Claim
from marketpulse.investigation.domain.enums import AuditActorType
from marketpulse.investigation.domain.reports import AuditEvent
from marketpulse.investigation.feedback.guards import stable_id
from marketpulse.investigation.persistence.models import ClaimRow
from marketpulse.investigation.persistence.repositories import InvestigationRepository


@dataclass(frozen=True)
class PersistQualifierSupplementsOperation:
    claim: Claim
    supplements: tuple[QualifierSupplement, ...]
    evidence_ids: dict[str, str]
    created_at: datetime

    def apply(self, session: Session, repository: InvestigationRepository) -> None:
        row = session.get(ClaimRow, self.claim.claim_id)
        if row is None or row.qualifiers != self.claim.qualifiers:
            raise ValueError("qualifier supplementation projection changed concurrently")
        row.qualifiers = supplemented_qualifiers(self.claim.qualifiers, self.supplements)
        repository.add_in_session(
            session,
            AuditEvent(
                audit_event_id=stable_id(
                    "QUAL-AUDIT",
                    self.claim.claim_id,
                    json.dumps([s.model_dump() for s in self.supplements], sort_keys=True),
                ),
                investigation_id=self.claim.investigation_id,
                run_id=self.claim.run_id,
                actor_type=AuditActorType.SYSTEM,
                event_type="CLAIM_QUALIFIERS_SUPPLEMENTED",
                target_type="CLAIM",
                target_id=self.claim.claim_id,
                reason="Explicit verbatim supporting Evidence, integrity checked before validation",
                metadata={
                    "previous_qualifiers": self.claim.qualifiers,
                    "qualifiers": row.qualifiers,
                    "supplements": [
                        {
                            **s.model_dump(mode="json"),
                            "evidence_id": self.evidence_ids[s.evidence_key],
                        }
                        for s in self.supplements
                    ],
                },
                created_at=self.created_at,
            ),
        )
