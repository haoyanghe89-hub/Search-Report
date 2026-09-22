"""Phase 4.3 agent feedback loop persistence.

Revision ID: 20260922_05
Revises: 20260922_04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = "20260922_05"
down_revision: str | None = "20260922_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("inv_run_budgets") as batch:
        batch.add_column(
            sa.Column("max_sources", sa.Integer(), nullable=False, server_default="100")
        )
        batch.add_column(
            sa.Column("sources_used", sa.Integer(), nullable=False, server_default="0")
        )
        batch.create_check_constraint("ck_inv_budget_sources_nonnegative", "sources_used >= 0")
        batch.create_check_constraint("ck_inv_budget_sources_limit", "sources_used <= max_sources")

    with op.batch_alter_table("inv_research_tasks") as batch:
        batch.add_column(sa.Column("target_claim_id", sa.String(128)))
        batch.add_column(sa.Column("origin_gap_id", sa.String(128)))
        batch.add_column(sa.Column("parent_task_id", sa.String(128)))
        batch.add_column(sa.Column("purpose", sa.Text()))
        batch.add_column(
            sa.Column(
                "preferred_source_types",
                JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.add_column(
            sa.Column(
                "suggested_queries",
                JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.add_column(sa.Column("round", sa.Integer(), nullable=False, server_default="1"))
        batch.create_foreign_key(
            "fk_inv_tasks_target_claim",
            "inv_claims",
            ["target_claim_id"],
            ["claim_id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_inv_tasks_origin_gap",
            "inv_research_gaps",
            ["origin_gap_id"],
            ["gap_id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_inv_tasks_parent",
            "inv_research_tasks",
            ["parent_task_id"],
            ["task_id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_inv_tasks_origin_gap", ["origin_gap_id"])
        batch.create_index("ix_inv_tasks_target_claim", ["target_claim_id"])
        batch.create_check_constraint("ck_inv_task_round_positive", "round >= 1")

    with op.batch_alter_table("inv_evidence") as batch:
        batch.add_column(sa.Column("created_by_step_id", sa.String(128)))
        batch.add_column(sa.Column("research_task_id", sa.String(128)))
        batch.create_foreign_key(
            "fk_inv_evidence_created_step",
            "inv_execution_steps",
            ["created_by_step_id"],
            ["step_id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_inv_evidence_task",
            "inv_research_tasks",
            ["research_task_id"],
            ["task_id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_inv_evidence_created_step", ["created_by_step_id"])
        batch.create_index("ix_inv_evidence_task", ["research_task_id"])

    with op.batch_alter_table("inv_claims") as batch:
        batch.add_column(sa.Column("created_by_step_id", sa.String(128)))
        batch.add_column(sa.Column("research_task_id", sa.String(128)))
        batch.create_foreign_key(
            "fk_inv_claims_created_step",
            "inv_execution_steps",
            ["created_by_step_id"],
            ["step_id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_inv_claims_task",
            "inv_research_tasks",
            ["research_task_id"],
            ["task_id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_inv_claims_created_step", ["created_by_step_id"])
        batch.create_index("ix_inv_claims_task", ["research_task_id"])

    with op.batch_alter_table("inv_research_gaps") as batch:
        batch.add_column(sa.Column("origin_validation_id", sa.String(128)))
        batch.create_foreign_key(
            "fk_inv_gaps_origin_validation",
            "inv_validation_results",
            ["origin_validation_id"],
            ["validation_id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_inv_gaps_origin_validation", ["origin_validation_id"])


def downgrade() -> None:
    with op.batch_alter_table("inv_research_gaps") as batch:
        batch.drop_index("ix_inv_gaps_origin_validation")
        batch.drop_constraint("fk_inv_gaps_origin_validation", type_="foreignkey")
        batch.drop_column("origin_validation_id")

    with op.batch_alter_table("inv_claims") as batch:
        batch.drop_index("ix_inv_claims_task")
        batch.drop_index("ix_inv_claims_created_step")
        batch.drop_constraint("fk_inv_claims_task", type_="foreignkey")
        batch.drop_constraint("fk_inv_claims_created_step", type_="foreignkey")
        batch.drop_column("research_task_id")
        batch.drop_column("created_by_step_id")

    with op.batch_alter_table("inv_evidence") as batch:
        batch.drop_index("ix_inv_evidence_task")
        batch.drop_index("ix_inv_evidence_created_step")
        batch.drop_constraint("fk_inv_evidence_task", type_="foreignkey")
        batch.drop_constraint("fk_inv_evidence_created_step", type_="foreignkey")
        batch.drop_column("research_task_id")
        batch.drop_column("created_by_step_id")

    with op.batch_alter_table("inv_research_tasks") as batch:
        batch.drop_constraint("ck_inv_task_round_positive", type_="check")
        batch.drop_index("ix_inv_tasks_target_claim")
        batch.drop_index("ix_inv_tasks_origin_gap")
        batch.drop_constraint("fk_inv_tasks_parent", type_="foreignkey")
        batch.drop_constraint("fk_inv_tasks_origin_gap", type_="foreignkey")
        batch.drop_constraint("fk_inv_tasks_target_claim", type_="foreignkey")
        batch.drop_column("round")
        batch.drop_column("suggested_queries")
        batch.drop_column("preferred_source_types")
        batch.drop_column("purpose")
        batch.drop_column("parent_task_id")
        batch.drop_column("origin_gap_id")
        batch.drop_column("target_claim_id")

    with op.batch_alter_table("inv_run_budgets") as batch:
        batch.drop_constraint("ck_inv_budget_sources_limit", type_="check")
        batch.drop_constraint("ck_inv_budget_sources_nonnegative", type_="check")
        batch.drop_column("sources_used")
        batch.drop_column("max_sources")
