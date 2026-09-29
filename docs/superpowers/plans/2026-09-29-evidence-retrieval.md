# Evidence retrieval and evaluation implementation plan

**Goal:** Find and use archived evidence more accurately before scaling search.
**Architecture:** Keep legacy replay inputs intact. Introduce versioned deterministic
passage selection over immutable artifacts; persist actual model requests using the
existing recording store. Compare selection under identical context limits.
**Tech stack:** Python, Pydantic, existing SQLAlchemy/blob repositories, pytest.
**Spec:** User's September 29 instructions in this task.

## Constraints

- Replay misses fail closed; new strategies require separate LIVE/recording runs.
- No independent passage table; offsets are Python character indices in archived text.
- PDF offsets are page-local; keep page identity even for duplicate page content.
- Preserve original candidate evidence if grounding is ambiguous; integrity decides acceptance.
- Reuse persisted successful calls; uncertain calls require explicit retry/cost policy.
- Offline comparisons hold archive, model configuration and context budget constant.
- Synthetic fixtures test mechanisms only; 8–12 real events are a pilot, not proof of maturity.

## Tasks

- [x] Add `feedback/retrieval.py`: deterministic fixed-version splitting, bilingual BM25,
  document/passages ranking, unique passage identity and exact slice/hash/page preservation.
  Test evidence beyond the prefix, Chinese/English, duplicates, PDF pages, permutation
  determinism and all context limits in `test_retrieval.py`.
- [x] Wire strategy into `feedback/context.py`, config and new LIVE workflow version;
  retain default legacy behavior for old replay. Existing replay tests must pass.
- [x] Add grounding diagnostics outside model-output schemas, persist them in analysis
  execution results, use precise supplied positions to disambiguate repeated quotations.
  Test missing, repeated, whitespace-normalized and page-local quotes.
- [x] Raise Settings/env/Compose defaults together; retain overrides and hard limits;
  report exhausted budget dimension and used/max counts. Test configuration parity.
- [x] Add durable uncertain-call handling without claiming exactly-once provider billing;
  test saved-result reuse, crash window and explicit retry behavior.
- [x] Add offline evaluation CLI with validated source-span labels, a synthetic fixture
  and a pending real-event pilot manifest; document separate LIVE evaluation metrics.
- [x] Run focused tests, full offline suite and lint/type checks; inspect diff and export
  patch plus a concise Chinese delivery report with actual measured results/limitations.

## Verification and remaining evaluation work

307 offline tests passed (one Windows symlink skip; seven LIVE/infrastructure tests excluded).
Ruff and mypy over 141 source files passed. The synthetic comparison recovered 3/3
labeled spans versus 0/3 for truncation under the same 600-character limit.
The ten real events remain explicitly pending archival annotation and separate LIVE execution;
no claim of real-world quality improvement or production maturity is made.
