# Stage Token Budget Implementation Plan

> **For agentic workers:** Use executing-plans inline; preserve the current dirty branch. No commits, worktree changes or delegation.

**Goal:** Bound model material and ancillary context, avoid paying repeatedly for unchanged semantic pairs, and protect verification/report headroom without changing evidence sufficiency.

**Architecture:** Opt-in LIVE configuration; deterministic extractive passage retrieval retains original offsets/hash. Scope provenance metadata to referenced sources. Keep every deterministic validation, reuse only previously checked semantic inputs/results with exact fingerprints. Check conservative model admission with in-flight allowance before dispatch; retain existing total token/call/time limits.

**Tech Stack:** Existing Python/Pydantic/SQLAlchemy/BM25/httpx, no new dependencies.

**Spec:** `docs/v5-taskD.txt`; current run usage diagnostics `reports/taskd/before/token-flow.json`.

## Constraints

- No HTTP routes/DTO/status changes; no frontend edits, source-quality/profile/release-gate weakening, old database repair, credential output or running-server restart.
- New real LIVE run authorized by D4; use the same stored investigation in a separate diagnostic database so existing runs remain untouched.
- Test with independent `--basetemp=reports/taskd/...` and `-p no:cacheprovider`.
- Skills requiring unavailable worktree/TDD/finishing packages use inline red-green verification; do not infer Git mutation authorization.

## Evidence

Recorded usage is 2,060,610 versus charged 1,981,109: final analysis response used 79,501 then binding failed. 136 calls: verifier 78 (42.44%), analyst 9 (30.20%), researcher 36 (25.18%), others 2.18%. Verifier repeatedly carries all source families (1,280,118 JSON chars across requests); analyst repeated passages plus open gaps/existing claims. 53 UNVERIFIED claims fail actual source-quality/independence/type requirements, not merely absent verifier dispatch. Do not claim a budget fix guarantees publishability.

## Task 1 — Reproducible diagnostics

- [x] Add `scripts/diagnose_token_flow.py`, validate blob hashes, save role/context/usage totals without prompt/body/secrets.
- [x] Extend field-size evidence and compare OpenAPI digest with task C's baseline.

## Task 2 — Bounded LIVE material

Files: `config.py`, `recovery.py`, feedback `models.py`, `context.py`, `retrieval.py`, `verification_team.py`; tests `test_retrieval.py`, new `test_stage_budget.py`.

- [x] Red-green tests: exact duplicate context coalescing with unchanged offsets/hash; relevant materials ahead of unrelated; LIVE limits and exact semantic reuse.
- [x] LIVE settings: 8 artifact sources / 16 excerpts / 24,000 body chars per analysis; ancillary context max 16 items and 500 chars per descriptive field; all configurable. Smaller contexts are extractive, never generated factual summaries.
- [x] Rank passages for relevance with existing source/current-task tie-breaking; coalesce identical artifact hashes. Preserve independent provenance in storage and validation. Approximate cross-source/overlapping dedup is deferred: do not mistake corroboration for redundant truth.
- [x] Scope verifier context to evidence-referenced sources, then worker subsets; retain selected claim/evidence semantics.
- [x] Prompt clarifies attributed company statements versus responsibility attribution and requires profile qualifiers; never automatically change claim types or infer world truth.
- [x] Targeted green verification.

## Task 3 — Reservations and semantic reuse

Files: new harness `stage_budget.py`, harness `calls.py`/`persistence.py`, feedback `orchestrator.py`/`semantic_reuse.py`, LIVE composition/recovery; tests new `test_stage_budget.py`, integration feedback/call tests. Policy lives below feedback to avoid circular imports.

- [x] Red-green pure tests: collection cannot consume verification/report floors; verification may consume its floor but not report floor; concurrent in-flight estimates included.
- [x] Keep 2,000,000 total tokens / existing wall clock; reserve 25% verification tokens and 2% report tokens, 15% verification calls and 1% report calls, bounded by configured total. Conservative dispatch estimate uses canonical UTF-8 request size plus output cap, not a claimed tokenizer count.
- [x] Admission before external dispatch and in-flight tracking within one owned run; previously recorded outcomes remain usable. Do not silently charge less than provider-reported usage.
- [x] Stop expanding collection at reservation floor, route existing claims through valid ANALYZE/VERIFY boundaries; exhausted outcome remains honest.
- [x] Reuse only exact semantic claim/evidence input fingerprints from immutable completed verifier checkpoint/proposal; still rerun integrity, quality, lineage and sufficiency policy for every selected claim.
- [x] Report retains supported findings on bounded termination; no conversion of unsupported claims into conclusions, release gate unchanged; inconsistent VERIFIED label alone remains DRAFT.
- [x] Targeted green verification including concurrency/cancellation, policy reexecution, retry/replay and budget accounting. Found and fixed recovery admission: do not resume into the same reserve rejection without enough added headroom.

## Task 4 — Final regression and authorized LIVE

- [x] Run backend full suite: initial 415 passed; current continuation 421 passed / 3 skipped / 7 deselected / 1 warning, 166.39s, independent reports/taskd/continuation/pytest-full and no cacheprovider. Ruff, compile/import, Investigation Console OpenAPI digest and git diff check exit 0.
- [x] Add a standalone real LIVE runner using Settings credentials in memory and an isolated DB; clone stored investigation/question fields, execute the production service once, save progress and final counts/report/type/release status.
- [x] Run same Gemini 4 Argon investigation with unchanged 2M total budget; no new real calls after terminal outcome unless user authorizes another run. Actual RUN-LIVE-d8f6e1dff6a84924 stopped at 295,714 known tokens on 3 unknown provider outcomes in VERIFY, not budget exhaustion.
- [x] User explicitly confirmed continuing: add exact-consent CLI recovery (6 tests), resume the same isolated run for the original 3 unknown verifier intents, no budget increases; save authorization/checkpoint/progress/new final separately. Original unknown calls were crossed; current run reached round 3 at 417,965 known tokens.
- [ ] D4 published-conclusion goal: not achieved. 34 UNVERIFIED / 0 PENDING / 0 VERIFIED; status report REVIEW_REQUIRED. External provider HTTP 402 interrupted researcher.official and cancelled 3 concurrent calls. Preserve 4 new unknown intents; do not infer unlimited retry consent or payment authority.
- [x] Update docs/v5-taskD-final-report.md with continuation metrics, safe HTTP error diagnostics, fresh verification, external 402 blocker and remaining quality gaps; no release override. Continue only after provider/account restoration and specific current unknown-call consent.
