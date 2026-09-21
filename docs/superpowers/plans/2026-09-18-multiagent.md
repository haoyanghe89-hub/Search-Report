# Four-agent Blackboard Implementation Plan

**Goal:** Convert MarketPulse into Master, Search, Analyst and Reporter roles with audited state.
**Architecture:** Supervisor-controlled blackboard; process-local dispatch, SQL persistence,
optional Redis notifications. Preserve existing entrypoints and report shape.
**Tech Stack:** Python 3.11+, Agents SDK 0.22.2, DeepSeek, Pydantic, SQLAlchemy, optional psycopg/Redis.
**Spec:** ../specs/2026-09-18-multiagent-design.md

## Global Constraints

Do not commit credentials. Work in a staged copy, retain unrelated original files, copy back
only reviewed changes. Do not claim independent worker deployment or automatic restart recovery.

## Task 1: Contracts, configuration and durable blackboard

- [x] Add domain/collaboration.py with SearchTask, ReviewDecision, ReportDraft, BlackboardState.
- [x] Add services/blackboard.py: create(state), load(run_id), save(state, actor, event), events(run_id).
  save uses `WHERE version = expected`, writes snapshot/event in one transaction, increments version.
- [x] Add notifications.py: publish only run_id/version/event after commit; failures are nonfatal.
- [x] Add explicit .env loading, SQL/Redis settings, optional server dependencies and Compose services.
- [x] Test persistence, isolation, optimistic conflict, event atomicity and environment precedence.

## Task 2: Four role implementations and coordinator

- [x] Keep ResearchPlan and MarketAnalysis contracts. Add SearchTask query selection, Master review
  action `research|report` and Reporter narrative with explicit source references.
- [x] Add role implementations to agents/team.py; invoke existing adapters only through harness.
- [x] Replace workflow with budgeted state dispatch. Persist started/completed/error events and
  role outputs. Main review may request one refinement; preserve original evidence IDs across rounds.
- [x] Keep structured analysis immutable during reporting; apply only validated narrative fields.
- [x] Test four-role invocation, refinement, duplicate work suppression, invalid citations and cancellation.

## Task 3: Integrate and verify

- [x] Expose blackboard trace through existing result/API plus a read-only run endpoint.
- [x] Update CLI report of run id, docs and .env example; configure provided key in ignored local .env.
- [x] Run `uv run pytest -m "not live and not infrastructure" -q`, `uv run ruff check src tests`,
  `uv run mypy src`, frontend test/build and a real-provider smoke.
- [x] Provide opt-in infrastructure tests; document skipped infrastructure validation honestly.
- [x] Hash-check original files, copy changed files back, sync environment and re-run checks there.
