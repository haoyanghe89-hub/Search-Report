from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import DatabaseError, IntegrityError

from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.investigation.domain.claims import (
    Claim,
    ClaimEvidenceRelation,
    ConflictSet,
)
from marketpulse.investigation.domain.enums import (
    AgentRole,
    ArtifactType,
    ClaimImportance,
    ClaimType,
    ConflictResolutionStatus,
    ConflictSeverity,
    ConflictStatus,
    ConflictType,
    EntailmentStatus,
    ParseStatus,
    RelationStance,
    ResearchTaskStatus,
    RunMode,
    RunStatus,
    SemanticJudgmentStatus,
    SourceType,
    StepType,
    ValidationStatus,
    WorkflowPhase,
)
from marketpulse.investigation.domain.runtime import (
    Investigation,
    InvestigationRun,
    InvestigationScope,
    ResearchTask,
    RunBudget,
)
from marketpulse.investigation.domain.sources import (
    DocumentArtifact,
    Evidence,
    Source,
    SourceSnapshot,
)
from marketpulse.investigation.feedback.store import ReserveSourcesOperation
from marketpulse.investigation.harness.persistence import HarnessStore
from marketpulse.investigation.harness.state_machine import Route
from marketpulse.investigation.ingestion.locators import make_text_locator
from marketpulse.investigation.persistence.base import (
    create_investigation_engine,
    create_session_factory,
)
from marketpulse.investigation.persistence.models import (
    SourceFamilyMemberRow,
    SourceSnapshotRow,
)
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.validation import (
    EvidenceIntegrityValidator,
    RecognizedArtifactVersions,
    SemanticJudgment,
    ValidationPersistence,
    ValidationPolicy,
    ValidationRequest,
)


class _MemoryBlobs:
    def __init__(self, ref: BlobRef, content: bytes) -> None:
        self._ref = ref
        self._content = content

    def exists(self, ref: BlobRef) -> bool:
        return ref == self._ref

    def verify_hash(self, ref: BlobRef) -> bool:
        return ref == self._ref and hashlib.sha256(self._content).hexdigest() == ref.sha256

    def get_bytes(self, ref: BlobRef) -> bytes:
        if not self.exists(ref):
            raise KeyError(ref)
        return self._content


def _database_url() -> str:
    url = os.getenv("MARKETPULSE_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set MARKETPULSE_TEST_POSTGRES_URL to a dedicated test database")
    return url


def _config(url: str) -> Config:
    root = Path(__file__).resolve().parents[3]
    config = Config(root / "alembic.ini")
    config.attributes["database_url"] = url
    return config


