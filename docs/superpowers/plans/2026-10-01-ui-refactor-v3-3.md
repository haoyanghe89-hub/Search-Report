# UI Refactor v3.3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Digital Folio a restrained investigation-file identity, then close the UI through an evidence-backed eight-dimension audit and full Playwright acceptance.

**Architecture:** Preserve every component interface and business path. Add the visual language in existing Vue templates and tokenized component styles; keep motion in the existing GSAP lifecycle, and verify the rendered application against its real replay data.

**Tech Stack:** Vue 3.4, Vite 5, GSAP/ScrollTrigger, Vitest, Playwright.

**Spec:** `docs/ui-refactor-v3-handoff.md` §5.3 plus the user-provided v3.3 acceptance brief.

## Global Constraints

- Do not modify `frontend/src/api`, business composables, the nine tab ids, props, emits, or data fields.
- Use only GSAP for scripted motion and source every visual value from `frontend/src/styles/tokens.css`.
- Keep `prefers-reduced-motion` content fully visible and clean up tweens, ScrollTriggers, media listeners, and event listeners on unmount.
- Preserve all v3.1 and v3.2 behavior.
- Do not commit without the user's confirmation.

---

### Task 1: Stabilize the v3.2 Baseline

**Files:**
- Modify: `frontend/src/styles/tokens.css`
- Modify: `frontend/src/styles/base.css`
- Modify: `frontend/src/styles/folio-ui.css`
- Modify: `frontend/src/components/Sidebar.vue`
- Modify: `frontend/src/components/TopBar.vue`
- Modify: `frontend/src/components/ReportDetail.vue`
- Modify: `frontend/src/views/InvestigationView.vue`

**Interfaces:** Consumes the existing component props/emits and produces the same interfaces with responsive and motion presentation only.

- [ ] Complete button/card/input/dialog/loading interaction states and the mobile drawer without changing emits.
- [ ] Complete report and mobile responsive rules at 1100px, 768px, and short-landscape boundaries.
- [ ] Run `npm run build`, `npm test`, and `git diff --check`; require exit 0 and 30/30 tests.

### Task 2: Add the Digital Folio Identity

**Files:**
- Modify: `frontend/src/styles/tokens.css`
- Modify: `frontend/src/styles/folio-ui.css`
- Modify: `frontend/src/components/SectionHeading.vue`
- Modify: `frontend/src/components/Timeline.vue`
- Modify: `frontend/src/components/ReportDetail.vue`
- Modify: `frontend/src/views/InvestigationView.vue`

**Interfaces:** Produces only presentational labels/classes derived from existing loop indexes and status values.

- [ ] Add editorial identifiers such as `SECTION 01`, `SOURCE 03`, and `EXHIBIT 04` from existing render indexes.
- [ ] Style evidence/claim validation badges as restrained monochrome stamps and source/evidence records as border-only index cards.
- [ ] Add a GSAP report-opening ritual no longer than 500ms, with immediate reduced-motion fallback and cleanup.
- [ ] Refine timeline dates into tabular case-time marks and align empty/loading states with the archive voice.
- [ ] Run the required build, test, and diff checks.

### Task 3: Eight-Dimension Closure

**Files:**
- Modify only the files named in Tasks 1-2 when a concrete audit issue is found.
- Record: `docs/ui-refactor-v3-3-audit.md`

**Interfaces:** Produces an audit ledger with initial score, concrete finding, resolution, and final score for typography, whitespace, hierarchy, color, motion, micro-interactions, responsive behavior, and originality.

- [ ] Audit one dimension at a time against rendered elements and source; make only evidence-backed changes.
- [ ] After each dimension, run `npm run build`, `npm test`, and `git diff --check`, and record the result.
- [ ] Stop only when each dimension scores at least 9.5/10 and has no obvious unresolved improvement within scope.

### Task 4: Full Playwright Acceptance

**Files:**
- Create: `frontend/test-results/v3-3/` screenshots and machine-readable acceptance output (ignored or removable generated artifacts).
- Modify source only to fix reproduced defects.

**Interfaces:** Exercises the live frontend/backend with no production interface changes.

- [ ] Test 1440×900, 1366×768, 1024×768, 768×1024, 390×844, 360×640, and 844×390 in both themes.
- [ ] Test reduced motion, all nine tabs, drawer, hover/focus states, report entry/progress/scrollspy/citation preview/dialog/version switch, and viewport overflow.
- [ ] Capture representative screenshots and collect unexpected console/page errors.
- [ ] Fix reproduced defects, rerun affected cases, then run final build, 30/30 tests, token/color grep, undefined-token audit, and `git diff --check`.
