# Validation Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Execute inline on the existing user-owned workspace; no unrelated commits or reset.

**Goal:** Preserve exact evidence gates while restoring structured qualifiers, bounded PROBABLE grading and verification convergence.

**Architecture:** Read-only archived diagnostics first. Normalize only supplied qualifier fields, retain identity groups, retain VERIFIED prerequisites and define narrowly enumerated PROBABLE exceptions. Bound verifier admission before external calls, then report existing results without changing release gates.

**Tech Stack:** Python, Pydantic, SQLite, pytest; no new dependencies.

**Spec:** docs/v5-taskG.txt

## Global Constraints

- HTTP contracts/frontend unchanged; no unsupported verification or competing-value averaging.
- Preserve entity/time/scope and task D report reserves; never mutate historical run data.
- Initial paid E2E ownership was user-only. User later explicitly authorized one G6 isolated paid investigation after regression. Shared backend not restarted or taken over; no second run launched.

## Tasks

- [x] Save `reports/taskg/before-validation.json` using read-only `scripts/diagnose_validation_gaps.py`: latest Claim basis, exact missing fields and original evidence quotes. Do not infer absent facts from unexamined documents.
- [x] Add red tests in `tests/unit/investigation/test_validation_convergence.py`: supplied aliases remain grouped; empty time/scope do not count as numeric qualifiers; complete support VERIFIED; only missing methodology PROBABLE; missing unit/no ENTAILS/conflict remain unverified/disputed; official and anonymous quality distinction; bounded verifier admission.
- [x] Normalize supplied new-claim `qualifiers` and documented aliases in `agents/normalization.py`; preserve known existing Claim identity. Extend ANALYST_SYSTEM with an exact grouped quantitative example. Update verifier context to carry groups rather than nested envelopes.
- [x] Add traceability/completeness scoring from actually archived parsed material in `validation/quality.py`; do not guess first-hand/official status from domain popularity. Exact publisher hosts carry metadata and same-issuer family, not numeric authority bonuses.
- [x] Implement profile-specific PROBABLE rules in `validation/profiles.py`, retaining all current VERIFIED gates; persist grading reasons and missing fields in existing basis text. Carry supported findings through `reporting/chinese_writer.py` and live report selection; release policy unchanged.
- [x] Bound verifier batches, paid calls and tokens through `feedback/models.py`, `feedback/orchestrator.py` and `harness/calls.py`; stop before provider dispatch, preserve writer reserve and report completed results.
- [x] Run targeted red/green, archive comparison, full non-external pytest with independent basetemp and no cache, Ruff, compile/import, OpenAPI and diff checks. Save `docs/v5-taskG-final-report.md` with exact counts and limitations; do not claim paid publication success without evidence.

## Results

- Final full non-external regression: 486 passed / 3 skipped / 7 deselected / 1 warning, 189.43 s, exit 0. Basetemp `reports/taskg/pytest-release`, no cacheprovider.
- Final targeted fixes and profile/convergence/report regression: 52 passed, exit 0.
- Ruff, 22-file format check, compile/import and diff check: exit 0.
- Console OpenAPI baseline unchanged: `8a7ac4bb65c741aa7c54002ec9c12a1f75963da552e04e709547928429bdaf9e`.
- Archived 86 Claims / 837 validations: 85 UNVERIFIED, 1 DISPUTED. In-memory candidate regrading still 0 VERIFIED / 0 PROBABLE; no fabricated core qualifiers/entailment or archive writes.
- Subsequent user-requested recheck: 16 targeted passed, full regression 487 passed / 3 skipped / 7 deselected / 1 warning, 188.53 s, exit 0. Production code unchanged in this recheck.
- G6 executed once: `RUN-LIVE-031c3198d5e84b6c`, BLOCKED/REPORT at 24 verifier batches; 54 verifier calls, 735045 total tokens. 35 Sources / 60 Evidence / 55 Claims: 0 VERIFIED / 0 PROBABLE / 52 UNVERIFIED / 3 PENDING. INVESTIGATION_STATUS / REVIEW_REQUIRED; goal NOT achieved. See `docs/v5-taskG-G6-report.md` and updated verification manifest. No second paid run.

## Test commands

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/investigation/test_validation_convergence.py --basetemp=reports/taskg/pytest-targeted -p no:cacheprovider -q --tb=short
.venv/Scripts/python.exe -m pytest -m 'not live and not infrastructure' --basetemp=reports/taskg/pytest-full -p no:cacheprovider -q --tb=short
.venv/Scripts/python.exe -m ruff check src tests scripts
.venv/Scripts/python.exe -m compileall -q src/marketpulse scripts/diagnose_validation_gaps.py
git diff --check
```
