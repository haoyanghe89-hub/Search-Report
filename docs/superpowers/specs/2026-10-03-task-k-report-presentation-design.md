# Task K Report Presentation Design

## Goal

Turn persisted investigation data into a concise, reader-facing report without changing claims, validation statuses, citations, source independence, or release decisions.

## Design

- Preserve the existing report-detail HTTP shape. Sections remain ordered objects with `section_type`, `content`, and `claim_ids`.
- Build only non-empty sections. Executive summary/status, evidence basis, and a combined limitations/recommendations section are the compact core. Findings appear only when supported material exists.
- Aggregate open research gaps by semantic gap type and normalized reason. Carry the target claim reference into the writer projection so one aggregated limitation can name all affected claims.
- Pair each aggregated limitation with its action in the same narrative unit. Do not emit a separate `NEXT_STEPS`/`CONCLUSIONS_AND_NEXT_STEPS` chapter.
- Classify provider error codes, exception class names, profile-policy internals, and machine diagnostics as technical material. Put them in `TECHNICAL_APPENDIX`; never repeat them in reader-facing sections.
- Keep no more than two concise methodology/credibility disclosures in the reader-facing report. Scope, questions, method, and diagnostics are appendix material and default to collapsed in the UI.
- Filter legacy empty sections in the frontend as a compatibility backstop. Historical reports remain readable.

## Verification

- Add a backend regression with multiple claims, duplicate gaps, and technical diagnostics.
- Assert answer-first summary, semantic aggregation, paired actions, no internal diagnostics in the body, no duplicate advice, and no empty persisted sections.
- Add frontend presentation helpers/tests for empty-section filtering and appendix classification.
- Run focused tests, full backend tests in an isolated basetemp, Ruff, import checks, frontend tests/build, Playwright responsive/reduced-motion checks, and one real quick rerun when provider quota permits.
