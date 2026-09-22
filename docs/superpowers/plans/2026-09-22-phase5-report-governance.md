# Phase 5 Report Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert Phase 4.3 ReportInput into immutable, cited, validated, policy-governed reports with optional authenticated human review and replay.

**Architecture:** A deterministic assembler creates a content-addressed snapshot. A bounded Writer emits typed narrative units; deterministic citation, validation, release, and review services own every trusted transition. Immutable report/review histories are separate from mutable session and latest-state projections.

**Tech Stack:** Python 3.11+, Pydantic 2, SQLAlchemy 2, Alembic, FastAPI, argon2-cffi, pytest, PostgreSQL 17.

**Spec:** `docs/superpowers/specs/2026-09-22-phase5-report-governance-design.md`

## Global Constraints

- Writer is not Verifier, Citation authority, Release authority, or repository reader.
- Reviewer cannot change Claim status or override a HARD finding.
- Any HARD finding produces `BLOCK / DRAFT / NOT_REQUIRED`.
- Semantic hashes exclude runtime IDs, timestamps, row order, and display ordinals.
- Rate-limit identity uses keyed HMAC; raw or plainly hashed client IP is never stored.
- The database stores neither reviewer plaintext/password hash nor raw session token.
- Governance history must remain valid after ReviewerSession cleanup.
- External calls, Blob reads, and semantic checks run outside long transactions.
- Do not commit/push until complete local gates pass and the user authorizes it.

---

### Task 1: Phase 5.1 — Immutable report input and persistence

**Files:**
- Create: `src/marketpulse/investigation/reporting/{__init__,models,hashing,assembler,persistence}.py`
- Create: `src/marketpulse/investigation/review/models.py`
- Create: `migrations/versions/20260922_06_report_governance.py`
- Modify: `src/marketpulse/investigation/domain/{enums,reports,runtime}.py`
- Modify: `src/marketpulse/investigation/persistence/{models,repositories}.py`
- Test: `tests/unit/investigation/test_phase5_reporting_models.py`
- Test: `tests/integration/investigation/test_phase5_reporting_persistence.py`
- Modify: `tests/integration/investigation/{test_migrations,test_postgres_persistence}.py`

**Interfaces:**
- Produces: `ReportInputSnapshot`, `ReportVersion`, `Citation`, `ReportValidationFinding`,
  `ReleasePolicyEvaluation`, `ReviewRequest`, `ReviewerSession`, `ReviewerAuthState`,
  `ReviewResearchRequest`, `canonical_hash()`, `ReportInputAssembler.assemble(run_id)`.

- [ ] Write failing unit tests for canonical semantic hashes, timestamp/runtime-ID exclusion, and stable source/citation fingerprints.
- [ ] Implement frozen typed models and canonical JSON/hash manifests.
- [ ] Write failing persistence/migration tests for all entities, FK/check constraints, and append-only guards.
- [ ] Add ORM mappings, repository operations, and Alembic upgrade/downgrade with SQLite/PostgreSQL guards.
- [ ] Write assembler fixtures over Phase 4.3 state and assert repeated assembly has the same semantic hash.
- [ ] Implement consistent-state assembly, projection consistency checks, and immutable snapshot persistence.
- [ ] Run Task 1 unit/integration/migration tests, Ruff, and strict mypy.

### Task 2: Phase 5.2 — Writer, citations, validation, and rendering

**Files:**
- Create: `src/marketpulse/investigation/reporting/{writer,citations,validation,renderer}.py`
- Modify: `src/marketpulse/investigation/agents/{contracts,model_agents,prompts,__init__}.py`
- Test: `tests/unit/investigation/test_phase5_writer_validation.py`
- Test: `tests/integration/investigation/test_phase5_report_pipeline.py`

**Interfaces:**
- Consumes: immutable `ReportInputSnapshot`.
- Produces: `WriterProjection`, FULL/RESTRICTED 15-section drafts, compact STATUS drafts,
  `CitationFactory.build()`, `CitationValidator.validate()`, `ReportValidator.validate()`, and
  deterministic Markdown/JSON rendering.

