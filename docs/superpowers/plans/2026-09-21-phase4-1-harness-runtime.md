# Phase 4.1 Harness Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a durable Investigation Harness and typed five-role contracts, ending the fake-agent mainline at READY_FOR_REPORT.

**Architecture:** Reuse the Phase 2 domain and Phase 3 external ports. Add explicit runtime models and a UnitOfWork whose short transactions own Step/checkpoint changes. Add persistent call binding and budget tables; no DB transaction spans external work.

**Tech Stack:** Python 3.11+, Pydantic 2, SQLAlchemy 2, Alembic, pytest, Ruff, strict mypy.

**Spec:** docs/superpowers/specs/2026-09-21-phase4-1-harness-runtime-design.md

## Global Constraints

- Implement only in this repository from commit 59b9bdc.
- Preserve legacy market behavior and listed untracked files.
- No ValidationPolicy, real Agent intelligence, report/release, public API, or frontend.
- Output, Step completion, and checkpoint update commit atomically.
- RunBudget uses monotonic active execution duration, excluding downtime.
- Replay call matching checks site, ordinal, fingerprint, schema, prompt, and config.

---

### Task 1: Runtime schema and migration

**Files:** Modify domain/runtime.py, domain/enums.py, persistence/models.py, persistence/repositories.py; create migrations/versions/20260921_03_harness_runtime.py and tests/integration/investigation/test_harness_persistence.py.

**Interfaces:** RunBudget; ExecutionStep.logical_step_key; InvestigationRun checkpoint and owner fields; CallBinding; repository CRUD-in-session methods.

- [x] Add failing SQLite migration and roundtrip tests for Step uniqueness, budget fields, call-binding uniqueness, and checkpoint.
- [x] Run the focused tests and confirm the missing schema failure.
- [x] Add typed models, ORM rows, Alembic upgrade/downgrade, and repository mapping.
- [x] Run focused tests and inspect SQLite schema; add PostgreSQL integration assertions (remote CI execution remains blocked).
- [x] Review with the other Phase 4.1 units and commit the verified implementation as f7425be.

### Task 2: UnitOfWork and state machine

**Files:** Create investigation/runtime/uow.py, state_machine.py, harness.py; test with tests/unit/investigation/test_harness_runtime.py.

**Interfaces:** UnitOfWork.begin_step(...), complete_step(...), fail_step(...), continue_run(...); repositories perform CRUD with a shared Session; Harness invokes handlers outside transactions.

- [x] Test legal and illegal transitions, rollback of outputs/Step/checkpoint, duplicate dispatch, and stale-owner takeover.
- [x] Confirm tests fail before implementation.
- [x] Implement short CAS transactions, durable logical keys, explicit Continue, and post-commit notification.
- [x] Verify failure/interruption and budget accounting with injected monotonic clock.
- [x] Review with the other Phase 4.1 units and commit the verified implementation as f7425be.

### Task 3: Agent contracts and fake mainline

**Files:** Create investigation/agents/contracts.py and ports.py; extend harness.py; add tests/unit/investigation/test_agent_contracts.py and tests/integration/investigation/test_harness_mainline.py.

**Interfaces:** Versioned frozen role inputs/proposals for Supervisor, Researcher, Analyst, Verifier, Writer; fake role Ports; route to READY_FOR_REPORT.

- [x] Write failing schema/reference/route tests and a fake-agent PLAN->COLLECT->ANALYZE->VERIFY test.
- [x] Implement bounded contexts and proposal validation; prohibit Agent status/release decisions.
- [x] Test Writer contract separately and assert no Report row is created.
- [x] Review with the other Phase 4.1 units and commit the verified implementation as f7425be.

### Task 4: Persistent call binding and budget

**Files:** Create investigation/runtime/calls.py; modify recording/adapters.py and persistence repository; test tests/integration/investigation/test_harness_call_bindings.py.

**Interfaces:** Bound Search/Fetch/Model operations take call_site_key and ordinal; binding stores exact recorded call identity; budget reservations persist before a new external call.

- [x] Test reuse after crash, duplicate fingerprint at two sites, exact Replay hit, version mismatch, and missing/corrupt payload.
- [x] Extend recording context with site metadata; add binding lookup and strict compatibility checks.
- [x] Test monotonic Step time and persistent cumulative call/token counters.
- [x] Review with the other Phase 4.1 units and commit the verified implementation as f7425be.

### Task 5: Acceptance and verification

**Files:** Create docs/12-phase4-1-harness-runtime-acceptance.md; extend PostgreSQL CI tests if needed.

- [x] Run focused and full offline pytest, Ruff, strict mypy, build, and SQLite migration smoke. PostgreSQL CI remains unrun because the remote push was rejected by auto-review and no local PostgreSQL service is available.
- [x] Record exact local command results and the PostgreSQL CI blocker in the independent acceptance document.
- [x] Recheck tracked/untracked status, review diff, and commit only Phase 4.1 files.
- [x] Report commit hash, changed files, contracts, state machine, UoW, bindings, budget, tests, CI, and limitations.
