"""failure-aware external call recording

Revision ID: 20260921_02
Revises: 20260921_01
Create Date: 2026-09-21 21:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_02"
down_revision: str | None = "20260921_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("inv_recorded_tool_calls", "inv_recorded_model_calls")
STATUSES = (
    "SUCCESS",
    "TIMEOUT",
    "PROVIDER_ERROR",
    "RATE_LIMITED",
    "INVALID_RESPONSE",
    "SECURITY_BLOCKED",
    "CANCELLED",
)


def _sqlite_drop_call_guards() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable_update")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable_delete")


def _sqlite_create_call_guards() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable_update BEFORE UPDATE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'investigation record is append-only'); END"
        )
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable_delete BEFORE DELETE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'investigation record is append-only'); END"
        )


def _status_type() -> sa.Enum:
    return sa.Enum(
        *STATUSES,
        name="inv_external_call_status",
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    _sqlite_drop_call_guards()
    for kind, table in (("tool", TABLES[0]), ("model", TABLES[1])):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"uq_inv_{kind}_call_fingerprint", type_="unique")
            batch.drop_constraint(f"ck_inv_{kind}_response_blob", type_="check")
            batch.drop_constraint(f"ck_inv_{kind}_response_hash", type_="check")
            batch.alter_column(
                "response_blob_ref", existing_type=sa.String(length=96), nullable=True
            )
            batch.alter_column("response_hash", existing_type=sa.String(length=64), nullable=True)
            batch.add_column(
                sa.Column(
                    "config_version",
                    sa.String(length=100),
                    nullable=False,
                    server_default="legacy-v1",
                )
            )
            batch.add_column(
                sa.Column("attempt", sa.Integer(), nullable=False, server_default="1")
            )
            batch.add_column(
                sa.Column(
                    "status", _status_type(), nullable=False, server_default="SUCCESS"
                )
            )
            batch.add_column(
                sa.Column("replayable", sa.Boolean(), nullable=False, server_default=sa.true())
            )
            batch.add_column(sa.Column("error_code", sa.String(length=100), nullable=True))
            batch.add_column(sa.Column("error_message", sa.Text(), nullable=True))
            batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
            batch.create_check_constraint(
                f"ck_inv_{kind}_response_blob",
                "response_blob_ref IS NULL OR response_blob_ref LIKE 'blob://sha256/%'",
            )
            batch.create_check_constraint(
                f"ck_inv_{kind}_response_hash",
                "response_hash IS NULL OR length(response_hash) = 64",
            )
            batch.create_check_constraint(
                f"ck_inv_{kind}_response_pair",
                "(response_blob_ref IS NULL) = (response_hash IS NULL)",
            )
            batch.create_check_constraint(
                f"ck_inv_{kind}_attempt_positive", "attempt >= 1"
            )
            batch.create_check_constraint(
                f"ck_inv_{kind}_replayable_success",
                "replayable = false OR (status = 'SUCCESS' AND response_blob_ref IS NOT NULL)",
            )
        op.execute(sa.text(f"UPDATE {table} SET completed_at = recorded_at"))
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "completed_at", existing_type=sa.DateTime(timezone=True), nullable=False
            )
            batch.alter_column(
                "config_version",
                existing_type=sa.String(length=100),
                server_default=None,
            )
            batch.alter_column("attempt", existing_type=sa.Integer(), server_default=None)
            batch.alter_column("status", existing_type=_status_type(), server_default=None)
            batch.alter_column("replayable", existing_type=sa.Boolean(), server_default=None)
        op.create_index(
            f"ix_inv_{kind}_calls_replay_lookup",
            table,
            ["run_id", "operation", "request_fingerprint", "status", "replayable"],
            unique=False,
        )
    _sqlite_create_call_guards()


def downgrade() -> None:
    _sqlite_drop_call_guards()
    for kind, table in (("tool", TABLES[0]), ("model", TABLES[1])):
        # The previous schema could not represent failures. Downgrade intentionally
        # preserves only complete successful observations.
        op.execute(
            sa.text(
                f"DELETE FROM {table} WHERE status <> 'SUCCESS' "
                "OR replayable = false OR response_blob_ref IS NULL OR response_hash IS NULL"
            )
        )
        op.drop_index(f"ix_inv_{kind}_calls_replay_lookup", table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_inv_{kind}_replayable_success", type_="check")
            batch.drop_constraint(f"ck_inv_{kind}_attempt_positive", type_="check")
            batch.drop_constraint(f"ck_inv_{kind}_response_pair", type_="check")
            batch.drop_constraint(f"ck_inv_{kind}_response_blob", type_="check")
            batch.drop_constraint(f"ck_inv_{kind}_response_hash", type_="check")
            batch.drop_constraint("inv_external_call_status", type_="check")
            batch.drop_column("completed_at")
            batch.drop_column("error_message")
            batch.drop_column("error_code")
            batch.drop_column("replayable")
            batch.drop_column("status")
            batch.drop_column("attempt")
            batch.drop_column("config_version")
            batch.alter_column(
                "response_blob_ref", existing_type=sa.String(length=96), nullable=False
            )
            batch.alter_column("response_hash", existing_type=sa.String(length=64), nullable=False)
            batch.create_check_constraint(
                f"ck_inv_{kind}_response_blob",
                "response_blob_ref LIKE 'blob://sha256/%'",
            )
            batch.create_check_constraint(
                f"ck_inv_{kind}_response_hash", "length(response_hash) = 64"
            )
            batch.create_unique_constraint(
                f"uq_inv_{kind}_call_fingerprint",
                ["run_id", "operation", "request_fingerprint"],
            )
    _sqlite_create_call_guards()