- [ ] Write failing contract tests for fixed schemas, atomic NarrativeUnits, and status-aware placement/wording.
- [ ] Implement bounded Writer projection and structured model-backed Writer without trusted citation fields.
- [ ] Write failing CitationFactory/Validator tests for provenance, locator/quote integrity, semantic entailment, and stable replay hashes.
- [ ] Implement deterministic CitationFactory and independent fail-closed CitationValidator without Claim-status mutation.
- [ ] Write failing ReportValidator tests for unsupported facts, qualifier loss, status upgrade, critical omission, and evidence-only bypass.
- [ ] Implement finding taxonomy, report validation, deterministic renderer, and atomic persistence operation.
- [ ] Run Task 2 focused tests, Ruff, and strict mypy.

### Task 3: Phase 5.3 — Deterministic release governance

**Files:**
- Create: `src/marketpulse/investigation/reporting/release.py`
- Create: `src/marketpulse/investigation/review/service.py`
- Test: `tests/unit/investigation/test_phase5_release_policy.py`
- Test: `tests/integration/investigation/test_phase5_review_lifecycle.py`

**Interfaces:**
- Produces: `ReportReleasePolicy.evaluate()`, immutable policy evaluations/review requests,
  material-change invalidation, and FULL/RESTRICTED/STATUS state transitions.

- [ ] Write table-driven failing tests for every decision-matrix row and release ceiling.
- [ ] Implement pure deterministic policy with strict HARD/GOVERNANCE separation.
- [ ] Write failing tests for expiry, version/policy drift, approval invalidation, and immutable projections.
- [ ] Implement review-cycle generation and binding checks without on-the-fly approval of stale cycles.
- [ ] Run Task 3 focused tests, Ruff, and strict mypy.

### Task 4: Phase 5.4 — Reviewer authentication and human review

**Files:**
- Create: `src/marketpulse/investigation/review/{auth,sessions,api}.py`
- Modify: `src/marketpulse/config.py`, `src/marketpulse/web_api.py`, `pyproject.toml`, `uv.lock`
- Test: `tests/unit/investigation/test_phase5_reviewer_auth.py`
- Test: `tests/integration/investigation/test_phase5_review_api.py`

**Interfaces:**
- Produces: `ConfiguredReviewerAuthenticator`, opaque session service, keyed client fingerprint,
  login/logout/me routes, authenticated review mutation, idempotency, and follow-up Run bridge.

- [ ] Add argon2-cffi and failing config/Argon2id-strength/redaction tests.
- [ ] Implement configured identity and password verification with no database password-hash copy.
- [ ] Write failing token-hash, TTL, single-generation, revoke, cleanup, and HMAC-fingerprint tests.
- [ ] Implement server-side sessions, rate buckets, config fingerprint, cleanup, and history-safe audit values.
- [ ] Write failing API tests for Cookie flags, Origin/CSRF, generic failures, identity injection, idempotency, and concurrent decisions.
- [ ] Implement routes and atomic APPROVE/REJECT/REQUEST_MORE_RESEARCH service, including rollback-then-best-effort failure audit.
- [ ] Run Task 4 focused tests, Ruff, strict mypy, and PostgreSQL concurrency tests when configured.

### Task 5: Phase 5.5 — Replay and integrated acceptance

**Files:**
- Create: `src/marketpulse/investigation/review/replay.py`
- Create: `tests/integration/investigation/test_phase5_replay.py`
- Create: `tests/live/test_phase5_writer_smoke.py`
- Create: `docs/15-phase5-report-governance-acceptance.md`
- Modify: `.github/workflows/postgres-integration.yml`, `README.md`,
  `docs/04-architecture-and-engineering.md`

**Interfaces:**
- Produces: exact-fingerprint `RecordedHumanReviewDecision` replay, no-auth replay path,
  RESTRICTED replay ceiling, and end-to-end acceptance evidence.

- [ ] Write failing replay match/mismatch tests with regenerated database IDs and stable semantic hashes.
- [ ] Implement recorded review adapter without passwords, sessions, or publication side effects.
- [ ] Add end-to-end FULL, STATUS, governance, stale approval, and replay scenarios.
- [ ] Extend PostgreSQL CI assertions for migration, append-only guards, concurrency, and report/review repositories.
- [ ] Update architecture language so all Hard Gate failures are `BLOCK / DRAFT`, then write acceptance evidence.
- [ ] Run focused Phase 5 tests, full offline pytest, Ruff check/format, strict mypy, build, Alembic upgrade/check/downgrade cycle, and PostgreSQL preparation.
