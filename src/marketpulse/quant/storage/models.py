from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from marketpulse.investigation.persistence.base import Base


class InstrumentRow(Base):
    __tablename__ = "inv_quant_instrument"
    instrument_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    market: Mapped[str] = mapped_column(String(20), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="CNY")
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="Asia/Shanghai")
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)


class DatasetSnapshotRow(Base):
    __tablename__ = "inv_quant_dataset_snapshot"
    snapshot_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    semantic_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    cache_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    upstream: Mapped[str] = mapped_column(String(100), nullable=False)
    family_key: Mapped[str] = mapped_column(String(100), nullable=False)
    lineage_status: Mapped[str] = mapped_column(String(50), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    asof: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pit_level: Mapped[str] = mapped_column(String(30), nullable=False)
    rights_policy_id: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(50), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(50), nullable=False)
    row_count: Mapped[int] = mapped_column(nullable=False)
    quality_flags: Mapped[list] = mapped_column(JSON, nullable=False)
    manifest_ref: Mapped[str] = mapped_column(Text, nullable=False)
    partitions: Mapped[list] = mapped_column(JSON, nullable=False)
    frozen_payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class SnapshotOwnershipRow(Base):
    __tablename__ = "inv_quant_snapshot_ownership"
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_investigations.investigation_id", ondelete="RESTRICT"), primary_key=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("inv_quant_dataset_snapshot.snapshot_id", ondelete="RESTRICT"), primary_key=True
    )
    rights_scope: Mapped[str] = mapped_column(String(50), nullable=False)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ComputeJobRow(Base):
    __tablename__ = "inv_quant_compute_job"
    __table_args__ = (UniqueConstraint("run_id", "idempotency_key"),)
    job_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("inv_runs.run_id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    input_hash: Mapped[str] = mapped_column(String(64))
    input_ref: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30))
    attempt: Mapped[int] = mapped_column(default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifact_id: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(100))


class ComputeArtifactRow(Base):
    __tablename__ = "inv_quant_compute_artifact"
    artifact_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    manifest_ref: Mapped[str] = mapped_column(Text)
    output_ref: Mapped[str] = mapped_column(Text)
    bundle_ref: Mapped[str] = mapped_column(Text)


class ComputeRecordRow(Base):
    __tablename__ = "inv_quant_compute_record"
    record_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("inv_quant_compute_job.job_id", ondelete="RESTRICT")
    )
    payload_ref: Mapped[str] = mapped_column(Text)


class QuantReportMaterialRow(Base):
    __tablename__ = "inv_quant_report_material"
    material_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("inv_runs.run_id", ondelete="RESTRICT"))
    semantic_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QuantCitationRow(Base):
    __tablename__ = "inv_quant_citation"
    citation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("inv_reports.report_id", ondelete="RESTRICT"))
    payload: Mapped[dict] = mapped_column(JSON)
