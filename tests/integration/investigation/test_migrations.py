from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

EXPECTED_TABLES = {
    "inv_audit_events",
    "inv_claim_evidence_relations",
    "inv_claims",
    "inv_call_bindings",
    "inv_conflict_claims",
    "inv_conflict_sets",
    "inv_document_artifacts",
    "inv_evidence",
    "inv_execution_steps",
    "inv_investigation_questions",
    "inv_investigations",
    "inv_recorded_model_calls",
    "inv_recorded_tool_calls",
    "inv_report_section_claims",
    "inv_report_sections",
    "inv_reports",
    "inv_research_gaps",
    "inv_research_tasks",
    "inv_review_decisions",
    "inv_runs",
    "inv_run_budgets",
    "inv_source_snapshots",
    "inv_sources",
    "inv_timeline_events",
    "inv_timeline_evidence",
    "inv_validation_results",
}


def _config(database_url: str) -> Config:
    root = Path(__file__).resolve().parents[3]
    config = Config(root / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.attributes["database_url"] = database_url
    return config


def test_upgrade_and_downgrade_preserve_legacy_schema(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    url = f"sqlite:///{database.as_posix()}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE mp_runs (run_id VARCHAR(100) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO mp_runs (run_id) VALUES ('legacy-run')"))
    engine.dispose()

    config = _config(url)
    command.upgrade(config, "head")

    engine = create_engine(url)
    inspector = inspect(engine)
    assert EXPECTED_TABLES <= set(inspector.get_table_names())
    evidence_fks = inspector.get_foreign_keys("inv_evidence")
    assert any(fk["referred_table"] == "inv_source_snapshots" for fk in evidence_fks)
    relation_uniques = inspector.get_unique_constraints("inv_claim_evidence_relations")
    assert any(
        set(item["column_names"]) == {"claim_id", "evidence_id"} for item in relation_uniques
    )
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT run_id FROM mp_runs")) == "legacy-run"
    engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(url)
    remaining = set(inspect(engine).get_table_names())
    assert "mp_runs" in remaining
    assert not (EXPECTED_TABLES & remaining)
    engine.dispose()
