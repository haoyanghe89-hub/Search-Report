"""Phase 4.1 persistent harness runtime.

Revision ID: 20260921_03
Revises: 20260921_02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

JSON_DOCUMENT = sa.JSON().with_variant(JSONB(), "postgresql")

revision: str = "20260921_03"
down_revision: str | None = "20260921_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = (
    "CREATED",
    "PENDING",
    "WAITING_FOR_EXECUTION",
    "RUNNING",
    "PAUSED",
    "INTERRUPTED",
    "BLOCKED",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)
NEW_STATUSES = (
    "CREATED",
    "PENDING",
    "WAITING_FOR_EXECUTION",
    "RUNNING",
    "VERIFYING",
    "READY_FOR_REPORT",
    "PAUSED",
    "INTERRUPTED",
    "BLOCKED",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)


def _status_check(values: tuple[str, ...]) -> str:
    return "status IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    with op.batch_alter_table("inv_runs") as batch:
        batch.drop_constraint("inv_run_status", type_="check")
        batch.create_check_constraint("inv_run_status", _status_check(NEW_STATUSES))
        batch.add_column(sa.Column("current_step_key", sa.String(256)))
        batch.add_column(sa.Column("last_completed_step_key", sa.String(256)))
        batch.add_column(sa.Column("owner_instance_id", sa.String(128)))
        batch.add_column(sa.Column("owner_heartbeat_at", sa.DateTime(timezone=True)))

    op.add_column(
        "inv_execution_steps",
        sa.Column("logical_step_key", sa.String(256), nullable=False, server_default="legacy"),
    )
    op.execute("UPDATE inv_execution_steps SET logical_step_key = step_id")
    with op.batch_alter_table("inv_execution_steps") as batch:
        batch.drop_constraint("uq_inv_step_attempt", type_="unique")
        batch.create_unique_constraint(
            "uq_inv_step_attempt", ["run_id", "logical_step_key", "attempt"]
        )
        batch.add_column(
            sa.Column("dependency_keys", JSON_DOCUMENT, nullable=False, server_default="[]")
        )
        batch.add_column(sa.Column("output_schema_version", sa.String(100)))
        batch.add_column(
            sa.Column("active_elapsed_ms", sa.Integer(), nullable=False, server_default="0")
        )
        batch.alter_column("logical_step_key", existing_type=sa.String(256), server_default=None)
        batch.alter_column("dependency_keys", existing_type=JSON_DOCUMENT, server_default=None)
        batch.alter_column("active_elapsed_ms", existing_type=sa.Integer(), server_default=None)

    op.create_table(
        "inv_run_budgets",
        sa.Column(
            "run_id",
            sa.String(128),
            sa.ForeignKey("inv_runs.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("max_research_rounds", sa.Integer(), nullable=False),
        sa.Column("max_search_calls", sa.Integer(), nullable=False),
        sa.Column("max_fetch_calls", sa.Integer(), nullable=False),
        sa.Column("max_model_calls", sa.Integer(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("max_wall_time_ms", sa.Integer(), nullable=False),
        sa.Column("research_rounds_used", sa.Integer(), nullable=False),
        sa.Column("search_calls_used", sa.Integer(), nullable=False),
        sa.Column("fetch_calls_used", sa.Integer(), nullable=False),
        sa.Column("model_calls_used", sa.Integer(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("consumed_wall_time_ms", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("consumed_wall_time_ms >= 0", name="ck_inv_budget_wall_nonnegative"),
    )
    op.create_table(
        "inv_call_bindings",
        sa.Column("binding_id", sa.String(128), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(128),
            sa.ForeignKey("inv_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("logical_step_key", sa.String(256), nullable=False),
        sa.Column("call_site_key", sa.String(256), nullable=False),
        sa.Column("call_ordinal", sa.Integer(), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("recorded_call_id", sa.String(128), nullable=False),
        sa.Column("call_kind", sa.String(16), nullable=False),
        sa.Column("operation", sa.String(200), nullable=False),
        sa.Column("schema_version", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(100)),
        sa.Column("config_version", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "logical_step_key",
            "call_site_key",
            "call_ordinal",
            name="uq_inv_call_binding_site",
        ),
    )
    op.create_index(
        "ix_inv_call_bindings_fingerprint", "inv_call_bindings", ["request_fingerprint"]
    )
    op.create_index("ix_inv_call_bindings_recorded_call", "inv_call_bindings", ["recorded_call_id"])


def downgrade() -> None:
    op.drop_index("ix_inv_call_bindings_recorded_call", table_name="inv_call_bindings")
    op.drop_index("ix_inv_call_bindings_fingerprint", table_name="inv_call_bindings")
    op.drop_table("inv_call_bindings")
    op.drop_table("inv_run_budgets")
    with op.batch_alter_table("inv_execution_steps") as batch:
        batch.drop_constraint("uq_inv_step_attempt", type_="unique")
        batch.create_unique_constraint(
            "uq_inv_step_attempt", ["run_id", "input_fingerprint", "attempt"]
        )
        batch.drop_column("active_elapsed_ms")
        batch.drop_column("output_schema_version")
        batch.drop_column("dependency_keys")
        batch.drop_column("logical_step_key")
    with op.batch_alter_table("inv_runs") as batch:
        batch.drop_column("owner_heartbeat_at")
        batch.drop_column("owner_instance_id")
        batch.drop_column("last_completed_step_key")
        batch.drop_column("current_step_key")
        batch.drop_constraint("inv_run_status", type_="check")
        batch.create_check_constraint("inv_run_status", _status_check(OLD_STATUSES))
