"""P0-C/D computation leases, immutable artifacts, calls and report sidecars."""

import sqlalchemy as sa
from alembic import op

revision = "20261004_09"
down_revision = "20261004_08"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "inv_quant_compute_job",
        sa.Column("job_id", sa.String(100), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(100),
            sa.ForeignKey("inv_runs.run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("input_ref", sa.Text, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("lease_token", sa.String(64)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("artifact_id", sa.String(100)),
        sa.Column("error_code", sa.String(100)),
        sa.UniqueConstraint("run_id", "idempotency_key"),
    )
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER trg_quant_job_intent BEFORE UPDATE ON inv_quant_compute_job "
            "WHEN NEW.run_id != OLD.run_id OR NEW.idempotency_key != OLD.idempotency_key "
            "OR NEW.input_hash != OLD.input_hash OR NEW.input_ref != OLD.input_ref "
            "BEGIN SELECT RAISE(ABORT,'quant input intent is immutable'); END"
        )
    op.create_table(
        "inv_quant_compute_artifact",
        sa.Column("artifact_id", sa.String(100), primary_key=True),
        sa.Column("manifest_ref", sa.Text, nullable=False),
        sa.Column("output_ref", sa.Text, nullable=False),
        sa.Column("bundle_ref", sa.Text, nullable=False),
    )
    op.create_table(
        "inv_quant_compute_record",
        sa.Column("record_id", sa.String(100), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(100),
            sa.ForeignKey("inv_quant_compute_job.job_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("payload_ref", sa.Text, nullable=False),
    )
    op.create_table(
        "inv_quant_report_material",
        sa.Column("material_id", sa.String(100), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(100),
            sa.ForeignKey("inv_runs.run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("semantic_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "inv_quant_citation",
        sa.Column("citation_id", sa.String(128), primary_key=True),
        sa.Column(
            "report_id",
            sa.String(100),
            sa.ForeignKey("inv_reports.report_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    for table in (
        "inv_quant_compute_artifact",
        "inv_quant_compute_record",
        "inv_quant_report_material",
        "inv_quant_citation",
    ):
        if op.get_bind().dialect.name == "sqlite":
            for action in ("update", "delete"):
                # The existing archive deletion service supplies scoped permits.
                key = {
                    "inv_quant_compute_artifact": "artifact_id",
                    "inv_quant_compute_record": "record_id",
                    "inv_quant_report_material": "material_id",
                    "inv_quant_citation": "citation_id",
                }[table]
                permitted = (
                    " AND NOT EXISTS (SELECT 1 FROM inv_deletion_permits "
                    f"WHERE table_name='{table}' AND row_key=json_array(OLD.{key}))"
                    if action == "delete"
                    else ""
                )
                op.execute(
                    f"CREATE TRIGGER trg_{table}_immutable_{action} BEFORE {action} ON {table} "
                    f"WHEN 1=1{permitted} BEGIN "
                    "SELECT RAISE(ABORT,'quant computation is immutable'); END"
                )
        else:
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION inv_reject_immutable_mutation()"
            )


def downgrade():
    for name in (
        "inv_quant_citation",
        "inv_quant_report_material",
        "inv_quant_compute_record",
        "inv_quant_compute_artifact",
        "inv_quant_compute_job",
    ):
        op.drop_table(name)
