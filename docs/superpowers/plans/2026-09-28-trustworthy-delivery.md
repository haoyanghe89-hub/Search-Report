# Trustworthy investigation delivery implementation plan

Goal: complete the user-approved P0 fixes and deliver a usable evidence investigation demo against the supplied PDF.

Design: retain the Investigation domain, Harness, immutable recordings and report governance. Live and Replay must share that pipeline. Live runs use real external ports in a managed background job; the bundled replay uses explicitly curated, source-specific statements and judgments, never a generic entailment stub. Citation selection must fail closed on unresolved/non-supporting relationships and use the latest validation. The Vue UI consumes real API data, including steps, citations and preserved snapshots. Docker builds the Vue bundle and proxies the API. Missing keys produce an actionable error, not a hidden fixture fallback.

User approved this direction in the request following the gap assessment; implementation proceeds without a redundant design gate. Keep all work on fix/trustworthy-investigation. No public deployment or credentials committed.

## Task 1: semantic validation and report correctness
- [x] Add regressions for pending/non-entailed citations and latest judgment binding.
- [x] Persist semantic relation results consistently without weakening immutable history; materialize citations only from eligible latest judgments.
- [x] Repair source-family report scoping; cite factual timeline events; export useful source/quote metadata.
- [x] Run validation, reporting, replay and review tests.

## Task 2: live execution
- [x] Add a live run service using BoundExternalCalls, real search/fetch/model ports, existing Harness and ReportPipeline.
- [x] POST /investigations/{id}/runs starts live work and returns run_id immediately. Explicit case replay remains a separate route. Persist failures, handle missing credentials and shutdown.
- [x] Wire service lifecycle in investigation.server; add isolated tests proving an unrelated event uses injected live ports, never the bundled replay.

## Task 3: case reconstruction
- [x] Replace all-to-all evidence/claim fixture links and blanket ENTAILS with exact source excerpts and explicit per-pair recorded judgments.
- [x] Remove empty EPA redirect source; ensure ten meaningful sources and declared dates/classifications with independent secondary coverage.
- [x] Cover the eight required case questions, retain qualified/unknown findings and a real source-scope conflict, prove a feedback round.
- [x] Regenerate manifest, report and trace via real replay execution; test quote fidelity and mismatched evidence rejection.

## Task 4: frontend and Docker
- [x] Replace mock-backed data dependencies with real API data while preserving the original Vue 3 Folio design and layout.
- [x] Create tasks, run live/replay, poll real state, browse source/evidence/claims/conflicts/report, click citations to exact quotes and snapshots.
- [x] Add frontend Dockerfile/nginx proxy, correct Compose/env/README, scoped gitignore and locked frontend dependencies.
- [x] Build production frontend and test API contracts; browser smoke when runnable.

## Task 5: acceptance
- [x] Remove demo password bypass and fix test time dependence.
- [x] Run full unit/integration suite, Ruff, mypy, frontend build, offline replay, new-event checks.
- [x] Add CI for frontend/full offline suite/container build; document any environment-dependent checks not executed.
- [x] Produce acceptance evidence and a reviewable source deliverable with exact remaining limitations.
