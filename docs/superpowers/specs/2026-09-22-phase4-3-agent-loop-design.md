# Phase 4.3 — Real Multi-Agent Investigation Feedback Loop Design

## Boundary

Phase 4.3 composes the Phase 4.1 Harness, Phase 3 recorded external ports, and Phase 4.2
Validation Core. Supervisor, Researcher, Analyst, and Verifier are ModelPort-backed proposal
producers. They never own Step/Run lifecycle, persist business truth, set ValidationStatus, call
tools directly, or decide report release. Writer remains a typed ReportInput boundary only.

## Composition

- `agents/contracts.py` holds strict, extra-forbid bounded inputs and proposals.
- `agents/model_agents.py` builds versioned system instructions and user context separately, calls
  only ModelPort, and allows one bounded schema-repair call.
- `agents/prompts.py` owns prompt text and versions. Every source excerpt is wrapped as
  `UNTRUSTED_SOURCE_DATA` and is only placed in user content.
- `feedback/context.py` builds bounded Planner, Researcher, Analyst, and Verifier contexts and a
  canonical context fingerprint.
- `feedback/guards.py` owns deterministic query, evidence, Claim atomicity, and Claim dedup guards.
- `feedback/selection.py` chooses artifacts by current task, target question, primary-source value,
  open gaps, and conflict relevance under item/character limits.
- `feedback/orchestrator.py` executes the fixed Plan → Collect → Analyze → Verify loop, routes gaps,
  enforces budgets, calculates information gain, detects no progress, and creates ReportInput.
- `feedback/trace.py` resolves Claim-to-source, Claim-to-Agent-call, and Gap-to-follow-up-task paths.

Live and Replay differ only at composition: a live `BoundExternalCalls` has provider ports; Replay
uses the same call-site keys against a source run and has no provider. Step-scoped wrappers expose
ordinary SearchPort, FetchPort, and ModelPort contracts to services and Agents.

## Transaction boundary

External model/search/fetch calls, parsing, Blob publication, integrity validation, Claim
normalization, and ValidationPolicy execution happen outside database transactions. A completed
Step opens one short UnitOfWork that publishes business rows, applies typed transaction operations,
marks the Step complete, and advances checkpoint/state version. Validation persistence therefore
gets an in-session entry point; the verification Step inserts the append-only result, judgments,
families, conflicts and gaps and updates Claim latest projection in the same Harness transaction.

## Agent contracts

Planner sees investigation goal/scope/questions, qualitative coverage, gaps, task summaries and
remaining budget. It emits task proposals with target, purpose, priority, desired source types,
evidence characteristics and dependencies. On feedback it emits a RouteProposal and follow-up
tasks. Harness rejects unknown targets, illegal routes, duplicate tasks and budget excess.

Researcher sees one persisted ResearchTask, relevant gaps, previous normalized queries, family and
source summaries and remaining budget. It emits queries and stopping advice. A deterministic query
guard rejects empty, excessive, duplicate, repeated-task and unrelated queries before execution.

Analyst sees selected artifact excerpts and metadata, relevant Claims/Evidence and gaps. It emits
candidate Evidence, atomic Claim normalization proposals, relations, timeline candidates and
conflict observations. Harness resolves every locator against immutable artifact bytes before
creating Evidence. Composite Claims get one bounded decomposition proposal; failed repair becomes
an ANALYSIS_ERROR gap. Claim reuse uses canonical statement, ClaimType and normalized qualifiers.

Verifier sees one or a small bounded set of Claims, valid supporting/contradicting Evidence,
lineage, conflicts and typed profile expectations. It emits only semantic judgments, contradiction
interpretations, missing-evidence observations, possible conflict explanations and research
directions. Extra final-status/release fields fail Pydantic validation. Phase 4.2 Policy always
computes final status fresh.

## Persistence and traceability

A focused migration extends ResearchTask with target Claim, parent Gap/task, preferred source
types, suggested queries and round. It adds `max_sources/sources_used` to RunBudget,
`origin_validation_id` to ResearchGap, and analysis Step/task provenance to Evidence and Claim.
Indexes and FKs support task/gap/Claim trace queries. Model and tool calls remain linked through
ExecutionStep and CallBinding.

The resulting trace is:

`Claim → ValidationResult → Relation → Evidence → Snapshot → Artifact locator → Source`, and
`Claim → Analysis Step → Analyst ModelCall → ResearchTask → Researcher ModelCall/Search binding →
Source acquisition`. Feedback adds `ValidationResult → ResearchGap → follow-up ResearchTask`.

## Feedback, budgets, and termination

Policy gap types for missing evidence, independence, primary sources, source conflicts, causal
support/mechanism, quantitative conflict and attribution route to COLLECT. Analysis/decomposition/
extraction failures route to ANALYZE. Sufficient critical coverage with no blocking gap routes to
READY_FOR_REPORT.

RunBudget checks rounds, search/fetch/model calls, tokens, sources and active execution time before
work. Exhaustion produces BLOCKED with existing results and gaps intact. Each round calculates new
sources/families/evidence/Claims, resolved/new gaps, resolved conflicts, and validation transitions.
DISPUTED is treated as a distinct state, not a lower score. Configurable consecutive zero-gain
rounds stop with `NO_INFORMATION_GAIN`.

## Tests

Unit tests cover strict model contracts, prompt separation/injection treatment, bounded context,
query and evidence guards, Claim repair/dedup, verifier authority, routing, budget and no-progress.
Deterministic integration tests execute the required two-round independence improvement and the
conflict discovery/time-resolution loop through real Harness Steps and fresh ValidationPolicy.
Agent-level replay starts a new Run with new Step/Validation IDs, no providers or key, consumes
recorded Model/Search/Fetch calls, and recomputes Policy. A live model smoke is marked `live` and
skips without explicit credentials.

## Exclusions

No complete Writer, 15-section report, release policy, reviewer authentication, frontend, OCR,
distributed queue, legacy removal, or East Palestine publication acceptance is included.
