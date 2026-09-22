"""Phase 5 report governance persistence.

Evolves ``inv_reports`` into an append-only report version table (lifecycle
status moves to the controlled-mutable ``inv_report_projections``), adds the
immutable report-input snapshot, citation, finding, evaluation, review-request,
reviewer-session, and replay-record tables, and installs append-only guards.

Revision ID: 20260922_06
Revises: 20260922_05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = "20260922_06"
down_revision: str | None = "20260922_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")

ZERO_HASH = "0" * 64

NEW_IMMUTABLE_TABLES = (
    "inv_report_input_snapshots",
    "inv_reports",
    "inv_report_sections",
    "inv_report_section_claims",
    "inv_citations",
    "inv_report_validation_findings",
    "inv_release_policy_evaluations",
    "inv_review_requests",
    "inv_review_research_requests",
    "inv_recorded_human_review_decisions",
)

REPORT_TYPE_VALUES = ("FULL_INVESTIGATION", "RESTRICTED_INVESTIGATION", "INVESTIGATION_STATUS")
REVIEW_STATUS_VALUES = ("NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED", "CHANGES_REQUESTED")
RELEASE_STATUS_VALUES = ("DRAFT", "RESTRICTED", "REVIEW_REQUIRED", "PUBLISHED")
REVIEW_DECISION_VALUES = ("APPROVE", "REJECT", "REQUEST_MORE_RESEARCH")
DECISION_ORIGIN_VALUES = ("LIVE", "REPLAY")
VALIDATOR_KIND_VALUES = ("CITATION", "REPORT")
FINDING_SEVERITY_VALUES = ("HARD", "GOVERNANCE")
RELEASE_DECISION_VALUES = ("BLOCK", "PUBLISH", "RESTRICT", "REQUIRE_REVIEW")
RUN_MODE_VALUES = ("LIVE", "REPLAY")


def _enum(values: tuple[str, ...], name: str) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=max(len(value) for value in values),
    )


def _create_immutable_guards(tables: tuple[str, ...]) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in tables:
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION inv_reject_immutable_mutation()"
            )
    elif dialect == "sqlite":
        for table in tables:
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable_update BEFORE UPDATE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'investigation record is append-only'); END"
            )
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'investigation record is append-only'); END"
            )


def _drop_immutable_guards(tables: tuple[str, ...]) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in tables:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    elif dialect == "sqlite":
        for table in tables:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable_update")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable_delete")


def upgrade() -> None:
    op.create_table(
        "inv_report_input_snapshots",
        sa.Column("snapshot_id", sa.String(length=128), nullable=False),
        sa.Column("investigation_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("run_mode", _enum(RUN_MODE_VALUES, "inv_run_mode"), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("claim_set_hash", sa.String(length=64), nullable=False),
        sa.Column("source_state_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("semantic_payload", JSON_DOCUMENT, nullable=False),
        sa.Column("runtime_references", JSON_DOCUMENT, nullable=False),
        sa.Column("assembled_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_inv_ris_snapshot_hash"),
        sa.CheckConstraint("length(claim_set_hash) = 64", name="ck_inv_ris_claim_set_hash"),
        sa.CheckConstraint(
            "length(source_state_fingerprint) = 64", name="ck_inv_ris_source_fingerprint"
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"], ["inv_investigations.investigation_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["inv_runs.run_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("snapshot_id"),
        sa.UniqueConstraint("snapshot_hash", name="uq_inv_ris_snapshot_hash"),
    )
    op.create_index("ix_inv_ris_run", "inv_report_input_snapshots", ["run_id"])
    op.create_index("ix_inv_ris_claim_set_hash", "inv_report_input_snapshots", ["claim_set_hash"])

    # Evolve inv_reports into an append-only report version table.
    with op.batch_alter_table("inv_reports") as batch:
        batch.drop_index("ix_inv_reports_run_release")
        batch.drop_constraint("inv_report_review_status", type_="check")
        batch.drop_constraint("inv_report_release_status", type_="check")
        batch.drop_column("review_status")
        batch.drop_column("release_status")
        batch.drop_column("updated_at")
        batch.add_column(
            sa.Column(
                "report_input_snapshot_hash",
                sa.String(length=64),
                nullable=False,
                server_default=ZERO_HASH,
            )
        )
        batch.add_column(
            sa.Column(
                "citation_set_hash",
                sa.String(length=64),
                nullable=False,
                server_default=ZERO_HASH,
            )
        )
        batch.add_column(
            sa.Column(
                "schema_version",
                sa.String(length=100),
                nullable=False,
                server_default="phase5-report-v1",
            )
        )
        batch.create_check_constraint(
            "ck_inv_report_citation_set_hash", "length(citation_set_hash) = 64"
        )
        batch.create_index("ix_inv_reports_run", ["run_id"])
        batch.create_index("ix_inv_reports_snapshot_hash", ["report_input_snapshot_hash"])

    op.create_table(
        "inv_report_projections",
        sa.Column("report_id", sa.String(length=128), nullable=False),
        sa.Column("investigation_id", sa.String(length=128), nullable=False),
        sa.Column(
            "review_status", _enum(REVIEW_STATUS_VALUES, "inv_report_review_status"), nullable=False
        ),
        sa.Column(
            "release_status",
            _enum(RELEASE_STATUS_VALUES, "inv_report_release_status"),
            nullable=False,
        ),
        sa.Column("active_review_request_id", sa.String(length=128), nullable=True),
        sa.Column("latest_evaluation_id", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["inv_reports.report_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["investigation_id"], ["inv_investigations.investigation_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("report_id"),
    )

    op.create_table(
        "inv_citations",
        sa.Column("citation_id", sa.String(length=128), nullable=False),
        sa.Column("report_id", sa.String(length=128), nullable=False),
        sa.Column("display_ordinal", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.String(length=128), nullable=False),
        sa.Column("evidence_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("report_input_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("claim_set_hash", sa.String(length=64), nullable=False),
        sa.Column("section_key", sa.String(length=100), nullable=False),
        sa.Column("unit_key", sa.String(length=200), nullable=False),
        sa.Column("claim_semantic_hash", sa.String(length=64), nullable=False),
        sa.Column("validation_semantic_hash", sa.String(length=64), nullable=False),
        sa.Column("relation_semantics", sa.String(length=200), nullable=False),
        sa.Column("evidence_semantic_hash", sa.String(length=64), nullable=False),
        sa.Column("canonical_locator", JSON_DOCUMENT, nullable=False),
        sa.Column("resolved_quote_hash", sa.String(length=64), nullable=False),
        sa.Column("artifact_content_hash", sa.String(length=64), nullable=False),
        sa.Column("snapshot_content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_semantic_identity", sa.String(length=500), nullable=False),
        sa.Column("entailment_judgment", sa.String(length=100), nullable=False),
        sa.Column("entailment_version", sa.String(length=100), nullable=False),
        sa.Column("schema_version", sa.String(length=100), nullable=False),
        sa.Column("citation_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint("display_ordinal >= 0", name="ck_inv_citations_ordinal"),
        sa.CheckConstraint("length(citation_hash) = 64", name="ck_inv_citations_hash"),
        sa.ForeignKeyConstraint(["report_id"], ["inv_reports.report_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["inv_claims.claim_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["evidence_id"], ["inv_evidence.evidence_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("citation_id"),
        sa.UniqueConstraint("report_id", "citation_hash", name="uq_inv_citations_report_hash"),
    )
    op.create_index("ix_inv_citations_hash", "inv_citations", ["citation_hash"])
    op.create_index(
        "ix_inv_citations_report_section", "inv_citations", ["report_id", "section_key"]
    )
    op.create_index("ix_inv_citations_claim", "inv_citations", ["claim_id"])
    op.create_index("ix_inv_citations_evidence", "inv_citations", ["evidence_id"])

    op.create_table(
        "inv_report_validation_findings",
        sa.Column("finding_id", sa.String(length=128), nullable=False),
        sa.Column("report_id", sa.String(length=128), nullable=False),
        sa.Column(
            "validator", _enum(VALIDATOR_KIND_VALUES, "inv_report_validator_kind"), nullable=False
        ),
        sa.Column(
            "severity", _enum(FINDING_SEVERITY_VALUES, "inv_finding_severity"), nullable=False
        ),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("section_key", sa.String(length=100), nullable=True),
        sa.Column("unit_key", sa.String(length=200), nullable=True),
        sa.Column("claim_stable_key", sa.String(length=200), nullable=True),
        sa.Column("validator_version", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["inv_reports.report_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("finding_id"),
    )
    op.create_index(
        "ix_inv_rvf_report_severity",
        "inv_report_validation_findings",
        ["report_id", "severity"],
    )

    op.create_table(
        "inv_release_policy_evaluations",
        sa.Column("evaluation_id", sa.String(length=128), nullable=False),
        sa.Column("report_id", sa.String(length=128), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column(
            "decision", _enum(RELEASE_DECISION_VALUES, "inv_release_decision"), nullable=False
        ),
        sa.Column(
            "release_status",
            _enum(RELEASE_STATUS_VALUES, "inv_report_release_status"),
            nullable=False,
        ),
        sa.Column(
            "review_status", _enum(REVIEW_STATUS_VALUES, "inv_report_review_status"), nullable=False
        ),
        sa.Column("evaluation_hash", sa.String(length=64), nullable=False),
        sa.Column("report_hash", sa.String(length=64), nullable=False),
        sa.Column("claim_set_hash", sa.String(length=64), nullable=False),
        sa.Column("citation_set_hash", sa.String(length=64), nullable=False),
        sa.Column("hard_finding_count", sa.Integer(), nullable=False),
        sa.Column("governance_finding_count", sa.Integer(), nullable=False),
        sa.Column("basis", JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("hard_finding_count >= 0", name="ck_inv_rpe_hard_count"),
        sa.CheckConstraint("governance_finding_count >= 0", name="ck_inv_rpe_governance_count"),
        sa.ForeignKeyConstraint(["report_id"], ["inv_reports.report_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("evaluation_id"),
        sa.UniqueConstraint("report_id", "evaluation_hash", name="uq_inv_rpe_report_hash"),
    )
    op.create_index("ix_inv_rpe_report", "inv_release_policy_evaluations", ["report_id"])

    op.create_table(
        "inv_review_requests",
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("report_id", sa.String(length=128), nullable=False),
        sa.Column("report_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("claim_set_hash", sa.String(length=64), nullable=False),
        sa.Column("citation_set_hash", sa.String(length=64), nullable=False),
        sa.Column("report_hash", sa.String(length=64), nullable=False),
        sa.Column("evaluation_hash", sa.String(length=64), nullable=False),
        sa.Column("evaluation_id", sa.String(length=128), nullable=False),
        sa.Column("validator_version", sa.String(length=100), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("trigger_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("report_version >= 1", name="ck_inv_rrq_report_version"),
        sa.ForeignKeyConstraint(["report_id"], ["inv_reports.report_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["inv_release_policy_evaluations.evaluation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index("ix_inv_rrq_report_created", "inv_review_requests", ["report_id", "created_at"])
    op.create_index("ix_inv_rrq_evaluation", "inv_review_requests", ["evaluation_hash"])

    op.create_table(
        "inv_reviewer_sessions",
        sa.Column("session_public_id", sa.String(length=128), nullable=False),
        sa.Column("reviewer_id", sa.String(length=200), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("reviewer_config_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("generation >= 1", name="ck_inv_reviewer_sessions_generation"),
        sa.PrimaryKeyConstraint("session_public_id"),
        sa.UniqueConstraint("token_hash", name="uq_inv_reviewer_sessions_token_hash"),
    )
    op.create_index("ix_inv_reviewer_sessions_reviewer", "inv_reviewer_sessions", ["reviewer_id"])

    op.create_table(
        "inv_reviewer_auth_state",
        sa.Column("reviewer_id", sa.String(length=200), nullable=False),
        sa.Column("active_session_public_id", sa.String(length=128), nullable=True),
        sa.Column("active_generation", sa.Integer(), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("reviewer_id"),
    )

    op.create_table(
        "inv_reviewer_rate_buckets",
        sa.Column("bucket_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("bucket_fingerprint"),
    )

    op.create_table(
        "inv_review_research_requests",
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("review_id", sa.String(length=128), nullable=False),
        sa.Column("report_id", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("follow_up_run_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["review_id"], ["inv_review_decisions.review_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["report_id"], ["inv_reports.report_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["follow_up_run_id"], ["inv_runs.run_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index("ix_inv_rrr_report", "inv_review_research_requests", ["report_id"])

    op.create_table(
        "inv_review_idempotency",
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("report_id", sa.String(length=128), nullable=False),
        sa.Column("reviewer_id", sa.String(length=200), nullable=False),
        sa.Column("decision", _enum(REVIEW_DECISION_VALUES, "inv_review_decision"), nullable=False),
        sa.Column("response_payload", JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["inv_reports.report_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("idempotency_key"),
    )
    op.create_index("ix_inv_review_idempotency_report", "inv_review_idempotency", ["report_id"])

    op.create_table(
        "inv_recorded_human_review_decisions",
        sa.Column("recorded_id", sa.String(length=128), nullable=False),
        sa.Column("reviewer_id", sa.String(length=200), nullable=False),
        sa.Column("decision", _enum(REVIEW_DECISION_VALUES, "inv_review_decision"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("report_hash", sa.String(length=64), nullable=False),
        sa.Column("claim_set_hash", sa.String(length=64), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("citation_set_hash", sa.String(length=64), nullable=False),
        sa.Column("release_policy_version", sa.String(length=100), nullable=False),
        sa.Column("evaluation_hash", sa.String(length=64), nullable=False),
        sa.Column("semantic_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("recorded_id"),
        sa.UniqueConstraint("semantic_fingerprint", name="uq_inv_rhrd_fingerprint"),
    )

    # inv_review_decisions keeps its rows; add review provenance values.
    with op.batch_alter_table("inv_review_decisions") as batch:
        batch.add_column(sa.Column("review_request_id", sa.String(length=128), nullable=True))
        batch.add_column(
            sa.Column("reviewer_session_public_id", sa.String(length=128), nullable=True)
        )
        batch.add_column(
            sa.Column("reviewer_config_fingerprint", sa.String(length=64), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "decision_origin",
                _enum(DECISION_ORIGIN_VALUES, "inv_review_decision_origin"),
                nullable=False,
                server_default="LIVE",
            )
        )
    # SQLite batch mode recreates the table and drops its append-only triggers.
    if op.get_bind().dialect.name == "sqlite":
        _create_immutable_guards(("inv_review_decisions",))

    with op.batch_alter_table("inv_runs") as batch:
        batch.add_column(sa.Column("origin_run_id", sa.String(length=128), nullable=True))
        batch.add_column(
            sa.Column("origin_review_request_id", sa.String(length=128), nullable=True)
        )

    _create_immutable_guards(NEW_IMMUTABLE_TABLES)


def downgrade() -> None:
    _drop_immutable_guards(NEW_IMMUTABLE_TABLES)

    with op.batch_alter_table("inv_runs") as batch:
        batch.drop_column("origin_review_request_id")
        batch.drop_column("origin_run_id")

    if op.get_bind().dialect.name == "sqlite":
        _drop_immutable_guards(("inv_review_decisions",))
    with op.batch_alter_table("inv_review_decisions") as batch:
        batch.drop_constraint("inv_review_decision_origin", type_="check")
        batch.drop_column("decision_origin")
        batch.drop_column("reviewer_config_fingerprint")
        batch.drop_column("reviewer_session_public_id")
        batch.drop_column("review_request_id")
    if op.get_bind().dialect.name == "sqlite":
        _create_immutable_guards(("inv_review_decisions",))

    op.drop_table("inv_recorded_human_review_decisions")
    op.drop_table("inv_review_idempotency")
    op.drop_table("inv_review_research_requests")
    op.drop_table("inv_reviewer_rate_buckets")
    op.drop_table("inv_reviewer_auth_state")
    op.drop_table("inv_reviewer_sessions")
    op.drop_table("inv_review_requests")
    op.drop_table("inv_release_policy_evaluations")
    op.drop_table("inv_report_validation_findings")
    op.drop_table("inv_citations")
    op.drop_table("inv_report_projections")

    with op.batch_alter_table("inv_reports") as batch:
        batch.drop_index("ix_inv_reports_snapshot_hash")
        batch.drop_index("ix_inv_reports_run")
        batch.drop_constraint("ck_inv_report_citation_set_hash", type_="check")
        batch.drop_column("schema_version")
        batch.drop_column("citation_set_hash")
        batch.drop_column("report_input_snapshot_hash")
        batch.add_column(
            sa.Column(
                "review_status",
                _enum(REVIEW_STATUS_VALUES, "inv_report_review_status"),
                nullable=False,
                server_default="NOT_REQUIRED",
            )
        )
        batch.add_column(
            sa.Column(
                "release_status",
                _enum(RELEASE_STATUS_VALUES, "inv_report_release_status"),
                nullable=False,
                server_default="DRAFT",
            )
        )
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        batch.create_index("ix_inv_reports_run_release", ["run_id", "release_status"])

    op.drop_table("inv_report_input_snapshots")
