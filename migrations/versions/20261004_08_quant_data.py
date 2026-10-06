"""P0-A/B immutable instruments, datasets and shared archive ownership."""

import sqlalchemy as sa
from alembic import op

revision = "20261004_08"
down_revision = "20261002_07"
branch_labels = None
depends_on = None
TABLES = ("inv_quant_instrument", "inv_quant_dataset_snapshot", "inv_quant_snapshot_ownership")


def upgrade():
    op.create_table(
        TABLES[0],
        sa.Column("instrument_id", sa.String(100), primary_key=True),
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("timezone", sa.String(50), nullable=False),
        sa.Column("definition", sa.JSON, nullable=False),
    )
    op.create_table(
        TABLES[1],
        sa.Column("snapshot_id", sa.String(100), primary_key=True),
        sa.Column("semantic_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("upstream", sa.String(100), nullable=False),
        sa.Column("family_key", sa.String(100), nullable=False),
        sa.Column("lineage_status", sa.String(50), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asof", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pit_level", sa.String(30), nullable=False),
        sa.Column("rights_policy_id", sa.String(200), nullable=False),
        sa.Column("schema_version", sa.String(50), nullable=False),
        sa.Column("normalizer_version", sa.String(50), nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("quality_flags", sa.JSON, nullable=False),
        sa.Column("manifest_ref", sa.Text, nullable=False),
        sa.Column("partitions", sa.JSON, nullable=False),
        sa.Column("frozen_payload", sa.JSON, nullable=False),
    )
    for column in ("cache_key", "request_hash"):
        op.create_index(f"ix_{TABLES[1]}_{column}", TABLES[1], [column])
    op.create_table(
        TABLES[2],
        sa.Column(
            "investigation_id",
            sa.String(100),
            sa.ForeignKey("inv_investigations.investigation_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "snapshot_id",
            sa.String(100),
            sa.ForeignKey("inv_quant_dataset_snapshot.snapshot_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("rights_scope", sa.String(50), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True)),
    )
    dialect = op.get_bind().dialect.name
    for name in TABLES[:2]:
        if dialect == "sqlite":
            for action in ("update", "delete"):
                op.execute(
                    f"CREATE TRIGGER trg_{name}_immutable_{action} BEFORE {action} ON {name} "
                    "BEGIN SELECT RAISE(ABORT, 'quant snapshot is immutable'); END"
                )
        else:
            op.execute(
                f"CREATE TRIGGER trg_{name}_immutable BEFORE UPDATE OR DELETE ON {name} "
                "FOR EACH ROW EXECUTE FUNCTION inv_reject_immutable_mutation()"
            )


def downgrade():
    for name in reversed(TABLES):
        op.drop_table(name)
