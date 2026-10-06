# Live Fetch and Body Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline; no delegation or Git mutations.

**Goal:** Resolve the confirmed local proxy DNS mismatch, extract actual article bodies, and make fetch/quality outcomes explainable without admitting unsupported evidence.

**Architecture:** Keep the existing HTTP contracts, manual redirect/DNS guard, source/artifact transaction pipeline and evidence gates. Enable the existing local proxy option only with user approval. Enhance the existing BeautifulSoup parser with semantic selection and a paragraph-density fallback; record safe diagnostics in existing recording metadata, snapshot provenance and structured logs.

**Tech Stack:** Existing Python/httpx/BeautifulSoup/Pydantic/SQLAlchemy/pytest; no new dependency or external reader service.

**Spec:** `docs/v5-taskC.txt`. Run `RUN-LIVE-68180c92a8cb4cb0`: 85/85 recorded fetches SECURITY_BLOCKED, zero snapshots; current public DNS answers are 198.18/15, local proxy option was false. User explicitly approved enabling only local config.

## Global Constraints

- No frontend, HTTP routes/DTO fields, status enums, evidence/hash/locator/validation/release policy changes.
- Default SSRF protections stay strict. Only `.env` receives approved `MARKETPULSE_ALLOW_PROXY_DNS=true`; keep localhost/private/literal fake-IP and unsafe redirect blocks.
- Read the historical database/blobs only; no real investigation, paid model call, server restart, or historical repair.
- Preserve prior A/B/v3/uv.lock changes. Inline on existing `ui-refactor`; unavailable worktree/finishing/TDD skills do not authorize Git mutations.

## Task 1: Evidence and local configuration

Files: `.env`, `scripts/diagnose_live_fetch.py`, this plan.

- [x] Inspect recorded statuses/budget/snapshot/source counts and safe DNS/config fields.
- [x] Obtain explicit proxy trust approval and enable only the existing local option.
- [x] Run read-only paired URL probe before code changes; retain original HTML under ignored `reports/taskc-fetch/before`.
- [x] Resolve all recorded unique hosts and classify original-run versus current-probe outcomes separately; never invent absent HTTP statuses.

## Task 2: Fetch diagnostics and bounded network behavior

Files: `investigation/adapters/fetch.py`, `recording/errors.py`, `recording/diagnostics.py`, `recording/adapters.py`, `live_runtime.py`; tests `unit/investigation/test_live_adapters.py` and `test_recording_adapters.py`.

Interfaces: `fetch(FetchRequest)->FetchResult` unchanged; optional internal `accept_language` constructor parameter. Existing error code/type families retained, with safe reason/diagnostic attributes on exceptions only.

- [x] Add failing tests for Accept/Accept-Language, HTTP 500 repair, 403 non-retry/cooldown, fake-DNS reason with strict mode, challenge classification and safe recording metadata.
- [x] Implement safe diagnostic reason codes, finite per-URL cooldown for hard denial/challenges, bounded existing retry and all 5xx support. No anti-bot bypass; other discovered URLs remain fallback.
- [x] Preserve per-hop DNS checks, MIME/byte cap, cancellation and redirect limits. Record only safe domain, status, bytes and reason; no exception body, request headers or credentials. Existing recording attempt fields stay unchanged.
- [x] Run targeted adapter/recording tests.

## Task 3: Body extraction and acquisition observability

Files: `ingestion/html.py`, `services/source_acquisition.py`, `feedback/orchestrator.py`; tests `test_document_parsers.py`, `test_source_acquisition.py`, `test_phase41_acquisition_uow.py`, `test_phase43_feedback_loop.py`.

Interfaces: Existing NormalizedDocument/AcquiredSource models unchanged. Quality diagnostics use existing warnings/gaps/provenance dictionaries; invalid content emits no evidence artifact.

- [x] Add failing tests: article excludes navigation; missing semantic selectors uses paragraph-rich container; long substantive article mentioning captcha is accepted; challenge/JS shell/search/tag/navigation/too-short content rejected with reason and length.
- [x] Implement semantic body → paragraph-density → cleaned plain-body fallback using existing BeautifulSoup, with minimum meaningful body length and link-density filtering. Keep full-page instruction assessment and exact normalized artifact bytes for locators; bump HTML parser version.
- [x] Expand only intentionally short valid test fixtures to realistic content while keeping their quoted facts and assertions unchanged.
- [x] Record domain/HTTP/body bytes/text chars/eligibility/filter reason/extraction method through safe logs and existing provenance. Record failed-fetch reason through existing gaps/metadata.
- [x] Deduplicate discovery source budget reservations against this run's existing snapshot sources and failure gap source IDs, not global inserted Source entities or snapshot-only sources. The global-entity approach broke live/replay budget fingerprints and was discarded. Preserve fetch-call vs valid-source semantics.
- [x] Run source/artifact/transaction/feedback regressions, including source-count and retained failure diagnostics.

## Task 4: Paired verification and handoff

- [x] Parse identical cached HTML before/after to isolate extraction from network changes; probe the same URLs again and present HTTP/body/filter comparison. Historical 0/85 versus explicitly configured network probe is separate from extractor comparison.
- [x] Run default backend suite: `.venv/Scripts/python.exe -m pytest -m 'not live and not infrastructure' -q`; inspect/fix failures then rerun.
- [x] Run whole src/tests plus diagnostic-script Ruff, compile/import, isolated server/report checks and pre/post OpenAPI SHA256; `git diff --check`.
- [x] Save `docs/v5-taskC-final-report.md` with category denominators, concrete file list, paired results, tests, dependency statement and limitations. Stop; user restarts backend and performs real end-to-end investigation.

## Final evidence

- Baseline: 384 passed, 3 skipped, 7 deselected; final: 405 passed, 3 skipped, 7 deselected. Final targeted suite: 68 passed.
- Same 11 public URLs: 10 HTTP 200, 1 control HTTP 404; 8 usable bodies, 2 navigation-page rejections. Isolated persistence: 10 sources/snapshots, 8 artifacts, 2 gaps; zero model calls.
- Fixed regression causes: isolated acquisition import cycle, live/replay budget counting, form-wrapped official documents and paragraph-adjacent factual fields. Reviewed case quotation content retained; bundled report E2E passes.
- No dependency additions, contract/schema changes, user database writes, server restart or real model investigation.
