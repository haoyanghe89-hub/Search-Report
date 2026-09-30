# LIVE run recovery implementation plan

**Goal:** Resume the same interrupted run with immutable step inputs, explicit unknown-call
consent and additive budgets, without replay-to-LIVE fallback or usage resets.
**Spec:** User approved the API/UI/checkpoint/version/uncertain-call/budget scope in this task.
**Architecture:** Existing audit table plus immutable blobs hold execution config, step inputs,
pause points and resume authorizations. Compare-and-swap run state before spawning one worker.
**Tech stack:** Python/Pydantic/SQLAlchemy, FastAPI, Vue, pytest and Node tests.

- [x] Add strict resume payload, recovery inspection, config/phase/checkpoint checks and atomic
  budget increments. Test stale requests, incompatible versions, exhausted budgets and no reset.
- [x] Pin original input for resumable-retrieval-v4 steps; reproduce call identities on restart.
  Test interrupted planning, research/verification inputs and missing/corrupt checkpoints.
- [x] Scope unknown-result consent to the exact intent IDs displayed to the user. Stop on a
  new unknown outcome; never turn an authorization into a global auto-retry policy.
- [x] Add GET recovery and POST resume endpoints and same-run task scheduling. Test saved
  response reuse, server recreation, cancellation and double-click concurrency.
- [x] Add recovery UI with unchecked consent, optional budget additions, clear version blocks,
  stale response protection and same-run refresh; test and build frontend.
- [x] Document supported workflows and limitations; run full offline tests, Ruff, mypy and
  frontend checks; export reviewable source and patch.

No automatic restart on server startup. Old workflow versions without pinned inputs fail closed.
Resume never changes accumulated usage or archived evidence, and never deletes historical reports.
