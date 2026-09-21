# Investigation Data + Persistence Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the typed Investigation domain, PostgreSQL-compatible schema migrations, immutable SourceSnapshot persistence, and locator contracts.

**Architecture:** Pure Pydantic domain models are mapped to explicit SQLAlchemy 2.x tables under an `inv_` namespace. Alembic owns schema evolution, while a transaction-oriented snapshot service composes the database with the existing content-addressed BlobStoragePort.

**Tech Stack:** Python 3.11+, Pydantic 2, SQLAlchemy 2, Alembic 1.x, PostgreSQL, SQLite test backend, pytest, Ruff, mypy, uv.

**Spec:** `docs/superpowers/specs/2026-09-21-investigation-data-foundation-design.md`

## Global Constraints

- Keep the legacy MarketPulse schema and runtime operational.
- Investigation code must not import market-specific domain or services.
- Evidence and Claim remain separate entities and tables.
- Database rows never store absolute blob filesystem paths.
- Replay-eligible recorded calls require actual request and response BlobRefs.
- Do not implement agents, validation execution, report writing, replay execution, OCR, or frontend changes.

---

### Task 1: Typed domain and locator contracts

**Files:**
- Create: `src/marketpulse/investigation/domain/*.py`
- Test: `tests/unit/investigation/test_domain.py`
- Test: `tests/unit/investigation/test_locators.py`

**Interfaces:**
- Produces: frozen domain models, `TextRangeLocator`, `PdfTextRangeLocator`, `serialize_locator(locator) -> str`, and `deserialize_locator(payload) -> EvidenceLocator`.

- [x] Write failing tests that construct all required enums/entities, prove `Evidence` has no Claim status, reject invalid call payload references, and round-trip both locator forms with stable JSON.
- [x] Run `pytest tests/unit/investigation/test_domain.py tests/unit/investigation/test_locators.py -q` and confirm import failures.
- [x] Implement focused enum, locator, runtime, source, claim, report, and recording modules with strict Pydantic validation.
- [x] Re-run the focused tests and confirm they pass.

### Task 2: SQLAlchemy schema and formal migration

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/20260921_01_investigation_foundation.py`
- Create: `src/marketpulse/investigation/persistence/base.py`
- Create: `src/marketpulse/investigation/persistence/models.py`
- Test: `tests/integration/investigation/test_migrations.py`

**Interfaces:**
- Produces: `Base`, `create_investigation_engine(url)`, `create_session_factory(engine)`, and Alembic `upgrade head` / `downgrade base` support.

- [x] Add Alembic and write migration tests that start with a legacy `mp_runs` table, upgrade to every `inv_` table, verify constraints/indexes, downgrade, and confirm the legacy table remains.
- [x] Run the migration test and confirm failure before configuration/revision exists.
- [x] Implement explicit ORM mappings and a hand-reviewed Alembic revision; enable SQLite foreign keys and PostgreSQL-safe JSON/constraints.
- [x] Re-run migration tests on SQLite and, when configured, PostgreSQL.

### Task 3: Entity persistence and append-only guarantees

**Files:**
- Create: `src/marketpulse/investigation/persistence/repositories.py`
- Test: `tests/integration/investigation/test_entity_roundtrip.py`

**Interfaces:**
- Consumes: domain entities and ORM tables from Tasks 1–2.
- Produces: focused repository methods for inserting/loading every core entity and normalized relation membership.

- [x] Write failing round-trip tests for all required entities, multi-snapshot sources, supports/contradicts relations, duplicate relation rejection, ValidationResult history, and AuditEvent history.
- [x] Implement explicit domain-to-row and row-to-domain mappings without generic market compatibility branches.
- [x] Add database-level immutable triggers for snapshots, artifacts, evidence, validation results, review decisions, audit events, and recorded calls.
- [x] Confirm attempted history UPDATE/DELETE fails and repeated inserts remain queryable in creation order.

### Task 4: SourceSnapshot persistence vertical slice

**Files:**
- Create: `src/marketpulse/investigation/services/source_snapshots.py`
- Test: `tests/integration/investigation/test_source_snapshot_persistence.py`

**Interfaces:**
- Produces: `SourceSnapshotPersistence.persist(...) -> SourceSnapshot`, `load(snapshot_id) -> PersistedSnapshot`, and content read methods using BlobStoragePort.

- [x] Write failing tests for Source → multiple Snapshots → raw/cleaned blobs → database metadata → restart readback.
- [x] Add failure injection proving a database rollback cannot leave a committed row pointing to a missing blob and that complete orphan blobs are tolerated.
- [x] Implement write-blobs-first, verify, then database-transaction commit; validate URI/hash pairs on both write and read.
- [x] Confirm responses contain logical BlobRefs only and raw/cleaned corruption raises the existing integrity error.

### Task 5: Boundaries, full validation, docs, and focused commit

**Files:**
- Modify: `ARCHITECTURE.md`
- Create: `docs/10-phase2-data-foundation-acceptance.md`
- Test: `tests/unit/investigation/test_boundaries.py`
- Test: `tests/integration/investigation/test_postgres_persistence.py`

**Interfaces:**
- Produces: recorded acceptance evidence and a focused Git commit on `feat/investigation-foundation`.

- [x] Add AST boundary tests forbidding imports from legacy market domain/services and a PostgreSQL integration test guarded by `MARKETPULSE_TEST_POSTGRES_URL`.
- [x] Run `pytest -m "not live" -q -p no:cacheprovider --basetemp=.codex-tmp/phase2-full`.
- [x] Run `ruff check src tests migrations`, `mypy src`, `uv build`, and an isolated Alembic upgrade/downgrade smoke test.
- [x] Record exact results, architectural deviations, and unresolved questions in the acceptance document.
- [x] Review `git diff --check` and secret/path scans, commit only phase files, push the feature branch, and verify the remote commit hash.
