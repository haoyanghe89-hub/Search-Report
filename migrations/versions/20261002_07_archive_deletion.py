"""Exact-row archive deletion permission; UPDATE remains append-only."""

import sqlalchemy as sa
from alembic import op

revision = "20261002_07"
down_revision = "20260922_06"
branch_labels = None
depends_on = None
TABLES = (
    "inv_source_snapshots",
    "inv_document_artifacts",
    "inv_evidence",
    "inv_validation_results",
    "inv_review_decisions",
    "inv_audit_events",
    "inv_recorded_tool_calls",
    "inv_recorded_model_calls",
    "inv_semantic_judgments",
    "inv_source_families",
    "inv_source_family_members",
    "inv_validation_conflicts",
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


def upgrade():
    op.create_table(
        "inv_deletion_permits",
        sa.Column("table_name", sa.String(100), primary_key=True),
        sa.Column("row_key", sa.String(1000), primary_key=True),
    )
    dialect = op.get_bind().dialect.name
    inspector = sa.inspect(op.get_bind())
    if dialect == "postgresql":
        op.execute("""
        CREATE FUNCTION inv_authorized_archive_delete() RETURNS trigger AS $$
        DECLARE key_value text;
        BEGIN
          SELECT jsonb_agg(to_jsonb(OLD)->key ORDER BY ordinal)::text INTO key_value
            FROM unnest(TG_ARGV) WITH ORDINALITY AS keys(key, ordinal);
          IF TG_OP = 'DELETE' AND EXISTS (
            SELECT 1 FROM inv_deletion_permits
            WHERE table_name = TG_TABLE_NAME AND row_key = key_value
          ) THEN RETURN OLD; END IF;
          RAISE EXCEPTION 'investigation record is append-only';
        END; $$ LANGUAGE plpgsql
        """)
    for table in TABLES:
        pk = inspector.get_pk_constraint(table)["constrained_columns"]
        if dialect == "sqlite":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable_delete")
            row_key = "json_array(" + ",".join(f'OLD."{name}"' for name in pk) + ")"
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable_delete BEFORE DELETE ON {table} "
                f"WHEN NOT EXISTS (SELECT 1 FROM inv_deletion_permits "
                f"WHERE table_name = '{table}' AND row_key = {row_key}) "
                "BEGIN SELECT RAISE(ABORT, 'investigation record is append-only'); END"
            )
        else:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
            arguments = ",".join(f"'{name}'" for name in pk)
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION inv_authorized_archive_delete({arguments})"
            )


def downgrade():
    dialect = op.get_bind().dialect.name
    for table in TABLES:
        if dialect == "sqlite":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable_delete")
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'investigation record is append-only'); END"
            )
        else:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION inv_reject_immutable_mutation()"
            )
    if dialect == "postgresql":
        op.execute("DROP FUNCTION inv_authorized_archive_delete()")
    op.drop_table("inv_deletion_permits")