@pytest.mark.infrastructure
def test_postgres_investigation_contract_and_migration_cycle() -> None:
    url = _database_url()
    config = _config(url)
    command.upgrade(config, "head")
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    raw = f"postgres-{suffix}".encode()
    digest = hashlib.sha256(raw).hexdigest()
    engine = create_investigation_engine(url)
    repository = InvestigationRepository(create_session_factory(engine))
    investigation_id = f"I-{suffix}"
    run_id = f"RUN-{suffix}"
    source_id = f"S-{suffix}"
    snapshot_id = f"SS-{suffix}"
    try:
        repository.add(
            Investigation(
                investigation_id=investigation_id,
                title="PostgreSQL contract",
                event_description="Integration verification",
                investigation_goal="Validate real PostgreSQL behavior",
                scope=InvestigationScope(
                    summary="PostgreSQL",
                    inclusions=("JSONB", "foreign keys", "append-only triggers"),
                ),
                created_at=now,
                updated_at=now,
            )
        )
        repository.add(
            InvestigationRun(
                run_id=run_id,
                investigation_id=investigation_id,
                mode=RunMode.LIVE,
                status=RunStatus.RUNNING,
                current_phase=WorkflowPhase.COLLECT,
                checkpoint_version=0,
                state_version=0,
                workflow_version="postgres-v1",
                created_at=now,
                updated_at=now,
            )
        )
        repository.add(
            Source(
                source_id=source_id,
                investigation_id=investigation_id,
                canonical_url=f"https://example.test/{suffix}",
                title="PostgreSQL source",
                source_type=SourceType.OFFICIAL_REPORT,
                is_official=True,
                is_first_hand=True,
                discovered_at=now,
            )
        )
        repository.add(
            SourceSnapshot(
                snapshot_id=snapshot_id,
                source_id=source_id,
                run_id=run_id,
                retrieved_at=now,
                raw_blob_ref=BlobRef(digest),
                raw_sha256=digest,
                cleaned_blob_ref=BlobRef(digest),
                cleaned_sha256=digest,
                mime_type="text/plain",
                encoding="utf-8",
                content_size=len(raw),
                http_status=200,
                parse_status=ParseStatus.PARSED,
                parser_name="fixture",
                parser_version="1",
                normalizer_version="1",
                evidence_eligible=True,
                provenance={"test": "postgresql", "nested": {"jsonb": True}},
            )
        )

        sessions = create_session_factory(engine)
        store = HarnessStore(sessions, repository)
        store.install_budget(
            RunBudget(
                run_id=run_id,
                max_research_rounds=2,
                max_search_calls=3,
                max_fetch_calls=3,
                max_model_calls=3,
                max_tokens=100,
                max_wall_time_ms=10_000,
                max_sources=2,
                updated_at=now,
            )
        )
        step = store.begin_step(
            run_id=run_id,
            logical_step_key="research:postgres:round-1",
            input_fingerprint=digest,
            workflow_version="postgres-v1",
            phase=WorkflowPhase.COLLECT,
            step_type=StepType.RESEARCH,
            agent_role=AgentRole.RESEARCHER,
            owner_instance_id="postgres-ci",
            research_round=1,
        )
        task = ResearchTask(
            task_id=f"T-{suffix}",
            investigation_id=investigation_id,
            run_id=run_id,
            title="PostgreSQL follow-up",
            objective="Verify Phase 4.3 task persistence",
            purpose="Exercise typed feedback-loop persistence",
            status=ResearchTaskStatus.PENDING,
            priority=90,
            preferred_source_types=(SourceType.OFFICIAL_REPORT,),
            suggested_queries=("official PostgreSQL fixture",),
            round=1,
            created_at=now,
            updated_at=now,
        )
        store.complete_step(
            step_id=step.step_id,
            owner_instance_id="postgres-ci",
            elapsed_ms=20,
            output_refs=(),
            output_schema_version="ResearchProposal",
            business_outputs=(task,),
            transaction_operations=(
                ReserveSourcesOperation(run_id=run_id, count=1, updated_at=now),
            ),
            route=Route.ANALYZE,
        )
        budget = repository.get(RunBudget, run_id)
        assert budget.consumed_wall_time_ms == 20
        assert budget.sources_used == 1
        stored_task = repository.get(ResearchTask, task.task_id)
        assert stored_task.purpose == "Exercise typed feedback-loop persistence"
        assert stored_task.preferred_source_types == (SourceType.OFFICIAL_REPORT,)
        assert stored_task.suggested_queries == ("official PostgreSQL fixture",)
        assert repository.get(InvestigationRun, run_id).last_completed_step_key == (
            "research:postgres:round-1"
        )
        assert {"inv_run_budgets", "inv_call_bindings"} <= set(inspect(engine).get_table_names())
        postgres_inspector = inspect(engine)
        assert {"max_sources", "sources_used"} <= {
            item["name"] for item in postgres_inspector.get_columns("inv_run_budgets")
        }
        assert {
            "target_claim_id",
            "origin_gap_id",
            "parent_task_id",
            "preferred_source_types",
            "suggested_queries",
            "round",
        } <= {item["name"] for item in postgres_inspector.get_columns("inv_research_tasks")}
        assert {"created_by_step_id", "research_task_id"} <= {
            item["name"] for item in postgres_inspector.get_columns("inv_evidence")
        }
        assert {"created_by_step_id", "research_task_id"} <= {
            item["name"] for item in postgres_inspector.get_columns("inv_claims")
        }
        assert "origin_validation_id" in {
            item["name"] for item in postgres_inspector.get_columns("inv_research_gaps")
        }
        assert {
            "inv_claims",
            "inv_research_gaps",
            "inv_research_tasks",
        } <= {
            item["referred_table"]
            for item in postgres_inspector.get_foreign_keys("inv_research_tasks")
        }

        source = repository.get(Source, source_id)
        snapshot = repository.get(SourceSnapshot, snapshot_id)
        artifact = DocumentArtifact(
            artifact_id=f"A-{suffix}",
            snapshot_id=snapshot_id,
            artifact_type=ArtifactType.PLAIN_TEXT,
            blob_ref=BlobRef(digest),
            sha256=digest,
            processor_name="fixture",
            processor_version="1",
            created_at=now,
        )
        evidence = Evidence(
            evidence_id=f"E-{suffix}",
            run_id=run_id,
            snapshot_id=snapshot_id,
            artifact_id=artifact.artifact_id,
            content=raw.decode(),
            content_hash=digest,
            locator=make_text_locator(raw.decode(), 0, len(raw.decode())),
            extracted_at=now,
            extractor_name="fixture",
            extractor_version="1",
            created_by_step_id=step.step_id,
            research_task_id=task.task_id,
        )
        claim = Claim(
            claim_id=f"C-{suffix}",
            investigation_id=investigation_id,
            run_id=run_id,
            statement="Official source stated the PostgreSQL fixture value",
            claim_type=ClaimType.STATEMENT,
            importance=ClaimImportance.HIGH,
            created_by_step_id=step.step_id,
            research_task_id=task.task_id,
            created_at=now,
            updated_at=now,
        )
        relation = ClaimEvidenceRelation(
            relation_id=f"REL-{suffix}",
            claim_id=claim.claim_id,
            evidence_id=evidence.evidence_id,
            stance=RelationStance.SUPPORTS,
            entailment_status=EntailmentStatus.PENDING,
            created_at=now,
        )
        repository.add(artifact)
        repository.add(evidence)
        repository.add(claim)
        repository.add(relation)
        assert repository.get(Evidence, evidence.evidence_id).research_task_id == task.task_id
        assert repository.get(Claim, claim.claim_id).created_by_step_id == step.step_id
        judgment = SemanticJudgment(
            judgment_id=f"SJ-{suffix}",
            run_id=run_id,
            claim_id=claim.claim_id,
            evidence_id=evidence.evidence_id,
            judgment=SemanticJudgmentStatus.ENTAILS,
            reason="exact PostgreSQL fixture statement",
            semantic_confidence=0.95,
            recorded_judgment_ref=f"REC-{suffix}",
            created_at=now,
        )
        conflict = ConflictSet(
            conflict_id=f"CF-{suffix}",
            investigation_id=investigation_id,
            run_id=run_id,
            claim_ids=(claim.claim_id,),
            evidence_ids=(evidence.evidence_id,),
            conflict_type=ConflictType.SCOPE,
            severity=ConflictSeverity.LOW,
            status=ConflictStatus.RESOLVED,
            resolution_status=ConflictResolutionStatus.RESOLVED_WITH_SCOPE,
            resolution_basis="fixture scope is explicit",
            created_at=now,
            updated_at=now,
        )
        validation_request = ValidationRequest(
            validation_id=f"V-{suffix}",
            created_at=now,
            claim=claim,
            relations=(relation,),
            evidence=(evidence,),
            snapshots=(snapshot,),
            artifacts=(artifact,),
            sources=(source,),
            semantic_judgments=(judgment,),
            existing_conflicts=(conflict,),
        )
        validation_policy = ValidationPolicy(
            integrity=EvidenceIntegrityValidator(
                blobs=_MemoryBlobs(BlobRef(digest), raw),  # type: ignore[arg-type]
                recognized_versions=RecognizedArtifactVersions(
                    snapshot_parsers=frozenset({("fixture", "1", "1")}),
                    artifact_processors=frozenset({("fixture", "1")}),
                ),
            )
        )
        validation_outcome = validation_policy.validate(validation_request)
        assert validation_outcome.result.status is ValidationStatus.VERIFIED
        validation_store = ValidationPersistence(sessions, repository)
        validation_store.persist(
            request=validation_request,
            outcome=validation_outcome,
        )
        validation_store.assert_latest_projection_consistent(claim.claim_id)
        assert repository.get(Claim, claim.claim_id).latest_validation_id == (
            validation_request.validation_id
        )

        loaded = repository.get(SourceSnapshot, snapshot_id)
        assert loaded.provenance["nested"] == {"jsonb": True}
        inspector = inspect(engine)
        index_names = {item["name"] for item in inspector.get_indexes("inv_recorded_tool_calls")}
        assert "ix_inv_tool_calls_replay_lookup" in index_names
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT pg_typeof(scope)::text FROM inv_investigations "
                        "WHERE investigation_id=:investigation_id"
                    ),
                    {"investigation_id": investigation_id},
                )
                == "jsonb"
            )

        with pytest.raises(DatabaseError, match="append-only"):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE inv_source_snapshots SET parser_version='2' "
                        "WHERE snapshot_id=:snapshot_id"
                    ),
                    {"snapshot_id": snapshot_id},
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    SourceSnapshotRow.__table__.insert().values(
                        snapshot_id=f"BAD-{suffix}",
                        source_id="missing-source",
                        run_id=run_id,
                        retrieved_at=now,
                        raw_blob_ref=f"blob://sha256/{digest}",
                        raw_sha256=digest,
                        mime_type="text/plain",
                        content_size=1,
                        parse_status=ParseStatus.PARSED,
                        parser_name="fixture",
                        parser_version="1",
                        normalizer_version="1",
                        evidence_eligible=False,
                        provenance={},
                    )
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE inv_runs SET status='NOT_A_STATUS' WHERE run_id=:run_id"),
                    {"run_id": run_id},
                )
        validation_indexes = {
            item["name"] for item in inspector.get_indexes("inv_validation_results")
        }
        assert {
            "ix_inv_validation_input_fingerprint",
            "ix_inv_validation_evidence_set_hash",
            "ix_inv_validation_policy",
        } <= validation_indexes
        assert {
            "inv_semantic_judgments",
            "inv_source_families",
            "inv_source_family_members",
            "inv_conflict_evidence",
            "inv_validation_conflicts",
        } <= set(inspector.get_table_names())
        assert {
            "inv_report_input_snapshots",
            "inv_report_projections",
            "inv_citations",
            "inv_report_validation_findings",
            "inv_release_policy_evaluations",
            "inv_review_requests",
            "inv_reviewer_sessions",
            "inv_reviewer_auth_state",
            "inv_reviewer_rate_buckets",
            "inv_review_research_requests",
            "inv_review_idempotency",
            "inv_recorded_human_review_decisions",
        } <= set(inspector.get_table_names())
        report_columns = {item["name"] for item in inspector.get_columns("inv_reports")}
        assert {
            "report_input_snapshot_hash",
            "citation_set_hash",
            "schema_version",
        } <= report_columns
        assert not {"review_status", "release_status", "updated_at"} & report_columns
        assert {"origin_run_id", "origin_review_request_id"} <= {
            item["name"] for item in inspector.get_columns("inv_runs")
        }
        assert {
            "review_request_id",
            "reviewer_session_public_id",
            "reviewer_config_fingerprint",
            "decision_origin",
        } <= {item["name"] for item in inspector.get_columns("inv_review_decisions")}
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO inv_report_input_snapshots ("
                    "snapshot_id, investigation_id, run_id, run_mode, snapshot_hash, "
                    "claim_set_hash, source_state_fingerprint, semantic_payload, "
                    "runtime_references, assembled_at) VALUES ("
                    ":snapshot_id, :investigation_id, :run_id, 'LIVE', :snapshot_hash, "
                    ":claim_set_hash, :fingerprint, '{}'::jsonb, '{}'::jsonb, :assembled_at)"
                ),
                {
                    "snapshot_id": f"SNAP-{suffix}",
                    "investigation_id": investigation_id,
                    "run_id": run_id,
                    "snapshot_hash": hashlib.sha256(f"snap-{suffix}".encode()).hexdigest(),
                    "claim_set_hash": hashlib.sha256(f"claims-{suffix}".encode()).hexdigest(),
                    "fingerprint": hashlib.sha256(f"sources-{suffix}".encode()).hexdigest(),
                    "assembled_at": now,
                },
            )
        with pytest.raises(DatabaseError, match="append-only"):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE inv_report_input_snapshots SET claim_set_hash='x' "
                        "WHERE snapshot_id=:snapshot_id"
                    ),
                    {"snapshot_id": f"SNAP-{suffix}"},
                )
        with pytest.raises(DatabaseError, match="append-only"):
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM inv_report_input_snapshots WHERE snapshot_id=:snapshot_id"),
                    {"snapshot_id": f"SNAP-{suffix}"},
                )
        with pytest.raises(DatabaseError, match="append-only"):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE inv_validation_results SET policy_version='changed' "
                        "WHERE validation_id=:validation_id"
                    ),
                    {"validation_id": validation_request.validation_id},
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    SourceFamilyMemberRow.__table__.insert().values(
                        family_record_id="missing-family",
                        source_id=source_id,
                    )
                )
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    smoke_engine = create_investigation_engine(url)
    try:
        assert "inv_investigations" not in inspect(smoke_engine).get_table_names()
    finally:
        smoke_engine.dispose()
    command.upgrade(config, "head")
    command.check(config)
