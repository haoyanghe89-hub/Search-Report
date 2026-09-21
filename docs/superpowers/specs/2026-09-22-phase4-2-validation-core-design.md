# Phase 4.2 — Evidence / Claim / Validation Core Design

## Boundary

The validation core is an Agent-independent package under `marketpulse.investigation.validation`.
It consumes immutable domain objects, source metadata, recorded semantic judgments, lineage, and
conflicts. It must not import Agents or Harness modules. Harness may call the core later.

## Modules

- `models.py`: strict typed validation inputs, integrity outcomes, semantic judgments, lineage,
  independence, source quality, conflict observations, profile results, and policy output.
- `integrity.py`: resolves Evidence → Snapshot → Artifact → Blob, checks recognized processor
  versions, resolves locators, and compares exact excerpt and hashes.
- `entailment.py`: semantic judge Protocol plus deterministic fake. Judgments never contain a
  ValidationStatus.
- `normalization.py`: contract validation for atomic Claim proposals; no general NLP parser.
- `lineage.py`: deterministic graph resolver using origin links, syndication clusters, and explicit
  attribution from metadata. Publisher/organization names are supporting basis, not identity.
- `independence.py`: counts independent provenance families rather than URLs or publishers.
- `quality.py`: multidimensional component assessment with an optional normalized helper score.
- `conflicts.py`: typed conflict detector plus an independent strong contradiction gate.
- `profiles.py`: eight explicit Python profile classes. No DSL or generic rules engine.
- `policy.py`: fixed 15-stage deterministic pipeline and ResearchGap derivation.
- `persistence.py`: append-only ValidationResult write plus atomic Claim latest projection.

## Integrity

Every referenced Evidence must exist and pass Snapshot, Artifact, Blob, locator, quote, and version
checks before it can contribute. Failures are typed and retained in validation basis. Invalid
Evidence is excluded from entailment, independence, quality, and sufficiency.

## Semantic judgments

`SemanticJudgment` uses ENTAILS, PARTIALLY_SUPPORTS, CONTRADICTS, NOT_RELEVANT, or UNCERTAIN and
stores semantic confidence separately from Claim confidence. A recorded model-call reference may
be replayed; policy status is always recomputed.

## Lineage and independence

The resolver builds deterministic connected components from explicit origin edges, shared
syndication clusters, and explicit attribution metadata. Each component becomes a stable family.
Unknown sources remain separate UNKNOWN families. The independence policy counts families with
valid, relevant Evidence and reports syndicated/duplicate members and primary/secondary counts.

## Quality and conflicts

Quality uses component findings for first-hand status, direct participation, primary-source nature,
data provenance, methodology, named sourcing, temporal proximity, retransmission, speculation,
independence, explicit uncertainty, and consistency with stronger evidence. No publisher brand
score is used.

Conflict detection compares typed observations. Time, scope, and definition metadata may resolve a
surface difference. Unexplained competing values remain unresolved; values are never averaged and
votes never erase conflicts. The strong contradiction gate executes before source sufficiency.

## Profiles and status

Eight typed profiles implement ClaimType-specific requirements: STATEMENT, INSTITUTIONAL_ACTION,
EVENT_FACT, QUANTITATIVE, CAUSAL, IMPACT, ATTRIBUTION, and ANALYTIC_INFERENCE. Status is a policy
result, independent of the confidence indicator. ANALYTIC_INFERENCE is capped at PROBABLE.

The fixed pipeline order is: existence, integrity, locator, entailment, lineage, strong
contradiction, independence, quality, profile sufficiency, conflicts, status, confidence,
validation basis, confidence basis, gaps.

## Persistence

A focused Alembic migration adds semantic judgments, source families/members, conflict evidence
relations and expanded append-only ValidationResult fields: policy/profile versions, input and
evidence hashes, lineage version, conflict refs, machine-readable basis, and confidence basis.
Claim stores a mutable latest-validation projection updated in the same transaction as insertion of
the immutable result. Database guards reject ValidationResult UPDATE and DELETE.

## Determinism

Canonical JSON hashing and stable sorting produce semantic-content-identical results for identical
inputs and policy versions. IDs and timestamps are persistence envelope data and are excluded from
the semantic comparison. Replayed semantic judgments are inputs; final status is never replayed.

## Exclusions

No real Agent reasoning, loop, Writer, report/release, Reviewer, public API, frontend, or Phase 4.3
gap scheduling is included.
