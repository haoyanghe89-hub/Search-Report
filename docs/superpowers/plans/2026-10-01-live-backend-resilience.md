# Live backend resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Bound recoverable proposal/search failures without accepting unsupported evidence or changing HTTP contracts.

**Architecture:** Move context-checkable duplicate task/query rejection into the existing structured repair loop. Convert exhausted follow-up/research/analysis proposals to application-authored blocked outcomes and gaps; retain actionable failed status reports for errors that cannot safely complete a step. Search each backend separately with a bounded timeout, retry, and per-client circuit state.

**Tech Stack:** Existing Python, Pydantic, asyncio, httpx, DDGS, SQLAlchemy, pytest.

**Spec:** `docs/v5-taskB.txt`; failed run is absent from both local SQLite databases and current API (404), so its exact throw site is not established.

## Global Constraints

- Do not change HTTP routes, request/response fields, external state meanings, or frontend files.
- Keep evidence hash/locator integrity, claim normalization, validation policy and release gates intact.
- Preserve prior persisted sources/steps; do not mutate or resume the historical failed run.
- No new search key or paid live investigation. Public probes only.
- Preserve dirty worktree changes. Execute inline on the existing non-main branch; unavailable Superpowers worktree/finishing skills are not substituted with Git mutations.

## Task 1: Proposal repair and controlled termination

**Files:** `src/marketpulse/investigation/agents/{model_agents,contracts}.py`, `feedback/{orchestrator,research_team}.py`, `live_runtime.py`; tests in `test_live_model_output.py`, `test_phase43_feedback_loop.py`.

**Interfaces:** `StructuredAgent(..., repair_attempts=2, sleep=asyncio.sleep)` remains an internal agent constructor; `.run(run_id)` retains `FeedbackLoopResult`; blocked outputs contain only existing typed proposals and ResearchGap records.

- [x] Write/run a failing unit test: `AsyncMock` raises `InvalidProviderResponseError` twice then yields `AnalysisProposal()`; assert 3 calls and sleep `[0.25, 0.5]` with the injected fake sleep.
- [x] Write/run failing tests rejecting a RouteProposal task matching `prior_task_summaries`, and a ResearchProposal whose queries all match `executed_queries`; require the existing repair hint to describe the safe application-authored issue.
- [x] Add bounded backoff to `_generate`, default two repairs, and exact-context duplicate checks to `validate_agent_proposal` (never fabricate replacement IDs or evidence).
- [x] Catch exhausted known proposal errors inside follow-up/research/analysis handlers; produce empty typed outputs, `Route.BLOCKED`, and actionable termination gaps. Initial planning/verification rejection remains an actionable FAILED status report, not a generic configuration hint.
- [x] Write/run integration regressions using existing `_seed_run`, `_orchestrator`, `TwoRoundModel` fixtures: repeat a follow-up task, return zero executable queries, and fail analysis parsing; assert BLOCKED, no new unsupported evidence/claims, prior sources/steps retained and status report buildable.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/unit/investigation/test_live_model_output.py tests/integration/investigation/test_phase43_feedback_loop.py -q`.

## Task 2: Per-backend search resilience

**Files:** `src/marketpulse/adapters/search.py`; `tests/unit/test_search.py`.

**Interfaces:** `search(query, limit=8)` and SearchCandidate fields unchanged. Constructor adds optional test-only backend order and monotonic clock injection. `_search_ddgs(query, limit, backend=...)` selects one installed backend, never `auto` or disabled Bing.

- [x] Write/run failing tests: HTML 500 then success has one bounded retry/backoff; repeated timeout/429 causes circuit skip on a later query and expiry permits recovery; fallback still reserves exactly one search unit.
- [x] Write/run failing tests: DDGS missing backend never calls `.text`; selected DDGS backend is single and valid; healthy fallback is preferred on the next query; all circuits open fails fast; cancellation does not retry.
- [x] Prioritize `ddgs:yahoo` based on the public probe; retain Bing HTML, DDGS Brave, DuckDuckGo HTML and DDGS Wikipedia as independent fallbacks. Downgrade Yahoo HTML to opt-in, and remove DDGS Bing from defaults.
- [x] Bound each provider to at most two attempts, a 25s overall query deadline, 5s HTTP/7s DDGS awaits, 60s cooldown (longer bounded cooldown for 429). Retain bounded references to timed-out DDGS tasks so repeated queries cannot spawn unbounded orphan threads.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/unit/test_search.py -q`.

## Task 3: Regression and handoff

- [x] Run full non-live/non-infrastructure pytest suite and inspect failures before fixing.
- [x] Run import/compile checks and relevant API/reporting integration tests; compare API OpenAPI schema to the pre-change snapshot.
- [x] Run `git diff --check`; confirm no new frontend/API route or schema changes.
- [x] Save root-cause limitations, concrete changes, red/green tests, public probe and final evidence in `docs/v5-taskB-final-report.md`. Stop without starting a real investigation or restarting the user's existing server.

## Execution evidence

- Final default regression: 384 passed, 3 skipped, 7 deselected (exit 0); targeted suite: 61 passed.
- Changed-file Ruff, compile/import and API/reporting integration checks passed. OpenAPI pre/post SHA256 is identical.
- Full report: `docs/v5-taskB-final-report.md`. Existing server was not restarted; no paid investigation started.
