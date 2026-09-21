# Investigation Data + Persistence Foundation Design

## Status and scope

This design implements the user-approved Phase 2A–2F contract. It adds the Investigation domain, formal PostgreSQL-compatible migrations, immutable source snapshot persistence, typed locators, and focused tests. It does not remove the legacy MarketPulse flow or implement agents, validation policy execution, report writing, replay runtime, OCR, or frontend work.

## Boundaries

The dependency direction is:

`investigation.domain <- investigation.persistence <- investigation.services`

The domain uses Pydantic value objects and enums only. It does not import FastAPI, SQLAlchemy, React, model providers, legacy `marketpulse.domain`, or local paths. Persistence uses SQLAlchemy 2.x and Alembic. Blob bytes remain behind `BlobStoragePort`; database rows contain only portable `blob://sha256/<digest>` references and hashes.

All entity primary IDs are globally unique opaque strings. Run-produced records (`SourceSnapshot`, `Evidence`, `Claim`, `ValidationResult`, `Report`, and recorded calls) carry `run_id`. A Replay run therefore creates new records while it may reuse immutable recorded blob payloads by hash. `Source` is investigation-scoped and represents a logical source; snapshots are immutable observations made by a specific run.

## Domain modules

- `enums.py`: all lifecycle, source, claim, validation, report, review, recording, and locator enums.
- `locators.py`: frozen discriminated `TextRangeLocator` and `PdfTextRangeLocator`, canonical JSON serialization, and strict deserialization.
- `runtime.py`: Investigation, InvestigationRun, ExecutionStep, and ResearchTask.
- `sources.py`: Source, SourceSnapshot, DocumentArtifact, and Evidence.
- `claims.py`: Claim, ClaimEvidenceRelation, ConflictSet, ValidationResult, ResearchGap, and TimelineEvent.
- `reports.py`: Report, ReportSection, ReviewDecision, and AuditEvent.
- `recordings.py`: RecordedToolCall and RecordedModelCall; request and response BlobRefs are mandatory.

Evidence and Claim are physically distinct types and tables. Evidence always references a concrete snapshot and typed locator. Claim-evidence stance and entailment live in a separate relation. ValidationResult and AuditEvent are append-only histories; Claim and Report retain only current projections.

## Persistence and migrations

ORM tables use the `inv_` prefix and explicit foreign keys, checks, uniqueness constraints, and indexes. PostgreSQL is the deployment target; SQLite is the deterministic unit/migration test backend. JSON columns use SQLAlchemy JSON with PostgreSQL JSONB variants. Enums are persisted as constrained strings rather than database-native enum types so schema evolution and SQLite tests remain predictable.

Alembic is the sole schema evolution mechanism for Investigation tables. The first revision creates the new tables without deleting or rewriting `mp_runs` or `mp_events`. Database triggers reject UPDATE and DELETE on immutable history/content tables. Downgrade removes only Investigation objects.

Important relational rules:

- Snapshot references Source and Run; Source has indexed canonical URL, origin, and syndication identifiers.
- Artifact references Snapshot; Evidence references Snapshot and optionally an artifact from the same snapshot.
- ClaimEvidenceRelation has a unique `(claim_id, evidence_id)` pair.
- ValidationResult and AuditEvent are insert-only.
- Conflict membership, timeline evidence, and report-section claims use normalized association tables.
- Blob reference/hash columns and operational run/step lookup columns are indexed.

## SourceSnapshot transaction flow

`SourceSnapshotPersistence.persist()` first stores and verifies raw and optional cleaned bytes through `BlobStoragePort`. It then inserts snapshot metadata in one database transaction. A database failure can leave unreferenced complete blobs, but cannot commit a row that points to a missing or partial blob. Reads resolve BlobRefs through the port, verify hashes, and never expose filesystem paths.

Snapshot fields are immutable after insert. Parser and normalizer changes create a new snapshot or artifact version; they never overwrite a prior payload.

## Error handling and validation

Domain constructors reject invalid BlobRefs, hash mismatches, confidence outside `[0, 1]`, invalid ranges, missing replay payloads, and inconsistent optional cleaned payload pairs. Persistence maps uniqueness and foreign-key failures to SQLAlchemy integrity errors so callers can distinguish contract violations. Blob errors preserve the existing safe error codes and do not disclose OS paths.

## Verification

Tests cover every core ORM entity, one-to-many snapshots, foreign-key enforcement, Claim/Evidence separation, relation stance and uniqueness, append-only histories, restart persistence, BlobRef portability and hash verification, locator round trips, mandatory recording payloads, migration upgrade/downgrade, and forbidden imports. A PostgreSQL integration test runs when `MARKETPULSE_TEST_POSTGRES_URL` is set; otherwise it is reported as skipped rather than silently simulated.
