"""Immutable semantic inputs for resumable workflow steps, stored in the audit log."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TypeVar

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.infrastructure.storage.ports import BlobStoragePort
from marketpulse.investigation.domain.enums import AuditActorType
from marketpulse.investigation.domain.reports import AuditEvent
from marketpulse.investigation.domain.runtime import InvestigationRun
from marketpulse.investigation.harness.persistence import ResumeVersionMismatchError
from marketpulse.investigation.persistence.models import AuditEventRow
from marketpulse.investigation.persistence.repositories import InvestigationRepository

RESUMABLE_WORKFLOW_VERSION = "resumable-retrieval-v4"
T = TypeVar("T", bound=BaseModel)


class WorkerCheckpoint(BaseModel):
    workers: int = Field(ge=1)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_saved_input(event: AuditEvent, blobs: BlobStoragePort) -> bytes:
    """Fail closed on missing/corrupt checkpoint metadata or immutable content."""
    metadata = event.metadata
    required = (
        "logical_step_key",
        "workflow_version",
        "schema",
        "schema_hash",
        "input_ref",
        "input_hash",
    )
    if event.event_type != "STEP_INPUT_SAVED" or any(
        not isinstance(metadata.get(key), str) or not metadata[key] for key in required
    ):
        raise ResumeVersionMismatchError("invalid Step input checkpoint metadata")
    ref = BlobRef.from_uri(str(metadata["input_ref"]))
    content = blobs.get_bytes(ref)
    if hashlib.sha256(content).hexdigest() != metadata["input_hash"]:
        raise ResumeVersionMismatchError("Step input checkpoint hash changed")
    from marketpulse.investigation.agents.contracts import (
        AnalysisInput,
        PlanInput,
        ResearchInput,
        RouteInput,
        VerificationInput,
    )
    from marketpulse.investigation.feedback.models import InformationGainSummary, RoundSnapshot

    schemas = (
        InformationGainSummary,
        RoundSnapshot,
        AnalysisInput,
        PlanInput,
        ResearchInput,
        RouteInput,
        VerificationInput,
        WorkerCheckpoint,
    )
    schema = next(
        (
            model
            for model in schemas
            if f"{model.__module__}.{model.__qualname__}" == metadata["schema"]
        ),
        None,
    )
    if schema is None or _digest(schema.model_json_schema()) != metadata["schema_hash"]:
        raise ResumeVersionMismatchError("Step input checkpoint schema changed")
    schema.model_validate_json(content)
    return content


class StepInputCheckpoints:
    def __init__(self, repository: InvestigationRepository, blobs: BlobStoragePort) -> None:
        self.repository = repository
        self.blobs = blobs

    def saved_inputs(
        self,
        sessions: sessionmaker[Session],
        run_id: str,
        model: type[T],
    ) -> dict[str, T]:
        schema = f"{model.__module__}.{model.__qualname__}"
        with sessions() as session:
            events = session.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.run_id == run_id,
                    AuditEventRow.event_type == "STEP_INPUT_SAVED",
                )
            ).all()
            return {
                str(event.metadata_payload["logical_step_key"]): model.model_validate_json(
                    validate_saved_input(
                        self.repository.get_in_session(session, AuditEvent, event.audit_event_id),
                        self.blobs,
                    )
                )
                for event in events
                if event.metadata_payload.get("schema") == schema
            }

    def pinned_input(self, run_id: str, logical_key: str, workflow_version: str, request: T) -> T:
        """Save once before dispatch; retries use the exact original model input.

        Budgets change as calls execute. Reconstructing an input from current state
        would change fingerprints and call batches after an interruption. A stable
        audit ID also makes concurrent first writers converge on the same input.
        """
        identity = "STEP-INPUT-" + _digest([run_id, logical_key])
        schema = f"{type(request).__module__}.{type(request).__qualname__}"
        schema_hash = _digest(type(request).model_json_schema())
        try:
            event = self.repository.get(AuditEvent, identity)
        except KeyError:
            run = self.repository.get(InvestigationRun, run_id)
            content = json.dumps(
                request.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            stored = self.blobs.put_bytes(content)
            event = AuditEvent(
                audit_event_id=identity,
                investigation_id=run.investigation_id,
                run_id=run_id,
                actor_type=AuditActorType.SYSTEM,
                event_type="STEP_INPUT_SAVED",
                target_type="ExecutionStepInput",
                target_id=identity,
                metadata={
                    "logical_step_key": logical_key,
                    "workflow_version": workflow_version,
                    "schema": schema,
                    "schema_hash": schema_hash,
                    "input_ref": stored.ref.uri,
                    "input_hash": hashlib.sha256(content).hexdigest(),
                },
                created_at=datetime.now(UTC),
            )
            try:
                self.repository.add(event)
            except IntegrityError:
                event = self.repository.get(AuditEvent, identity)
        if (
            event.run_id != run_id
            or event.metadata.get("logical_step_key") != logical_key
            or event.metadata.get("workflow_version") != workflow_version
            or event.metadata.get("schema") != schema
            or event.metadata.get("schema_hash") != schema_hash
        ):
            raise ResumeVersionMismatchError("Step input checkpoint version/schema changed")
        return type(request).model_validate_json(validate_saved_input(event, self.blobs))
