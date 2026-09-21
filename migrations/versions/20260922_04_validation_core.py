"""phase 4.2 validation core

Revision ID: 20260922_04
Revises: 20260921_03
Create Date: 2026-09-22 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = "20260922_04"
down_revision: str | None = "20260921_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")
NEW_GAP_VALUES = (
    "EVIDENCE_GAP",
    "UNREADABLE_SOURCE",
    "SOURCE_CONFLICT",
    "MISSING_PRIMARY_SOURCE",
    "INSUFFICIENT_INDEPENDENCE",
    "INSUFFICIENT_ENTAILMENT",
    "MISSING_CAUSAL_SUPPORT",
    "MISSING_MECHANISM",
    "UNRESOLVED_QUANTITATIVE_CONFLICT",
    "ATTRIBUTION_UNDER_SUPPORTED",
    "ANALYSIS_ERROR",
    "OTHER",
)
OLD_GAP_VALUES = (
    "EVIDENCE_GAP",
    "UNREADABLE_SOURCE",
    "SOURCE_CONFLICT",
    "MISSING_PRIMARY_SOURCE",
    "INSUFFICIENT_INDEPENDENCE",
    "ANALYSIS_ERROR",
    "OTHER",
)
NEW_IMMUTABLE_TABLES = (
    "inv_semantic_judgments",
    "inv_source_families",
    "inv_source_family_members",
    "inv_validation_conflicts",
)


def _values_constraint(values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{value}'" for value in values)
    return f"gap_type IN ({rendered})"


def _create_immutable_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in NEW_IMMUTABLE_TABLES:
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION inv_reject_immutable_mutation()"
            )
    elif dialect == "sqlite":
        for table in NEW_IMMUTABLE_TABLES:
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable_update BEFORE UPDATE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'investigation record is append-only'); END"
            )
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'investigation record is append-only'); END"
            )


def _drop_immutable_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in NEW_IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    elif dialect == "sqlite":
        for table in NEW_IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable_update")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable_delete")


def upgrade() -> None:
    op.add_column("inv_claims", sa.Column("latest_validation_id", sa.String(128), nullable=True))
    op.create_index(
        "ix_inv_claims_latest_validation",
        "inv_claims",
        ["latest_validation_id"],
        unique=False,
    )

    op.add_column(
        "inv_conflict_sets",
        sa.Column(
            "competing_values", JSON_DOCUMENT, nullable=False, server_default=sa.text("'[]'")
        ),
    )
    op.add_column(
        "inv_conflict_sets",
        sa.Column(
            "possible_explanations", JSON_DOCUMENT, nullable=False, server_default=sa.text("'[]'")
        ),
    )
    op.add_column(
        "inv_conflict_sets",
        sa.Column("resolution_status", sa.String(40), nullable=False, server_default="UNRESOLVED"),
    )
    op.add_column("inv_conflict_sets", sa.Column("resolution_basis", sa.Text(), nullable=True))
    op.create_index(
        "ix_inv_conflicts_resolution",
        "inv_conflict_sets",
        ["resolution_status"],
        unique=False,
    )

    zeros = "0" * 64
    op.add_column(
        "inv_validation_results",
        sa.Column("policy_version", sa.String(100), nullable=False, server_default="legacy-policy"),
    )
    op.add_column(
        "inv_validation_results",
        sa.Column("input_fingerprint", sa.String(64), nullable=False, server_default=zeros),
    )
    op.add_column(
        "inv_validation_results",
        sa.Column("evidence_set_hash", sa.String(64), nullable=False, server_default=zeros),
    )
    op.add_column(
        "inv_validation_results",
        sa.Column(
            "lineage_version", sa.String(100), nullable=False, server_default="legacy-lineage"
        ),
    )
    op.add_column(
        "inv_validation_results",
        sa.Column(
            "conflict_set_refs", JSON_DOCUMENT, nullable=False, server_default=sa.text("'[]'")
        ),
    )
    op.add_column(
        "inv_validation_results",
        sa.Column(
            "validation_basis_payload",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "inv_validation_results",
        sa.Column(
            "confidence_basis",
            sa.Text(),
            nullable=False,
            server_default="Legacy confidence basis",
        ),
    )
    op.create_index(
        "ix_inv_validation_input_fingerprint",
        "inv_validation_results",
        ["input_fingerprint"],
        unique=False,
    )
    op.create_index(
        "ix_inv_validation_evidence_set_hash",
        "inv_validation_results",
        ["evidence_set_hash"],
        unique=False,
    )
    op.create_index(
        "ix_inv_validation_policy",
        "inv_validation_results",
        ["policy_version", "profile_version"],
        unique=False,
    )

    with op.batch_alter_table("inv_research_gaps") as batch:
        batch.drop_constraint("inv_gap_type", type_="check")
        batch.alter_column(
            "gap_type",
            existing_type=sa.String(25),
            type_=sa.String(64),
            existing_nullable=False,
        )
        batch.add_column(sa.Column("preferred_source_type", sa.String(100), nullable=True))
        batch.add_column(sa.Column("missing_requirement", sa.Text(), nullable=True))
        batch.add_column(sa.Column("suggested_action", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "ck_inv_gap_type_values",
            _values_constraint(NEW_GAP_VALUES),
        )
    op.create_index(
        "ix_inv_gaps_claim_type",
        "inv_research_gaps",
        ["target_claim_id", "gap_type"],
        unique=False,
    )

    op.create_table(
        "inv_conflict_evidence",
        sa.Column("conflict_id", sa.String(128), nullable=False),
        sa.Column("evidence_id", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["conflict_id"], ["inv_conflict_sets.conflict_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["inv_evidence.evidence_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("conflict_id", "evidence_id"),
    )
    op.create_index(
        "ix_inv_conflict_evidence_evidence",
        "inv_conflict_evidence",
        ["evidence_id"],
        unique=False,
    )

    op.create_table(
        "inv_semantic_judgments",
        sa.Column("judgment_id", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("claim_id", sa.String(128), nullable=False),
        sa.Column("evidence_id", sa.String(128), nullable=False),
        sa.Column(
            "judgment",
            sa.Enum(
                "ENTAILS",
                "PARTIALLY_SUPPORTS",
                "CONTRADICTS",
                "NOT_RELEVANT",
                "UNCERTAIN",
                name="inv_semantic_judgment_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("semantic_confidence", sa.Float(), nullable=False),
        sa.Column("model_call_ref", sa.String(255), nullable=True),
        sa.Column("recorded_judgment_ref", sa.String(255), nullable=True),
        sa.Column("schema_version", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "semantic_confidence >= 0 AND semantic_confidence <= 1",
            name="ck_inv_semantic_confidence",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["inv_runs.run_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["inv_claims.claim_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["evidence_id"], ["inv_evidence.evidence_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("judgment_id"),
    )
    op.create_index(
        "ix_inv_semantic_claim_evidence",
        "inv_semantic_judgments",
        ["claim_id", "evidence_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_inv_semantic_run",
        "inv_semantic_judgments",
        ["run_id"],
        unique=False,
    )

    op.create_table(
        "inv_source_families",
        sa.Column("family_record_id", sa.String(128), nullable=False),
        sa.Column("validation_id", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("family_id", sa.String(128), nullable=False),
        sa.Column("lineage_version", sa.String(100), nullable=False),
        sa.Column(
            "origin_type",
            sa.Enum(
                "ORIGINAL",
                "SYNDICATED",
                "ATTRIBUTED",
                "MIXED",
                "UNKNOWN",
                name="inv_lineage_origin_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("independence_basis", JSON_DOCUMENT, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "resolution_method",
            sa.Enum(
                "DETERMINISTIC",
                "SEMANTIC_ASSISTED",
                "UNKNOWN",
                name="inv_lineage_resolution_method",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_inv_family_confidence"),
        sa.ForeignKeyConstraint(
            ["validation_id"], ["inv_validation_results.validation_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["inv_runs.run_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("family_record_id"),
        sa.UniqueConstraint("validation_id", "family_id", name="uq_inv_family_validation"),
    )
    op.create_index(
        "ix_inv_families_run_family",
        "inv_source_families",
        ["run_id", "family_id"],
        unique=False,
    )
    op.create_index(
        "ix_inv_families_validation",
        "inv_source_families",
        ["validation_id"],
        unique=False,
    )

    op.create_table(
        "inv_source_family_members",
        sa.Column("family_record_id", sa.String(128), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["family_record_id"], ["inv_source_families.family_record_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["source_id"], ["inv_sources.source_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("family_record_id", "source_id"),
    )
    op.create_index(
        "ix_inv_family_members_source",
        "inv_source_family_members",
        ["source_id"],
        unique=False,
    )

    op.create_table(
        "inv_validation_conflicts",
        sa.Column("validation_id", sa.String(128), nullable=False),
        sa.Column("conflict_id", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["validation_id"], ["inv_validation_results.validation_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["conflict_id"], ["inv_conflict_sets.conflict_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("validation_id", "conflict_id"),
    )
    op.create_index(
        "ix_inv_validation_conflicts_conflict",
        "inv_validation_conflicts",
        ["conflict_id"],
        unique=False,
    )
    _create_immutable_guards()


def downgrade() -> None:
    _drop_immutable_guards()
    op.drop_index("ix_inv_validation_conflicts_conflict", table_name="inv_validation_conflicts")
    op.drop_table("inv_validation_conflicts")
    op.drop_index("ix_inv_family_members_source", table_name="inv_source_family_members")
    op.drop_table("inv_source_family_members")
    op.drop_index("ix_inv_families_validation", table_name="inv_source_families")
    op.drop_index("ix_inv_families_run_family", table_name="inv_source_families")
    op.drop_table("inv_source_families")
    op.drop_index("ix_inv_semantic_run", table_name="inv_semantic_judgments")
    op.drop_index("ix_inv_semantic_claim_evidence", table_name="inv_semantic_judgments")
    op.drop_table("inv_semantic_judgments")
    op.drop_index("ix_inv_conflict_evidence_evidence", table_name="inv_conflict_evidence")
    op.drop_table("inv_conflict_evidence")

    op.drop_index("ix_inv_gaps_claim_type", table_name="inv_research_gaps")
    with op.batch_alter_table("inv_research_gaps") as batch:
        batch.drop_constraint("ck_inv_gap_type_values", type_="check")
        batch.drop_column("suggested_action")
        batch.drop_column("missing_requirement")
        batch.drop_column("preferred_source_type")
        batch.alter_column(
            "gap_type",
            existing_type=sa.String(64),
            type_=sa.String(25),
            existing_nullable=False,
        )
        batch.create_check_constraint("inv_gap_type", _values_constraint(OLD_GAP_VALUES))

    op.drop_index("ix_inv_validation_policy", table_name="inv_validation_results")
    op.drop_index("ix_inv_validation_evidence_set_hash", table_name="inv_validation_results")
    op.drop_index("ix_inv_validation_input_fingerprint", table_name="inv_validation_results")
    op.drop_column("inv_validation_results", "confidence_basis")
    op.drop_column("inv_validation_results", "validation_basis_payload")
    op.drop_column("inv_validation_results", "conflict_set_refs")
    op.drop_column("inv_validation_results", "lineage_version")
    op.drop_column("inv_validation_results", "evidence_set_hash")
    op.drop_column("inv_validation_results", "input_fingerprint")
    op.drop_column("inv_validation_results", "policy_version")

    op.drop_index("ix_inv_conflicts_resolution", table_name="inv_conflict_sets")
    op.drop_column("inv_conflict_sets", "resolution_basis")
    op.drop_column("inv_conflict_sets", "resolution_status")
    op.drop_column("inv_conflict_sets", "possible_explanations")
    op.drop_column("inv_conflict_sets", "competing_values")

    op.drop_index("ix_inv_claims_latest_validation", table_name="inv_claims")
    op.drop_column("inv_claims", "latest_validation_id")
