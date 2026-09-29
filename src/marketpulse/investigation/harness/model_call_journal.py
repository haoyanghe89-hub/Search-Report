"""Durable model dispatch intents using the existing audit log, without a new table."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.investigation.domain.enums import AuditActorType, ExternalCallStatus
from marketpulse.investigation.domain.reports import AuditEvent
from marketpulse.investigation.persistence.models import (
    AuditEventRow,
    InvestigationRunRow,
    RecordedModelCallRow,
)
from marketpulse.investigation.recording.errors import ExternalCallError


class ModelCallOutcomeUnknownError(ExternalCallError):
    code = "MODEL_CALL_OUTCOME_UNKNOWN"

    def __init__(self, intent_id: str) -> None:
        self.intent_id = intent_id
        super().__init__(
            f"{self.code}: {intent_id}; provider execution/charges may have occurred. "
            "Reconcile with the provider or explicitly authorize retry_unknown_outcome; "
            "a retry consumes another call budget and may incur duplicate charges."
        )


def prepare_model_intent(
    sessions: sessionmaker[Session],
    *,
    run_id: str,
    logical_step_key: str,
    call_site_key: str,
    call_ordinal: int,
    fingerprint: str,
    next_record_attempt: int,
    retry_unknown_outcome: bool,
) -> tuple[AuditEvent, int]:
    """Prepare intent; caller MUST commit it with budget reservation before dispatch.

    Intent IDs are deterministic for each site/attempt, so concurrent contenders
    cannot both commit the same dispatch. The harness also owns the step lease.
    """
    identity = json.dumps([run_id, logical_step_key, call_site_key, call_ordinal])
    target_id = "MODEL-SITE-" + hashlib.sha256(identity.encode()).hexdigest()
    with sessions() as session:
        run = session.get(InvestigationRunRow, run_id)
        if run is None:
            raise ValueError(f"run does not exist: {run_id}")
        intents = session.scalars(
            select(AuditEventRow).where(
                AuditEventRow.target_id == target_id,
                AuditEventRow.event_type == "MODEL_CALL_INTENT",
            )
        ).all()
        previous = max(intents, key=lambda row: int(row.metadata_payload["sequence"]), default=None)
        unknown_intent: str | None = None
        if previous is not None:
            metadata = previous.metadata_payload
            records = session.scalars(
                select(RecordedModelCallRow).where(
                    RecordedModelCallRow.run_id == run_id,
                    RecordedModelCallRow.request_fingerprint == metadata["request_fingerprint"],
                    RecordedModelCallRow.attempt == metadata["record_attempt"],
                )
            ).all()
            terminal = next(
                (
                    row
                    for row in records
                    if row.metadata_payload.get("logical_step_key") == logical_step_key
                    and row.metadata_payload.get("call_site_key") == call_site_key
                    and row.metadata_payload.get("call_ordinal") == call_ordinal
                ),
                None,
            )
            # A timeout, cancellation or transport/provider error does not establish
            # whether the provider completed and billed the request.
            if terminal is None or terminal.status in {
                ExternalCallStatus.TIMEOUT,
                ExternalCallStatus.CANCELLED,
                ExternalCallStatus.PROVIDER_ERROR,
            }:
                unknown_intent = previous.audit_event_id
                if not retry_unknown_outcome:
                    raise ModelCallOutcomeUnknownError(unknown_intent)
        sequence = int(previous.metadata_payload["sequence"]) + 1 if previous else 1
        prior_attempts = [
            int(row.metadata_payload["record_attempt"])
            for row in intents
            if row.metadata_payload["request_fingerprint"] == fingerprint
        ]
        attempt = max(next_record_attempt, max(prior_attempts, default=0) + 1)
        intent = AuditEvent(
            audit_event_id="MODEL-INTENT-"
            + hashlib.sha256(f"{target_id}:{sequence}".encode()).hexdigest(),
            investigation_id=run.investigation_id,
            run_id=run_id,
            actor_type=AuditActorType.SYSTEM,
            event_type="MODEL_CALL_INTENT",
            target_type="MODEL_CALL_SITE",
            target_id=target_id,
            new_state="OUTCOME_PENDING",
            reason="Dispatch reserved; an absent terminal recording means outcome unknown.",
            metadata={
                "logical_step_key": logical_step_key,
                "call_site_key": call_site_key,
                "call_ordinal": call_ordinal,
                "request_fingerprint": fingerprint,
                "record_attempt": attempt,
                "sequence": sequence,
                "retry_of_unknown_intent": unknown_intent,
                "retry_policy": (
                    "ALLOW_POSSIBLE_DUPLICATE_CHARGE" if unknown_intent else "BLOCK_UNKNOWN"
                ),
            },
            created_at=datetime.now(UTC),
        )
    return intent, attempt
