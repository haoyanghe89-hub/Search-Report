# Parallel research implementation plan

**Goal:** Run complementary research agents concurrently, expand bounded public-web coverage, and preserve recorded evidence validation.

**Architecture:** Keep the durable coordinator as the sole phase-transition writer. Inside its research step, run official, independent, technical and counter-evidence researchers in parallel, merge/deduplicate their proposals fairly, and execute bounded concurrent acquisition. Use stable per-query call sites and shared URL admission to avoid repeated fetches. Verification remains an evidence-gated phase. Cancellation must drain all workers before the durable step exits.

**Tech stack:** Python asyncio, Pydantic, existing SQLAlchemy call budgets and Vue 3.

## Constraints
- Retain offline replay compatibility with concurrency defaults of one in FeedbackLoopConfig.
- LIVE defaults: 120 logical searches, 300 fetched sources, 6 rounds, 1800 seconds, 4 researchers, 4 concurrent searches and 8 fetches. Counters include failed attempts; engine fallback HTTP requests are not logical searches.
- Never label finite search as exhaustive; keep no-progress and budget termination reasons.
- No concurrent commits to a shared workflow phase. Preserve validated-relation-only citations.

## Tasks
- [x] Add bounded worker utility with ordered results, strict concurrency, cancellation draining and error propagation. Test overlap and cancellation.
- [x] Add complementary model researchers with unique recorded call sites, deterministic round-robin query merge and bounded model allocation. Test distinct contexts, overlap and deduplication.
- [x] Add parallel acquisition, per-batch URL admission and stable call sites. Test duplicate URLs and call/source caps; preserve serial replay path.
- [x] Wire larger configurable LIVE budgets, model/token caps and concurrency. Update env docs and tests.
- [x] Expose runtime workers in progress UI through actual recorded call/step data where available; label scope accurately.
- [x] Run affected integration suites, complete lint/type checks, rebuild UI if changed, and update delivery artifacts. Validate runtime configuration before restart; do not interrupt active investigations.

