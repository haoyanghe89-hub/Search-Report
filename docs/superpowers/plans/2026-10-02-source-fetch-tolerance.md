# Source Fetch Tolerance Implementation Plan

> **For agentic workers:** Use executing-plans inline. Preserve the dirty branch; no delegation, worktree changes or commits.

**Goal:** A single inaccessible candidate must not discard other candidates or terminate a LIVE investigation.

**Architecture:** Extend the existing opt-in per-source exception boundary, not the LIVE exception handler. Persist an UNREADABLE_SOURCE gap and safe diagnostics for each skipped candidate; complete the normal research transaction with successful material. Use existing budget/policy-controlled termination and add actionable context only when no eligible snapshot exists.

**Tech Stack:** Existing asyncio, Pydantic, SQLAlchemy, httpx; no dependencies.

**Spec:** `docs/v5-taskE.txt`.

## Global Constraints

- No HTTP routes/DTO/enums/frontend changes, validation/release weakening, historical run rewriting or server restart.
- Retain task D context limits and phase reservations. Do not catch cancellation, replay/cache mismatch, model unknown outcomes or budget errors as source failures.
- Reuse the existing HttpxFetchAdapter retry/cooldown. No new network or paid investigation; user will restart and rerun.
- Independent `--basetemp=reports/taske/...`, `-p no:cacheprovider` for regression.
- Missing separate TDD/worktree/finishing skills: use inline failing-test → minimal fix → fresh regression; no Git mutations.

## Evidence

Read-only root DB: RUN-LIVE-42f0c4b9624c4b9c / COLLECT / FAILED; failed research:T-09-pricing-and-cost-effectiveness-audit:round-2, RATE_LIMITED, retryable=false. CALL-c546fb12e3344c538303fe4549d4beb7 records www.morphllm.com / HTTP_RATE_LIMITED / 429. RateLimitedError and ProviderCallError are siblings under ExternalCallError; SourceAcquisitionService.prepare catches only ProviderCallError, SecurityBlockedError and TimeoutError. bounded_map cancels siblings; harness records failed non-retryable research, then live_runtime catches the exception and marks FAILED; recovery rejects it.

## Task 1 — Red regression

**Files:** Create `tests/integration/investigation/test_source_fetch_tolerance.py`; reuse existing source and LIVE fixture helpers, no duplicate harness.

- [x] Exercise RateLimitedError, ProviderCallError 403/429, TimeoutError and SecurityBlockedError followed by an accepted candidate through `prepare(tolerate_fetch_errors=True)`, concurrency 1 and 3. Assert one valid result, no failed artifacts/snapshot, stable UNREADABLE_SOURCE reason, persistent domain/status action and safe log (no private exception text).
- [x] LIVE API via production service: mixed 429/timeout/success and all-429, sequential and parallel configuration. Assert research COMPLETED, no FAILED execution steps, successful evidence reaches verifier; all-429 yields REPORT/BLOCKED, no evidence, explicit retry/network advice, unchanged phase reserves, can_resume=true and no unknown model calls.
- [x] Prove strict opt-out and cancellation/budget/replay/integrity failures still propagate.
- [x] Run new tests before production changes: 14 failed / 5 passed, including RateLimitedError → LIVE FAILED.

## Task 2 — Minimal exception boundary

**Files:** `services/source_acquisition.py`, `feedback/orchestrator.py`.

- [x] Import RateLimitedError and add it to the existing `prepare_item` catch tuple; do not catch generic ExternalCallError/Exception.

```python
except (ProviderCallError, RateLimitedError, SecurityBlockedError, TimeoutError) as error:
    if not self._tolerate_fetch_errors:
        raise
```

- [x] Preserve stable reason and failed outcome fields. Use the URL host (no query) and validated numeric HTTP status in gap suggested_actions and acquisition_result logging; do not log exception text, credentials or bodies.
- [x] Enable `tolerate_fetch_errors=True` for sequential orchestrator SourceAcquisitionService, matching the existing parallel branch.
- [x] In existing `_blocked`, if no snapshot is evidence eligible and source-linked UNREADABLE_SOURCE gaps without snapshots exist, append `未获得可读取的合格来源；部分来源不可访问或被限流。请检查网络、稍后重试或提供可访问的原始材料。` to its detail. Do not misclassify parser rejection as HTTP denial. Keep budget reason, legal state transitions and recovery markers unchanged.
- [x] New tests: 19 passed; expanded adapter retry/cooldown/acquisition UoW: 40 passed. Full policy/recording regression retained.

## Task 3 — Fresh verification and handoff

- [x] Backend non-external full regression: 440 passed / 3 skipped / 7 deselected / 1 warning, 174.09s, exit 0, independent reports/taske/pytest-full and no cacheprovider.
- [x] Ruff, format check, compile/import, Investigation Console OpenAPI digest matches `8a7ac4bb65c741aa7c54002ec9c12a1f75963da552e04e709547928429bdaf9e`, git diff --check exit 0.
- [x] Save `docs/v5-taskE-final-report.md`: actual error chain, exact production file changes, fresh test results and limits. No historical auto-resume; real rerun/server restart left to user.
