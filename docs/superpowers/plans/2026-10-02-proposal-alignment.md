# Task F: proposal alignment and bounded repeated work

Scope: preserve HTTP contracts, frontend, EvidenceIntegrityValidator, ValidationPolicy,
release policy and task D stage budget reservations. Work inline on the existing dirty
branch; do not restart the server or rewrite historical runs.

## Evidence

- RUN-LIVE-5ef5e23234794a22 used 213261 tokens, not 13261; 21 claims persisted,
  17 verifier calls, zero VERIFIED. Four task analyses eventually passed references.
- Analysis T-02 and T-05 initially failed on missing nested locator.quote_hash.
  The LIVE prompt says to omit quote_hash although the nested locator requires it.
- T-05 repairs failed with root value_error. Invalid raw responses were not archived;
  their exact local-reference/duplicate failure cannot be recovered retrospectively.
- Actual recorded model is deepseek-flash, not deepseek-chat. No evidence yet warrants
  guessing another model name or changing the user's provider configuration.
- prepare() finds an existing Source but still fetches and parses it again, creating
  new snapshots. Analysis feedback has no per-task ceiling beyond global budget.

## Execution / review checkpoints

1. [done] Save hash-checked complete archived analysis responses and comparisons.
2. [done] Add red tests for missing nested hash normalization, actionable local-reference
   error codes, unchanged rejection of invented references/quotes, and source reuse.
3. [done] Align the prompt and candidate parser; compute missing quote hash only from the
   provided quote, never change supplied hashes/IDs/offsets. Full archive integrity
   remains mandatory. Add opt-in analysis-only raw response capture to isolated runner.
4. [done] Reuse only accepted, persisted source snapshots in the same run, preserving exact
   artifact IDs. Deduplicate batch URLs without skipping queries or inflating counts.
   Bound per-task analysis feedback and persist an actionable controlled stop.
5. [done] Run targeted regression then full backend tests (unique basetemp, no cache), Ruff,
   compile/import, OpenAPI fingerprint and git diff --check.
6. [attempted; final E2E handed to user] Execute a fresh same-topic LIVE investigation in an isolated database,
   capture analysis responses before validation, persist progress and report actual
   verified counts / report type / release status. No automatic unknown-call retry.
7. [done] Save final report including missing historical raw-output limitation and any unmet
   end-to-end target. Do not claim publication if quality gates remain unmet.

## Final evidence / deviation

- First fresh run captured seven complete raw analysis responses. The repeated rejection
  was input-known existing Claim keys referenced in relations/conflicts but not included
  in the output's local claims list. Lossless normalization closes this list only for
  exact known definitions; fabricated refs and changed definitions still fail.
- Exact stored entity/time/scope groups must be restored instead of nesting the whole
  qualifiers envelope into entity. All 18 archived Claims reuse unchanged IDs/status.
- Offline replay: 7/7 structure/reference PASS, 38/42 archive-integrity PASS; the four
  nonmatching quotes remain rejected. No diagnostic candidates written to run data.
- Source S-a902a55307bcef05069acf90a7347641: five accepted snapshots before, one after.
- Final paid attempt RUN-LIVE-020b536dece14824 failed on a connection error with an
  unknown model-call outcome, before any analysis response. No paid unknown retry.
  Final qualifier patch is offline-verified only; publication target is not achieved.
- Final regression: 452 passed / 3 skipped / 7 deselected, exit 0; Ruff/import/compile,
  format and diff checks pass, Console OpenAPI fingerprint unchanged. Detailed report:
  docs/v5-taskF-final-report.md. No model switch, dependencies or HTTP/frontend changes.

## Offline handoff (2026-10-02)

- User confirmed restored network and explicitly owns backend restart and paid final E2E;
  no further live runs or unknown-call retries are authorized for this task.
- Fresh offline replay: 7/7 structure/reference PASS; 38/42 archive integrity PASS,
  four invalid quotes still rejected. All 18 existing Claims reuse unchanged objects;
  entity/time/scope groups each match 18/18. Diagnostic candidates not persisted.
- Fresh targeted tests: 9 passed, exit 0; Ruff and diagnostic format/compile pass.
- Only diagnostic group-result fields, report and verification manifest changed at handoff.
  Production patch is unchanged. Final release outcome remains pending user E2E.
