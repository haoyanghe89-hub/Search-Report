# Task K Report Presentation Implementation Plan

> **For agentic workers:** Execute these checkboxes in order in the current session; preserve unrelated dirty-worktree changes.

**Goal:** Produce compact, deduplicated, layered investigation reports while preserving evidence and validation semantics.

**Architecture:** Carry report-only aggregation metadata through the immutable snapshot and writer projection, synthesize a compact draft, persist only non-empty sections, and make the Vue reader collapse appendix material. The HTTP response shape remains unchanged.

**Tech Stack:** Python 3.12, Pydantic, SQLAlchemy, FastAPI, Vue 3, Node test runner, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-03-task-k-report-presentation-design.md`

## Global Constraints

- Do not alter VERIFIED/PROBABLE/UNVERIFIED rules, citation integrity, source independence, anti-fabrication gates, or source data.
- Preserve the report HTTP schema.
- Preserve existing design tokens, responsive behavior, animation, and reduced-motion behavior.
- Do not overwrite unrelated working-tree changes.

---

### Task 1: Add report-composition regression coverage

**Files:**
- Modify: `tests/unit/investigation/test_phase5_writer_validation.py`

- [ ] Build a projection containing repeated same-type gaps, affected claims, and diagnostic strings.
- [ ] Assert compact sections, one gap group, one recommendation, appendix isolation, and no empty section.
- [ ] Run the focused test and confirm the old writer fails.

### Task 2: Carry aggregation metadata and compose the compact report

**Files:**
- Modify: `src/marketpulse/investigation/reporting/models.py`
- Modify: `src/marketpulse/investigation/reporting/assembler.py`
- Modify: `src/marketpulse/investigation/reporting/writer.py`
- Modify: `src/marketpulse/investigation/reporting/chinese_writer.py`
- Modify: `src/marketpulse/investigation/reporting/validation.py`
- Modify: `src/marketpulse/investigation/reporting/pipeline.py`
- Modify: `src/marketpulse/investigation/reporting/renderer.py`

- [ ] Preserve each gap's target claim stable key in the report snapshot/projection.
- [ ] Aggregate gaps by type and normalized meaning and pair each with one action.
- [ ] Separate technical diagnostics into `TECHNICAL_APPENDIX`.
- [ ] Emit answer-first summary, thematic findings, evidence basis, combined limitations/recommendations, and non-empty appendices.
- [ ] Persist/render only non-empty sections and adjust validation from a fixed exhaustive schema to compact required core sections plus an allow-list.
- [ ] Run focused backend tests until green.

### Task 3: Render compact reports and folded appendices

**Files:**
- Create: `frontend/src/utils/reportPresentation.js`
- Create: `frontend/tests/reportPresentation.test.js`
- Modify: `frontend/src/components/ReportDetail.vue`

- [ ] Add pure helpers that remove empty sections and classify appendices.
- [ ] Render core sections in the outline/body and appendix sections inside a closed `<details>` element.
- [ ] Keep citation interactions, layout tokens, responsive behavior, and reduced-motion intact.
- [ ] Run Node tests and the production build.

### Task 4: End-to-end verification and evidence

**Files:**
- Create: `docs/v7-taskK-final-report.md`
- Create/update: `frontend/test-results/task-k/*`

- [ ] Run full backend tests with an isolated basetemp and disabled cache provider.
- [ ] Run Ruff, import checks, and `git diff --check`.
- [ ] Run Playwright at desktop/mobile and reduced-motion settings; save screenshots.
- [ ] Run the same topic once at quick depth if quota permits and record source/evidence/claim/status counts and final section structure.
- [ ] Write the delivery report with before/after counts, verification results, screenshots, and remaining limitations.
