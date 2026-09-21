# Phase 3 Acquisition and Recording Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build typed provider-neutral external-call ports, call-level recording/replay, deterministic document ingestion, and a source-acquisition vertical slice.

**Architecture:** Async ports isolate provider implementations; recording decorators persist canonical request/response envelopes to immutable Blob storage and append call records; replay adapters consume only exact successful recordings. A registry selects deterministic HTML/text/PDF parsers and SourceAcquisitionService persists the resulting immutable Snapshot/artifact bundle.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLAlchemy 2, Alembic, httpx, BeautifulSoup, pypdf, PostgreSQL, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-21-acquisition-recording-foundation-design.md`

## Global Constraints

- Do not implement full five-Agent prompts.
- Replay is fail-closed and cannot depend on network access or external API keys.
- SourceSnapshot and artifact payloads remain immutable and content-addressed.
- PDF citations target page artifacts, never transient or re-fetched content.
- External content is always untrusted data, regardless of source authority.
- Keep Investigation code independent of legacy market-domain contracts.

---

### Task 1: Recording Schema Evolution

**Files:**
- Modify: `src/marketpulse/investigation/domain/enums.py`
- Modify: `src/marketpulse/investigation/domain/recordings.py`
- Modify: `src/marketpulse/investigation/persistence/models.py`
- Modify: `src/marketpulse/investigation/persistence/repositories.py`
- Create: `migrations/versions/20260921_02_external_call_recording.py`
- Test: `tests/unit/investigation/test_recording_domain.py`
- Test: `tests/integration/investigation/test_recording_repository.py`

**Interfaces:**
- Produces: `ExternalCallStatus`; failure-aware `RecordedToolCall` and `RecordedModelCall`; ordered repository lookup methods; atomic persistence for Snapshot/artifact/gap bundles.

- [ ] Write failing domain tests for successful and failed call invariants, including repeated fingerprints.
- [ ] Add statuses, optional failure response fields, `attempt`, `config_version`, `completed_at`, `replayable`, and safe error metadata.
- [ ] Add an Alembic revision that removes fingerprint uniqueness, makes response fields nullable, and adds status/index constraints.
- [ ] Add repository list/lookup methods ordered by recording time and call ID.
- [ ] Run the focused domain, migration, and repository tests.

### Task 2: Typed Ports and Canonical Envelopes

**Files:**
- Create: `src/marketpulse/investigation/ports/__init__.py`
- Create: `src/marketpulse/investigation/ports/external.py`
- Create: `src/marketpulse/investigation/recording/canonical.py`
- Create: `src/marketpulse/investigation/recording/errors.py`
- Test: `tests/unit/investigation/test_external_ports.py`

**Interfaces:**
- Produces: `SearchRequest/SearchResult`, `FetchRequest/FetchResult`, generic `ModelRequest/StructuredModelResult`, `SearchPort`, `FetchPort`, `ModelPort`, and canonical fingerprint helpers.

- [ ] Write failing serialization/fingerprint tests, including binary Fetch bodies and version changes.
- [ ] Implement immutable typed request/result models and async protocols.
- [ ] Implement stable compact JSON envelopes and SHA-256 fingerprints.
- [ ] Add explicit provider/security/replay error types with stable codes.
- [ ] Run focused port and canonicalization tests.

### Task 3: Recording and Replay Adapters

**Files:**
- Create: `src/marketpulse/investigation/recording/__init__.py`
- Create: `src/marketpulse/investigation/recording/store.py`
- Create: `src/marketpulse/investigation/recording/adapters.py`
- Test: `tests/unit/investigation/test_recording_adapters.py`

**Interfaces:**
- Consumes: typed ports, canonical envelopes, BlobStoragePort, InvestigationRepository recording queries.
- Produces: `RecordingSearchAdapter`, `RecordingFetchAdapter`, `RecordingModelAdapter`, `ReplaySearchAdapter`, `ReplayFetchAdapter`, and `ReplayModelAdapter`.

- [ ] Write failing tests for successful recording, failure classification, typed replay, cache miss, corrupt payload, repeated calls, and no live fallback.
- [ ] Implement a repository-backed `RecordedCallStore` and injected call context/ID/clock providers.
- [ ] Implement recording decorators without altering wrapped-call return or error semantics.
- [ ] Implement replay adapters with exact request verification, typed schema validation, and per-fingerprint ordered cursors.
- [ ] Run focused adapter tests.

### Task 4: Live Provider Bridges

**Files:**
- Create: `src/marketpulse/investigation/adapters/__init__.py`
- Create: `src/marketpulse/investigation/adapters/search.py`
- Create: `src/marketpulse/investigation/adapters/fetch.py`
- Create: `src/marketpulse/investigation/adapters/model.py`
- Test: `tests/unit/investigation/test_live_adapters.py`

**Interfaces:**
- Produces: a legacy-public-search bridge behind SearchPort, an SSRF-safe HTTP FetchPort adapter with redirect/MIME/size controls, and an OpenAI-compatible structured ModelPort adapter.

- [ ] Write failing translation and security tests using fake transports/providers.
- [ ] Map the existing public search client behind the generic port without leaking legacy types.
- [ ] Implement guarded HTTP fetch with validation of every redirect target and PDF support.
- [ ] Implement structured model JSON validation without embedding domain-agent prompts.
- [ ] Run focused adapter tests.

### Task 5: Parser Registry, Normalization, and Locator Resolution

**Files:**
- Modify: `pyproject.toml`
- Create: `src/marketpulse/investigation/ingestion/__init__.py`
- Create: `src/marketpulse/investigation/ingestion/models.py`
- Create: `src/marketpulse/investigation/ingestion/registry.py`
- Create: `src/marketpulse/investigation/ingestion/security.py`
- Create: `src/marketpulse/investigation/ingestion/html.py`
- Create: `src/marketpulse/investigation/ingestion/plain_text.py`
- Create: `src/marketpulse/investigation/ingestion/pdf.py`
- Create: `src/marketpulse/investigation/ingestion/locators.py`
- Test: `tests/unit/investigation/test_document_parsers.py`

**Interfaces:**
- Produces: `DocumentParserPort`, `DocumentParserRegistry`, `NormalizedDocument`, HTML/text/PDF parsers, untrusted-content findings, and exact locator construction/resolution.

- [ ] Write failing parser-selection and exact-offset tests, including MIME/suffix conflicts.
- [ ] Add pypdf and implement content-signature media detection.
- [ ] Implement deterministic HTML/plain-text normalization and suspicious-instruction detection.
- [ ] Implement per-page PDF extraction and deterministic full/partial/scanned/error classification.
- [ ] Implement locator helpers that hash and resolve excerpts from persisted artifact bytes.
- [ ] Run focused parser tests.

### Task 6: Source Acquisition Vertical Slice

**Files:**
- Create: `src/marketpulse/investigation/services/source_acquisition.py`
- Modify: `src/marketpulse/investigation/persistence/repositories.py`
- Test: `tests/integration/investigation/test_source_acquisition.py`

**Interfaces:**
- Consumes: SearchPort, FetchPort, parser registry, BlobStoragePort, repository, deterministic IDs and clock.
- Produces: `SourceAcquisitionService.acquire(...)` and explicit discovered/fetched/parsed/evidence-eligible/valid statistics.

- [ ] Write a failing no-LLM Live fixture test from Search through exact locator resolution.
- [ ] Add atomic persistence for Snapshot, artifacts, and optional unreadable-source gaps.
- [ ] Implement source normalization, immutable Blob writes, parser dispatch, provenance, and validity classification.
- [ ] Add scanned and partial PDF integration cases.
- [ ] Add a Replay acquisition test using a new run and no live adapter/network/key.
- [ ] Run focused acquisition tests.

### Task 7: Real PostgreSQL CI and Case Fixture Layout

**Files:**
- Create: `.github/workflows/postgres-integration.yml`
- Expand: `tests/integration/investigation/test_postgres_persistence.py`
- Create: `case_data/east_palestine_2023/manifest.json`
- Create: `case_data/east_palestine_2023/{snapshots,blobs,tool_calls,model_calls,pdf_pages}/.gitkeep`

**Interfaces:**
- Produces: reproducible ephemeral PostgreSQL validation and a future-safe fixture layout with an official text-layer PDF candidate.

- [ ] Add PostgreSQL assertions for migrations, repository round trips, FK, JSONB, enum/check/index behavior, append-only triggers, and downgrade/upgrade smoke.
- [ ] Add an Ubuntu GitHub Actions job with an ephemeral PostgreSQL service and no repository credentials.
- [ ] Add a versioned case manifest that records structure and official PDF candidate metadata only.
- [ ] Push the branch, observe the public Actions run, and use systematic debugging for any failure.

### Task 8: Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Create: `docs/11-phase3-acquisition-recording-acceptance.md`

**Interfaces:**
- Produces: Phase 3 operating/architecture documentation and evidence-backed acceptance results.

- [ ] Document composition of Live versus Replay ports, parser limits, source validity, PostgreSQL CI, and the no-five-Agent-prompt boundary.
- [ ] Run all offline tests, the configured integration suite, Ruff, strict mypy, Alembic upgrade/check/downgrade smoke, and build.
- [ ] Review the Phase 3A-Q checklist line by line and record command outputs and known limitations.
- [ ] Commit only Phase 3 files, preserve unrelated untracked files, push the branch, and report the commit and CI result.
