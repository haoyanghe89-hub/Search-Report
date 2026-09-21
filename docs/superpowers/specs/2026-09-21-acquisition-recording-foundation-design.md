# Phase 3 Acquisition and Recording Foundation Design

## Status

Approved by the product owner on 2026-09-21. This document turns the approved Phase 3A-Q contract into repository-local architecture. It does not authorize the five domain-agent prompts.

## Goal

Create provider-neutral Search, Fetch, and Model ports with call-level recording and fail-closed replay, plus a deterministic source-acquisition pipeline that persists immutable HTML, plain-text, and text-layer PDF observations as exact-locatable artifacts.

## Boundaries

- Future Investigation agents depend only on typed ports. Concrete HTTP, search, and model SDK details remain in adapters.
- Recording is a decorator concern. Agents and acquisition code never call persistence helpers directly.
- Replay uses recorded nondeterministic inputs and freshly executes deterministic acquisition logic. It never restores a final Investigation state and never falls back to live providers.
- Source acquisition creates Sources, SourceSnapshots, DocumentArtifacts, and unreadable-source ResearchGaps. It does not create Claims, perform causal analysis, or write reports.
- External document content is always untrusted data, including official sources.

## Typed External Ports

`SearchPort.search(SearchRequest) -> SearchResult`, `FetchPort.fetch(FetchRequest) -> FetchResult`, and generic `ModelPort.generate(ModelRequest[T]) -> StructuredModelResult[T]` are async protocols. Requests include the semantic input plus explicit schema, prompt, and runtime-config versions needed for fingerprinting. Responses are immutable Pydantic models. Binary fetch bodies use deterministic base64 JSON serialization.

Live provider adapters implement these ports. Recording and Replay adapters implement the same ports, so mode selection happens at composition time rather than with `if replay_mode` branches in agents or services.

## Canonicalization and Recording

Every recording decorator performs this sequence:

1. Canonicalize the typed request as sorted, compact UTF-8 JSON.
2. Include operation, schema version, prompt version, and relevant runtime-config version in the fingerprint envelope.
3. Store that request envelope in the content-addressed Blob Store.
4. Execute the wrapped live adapter exactly once.
5. On a complete typed response, store the response envelope and append a successful recorded call.
6. On timeout, rate limit, provider error, invalid response, security block, or cancellation, append a non-replayable failed call and re-raise the original semantic error.

Recorded statuses are `SUCCESS`, `TIMEOUT`, `PROVIDER_ERROR`, `RATE_LIMITED`, `INVALID_RESPONSE`, `SECURITY_BLOCKED`, and `CANCELLED`. Response references are optional for failed calls. `SUCCESS` is replayable only when a complete response Blob exists and validates.

The Phase 2 uniqueness constraint on `(run_id, operation, request_fingerprint)` is removed because retries and repeated identical calls are distinct observations. Calls carry an `attempt` and are ordered by `(recorded_at, call_id)`. Replay consumes successful matching calls in recorded order; exhaustion is an explicit cache miss.

## Fail-Closed Replay

Replay adapters are constructed with a source recording run ID and a new Replay run context. They query only the source recording run for exact operation and fingerprint matches, then:

- read the request and response Blobs through `BlobStoragePort`, which verifies SHA-256;
- verify the canonical request bytes still match;
- validate the response against the current typed schema;
- return the typed value.

Missing, exhausted, mismatched, or non-successful recordings raise `REPLAY_CACHE_MISS`. Corrupt bytes raise `BLOB_INTEGRITY_ERROR`. Replay adapters have no live-adapter reference and therefore cannot silently access the network or an LLM.

## Document Parsing

`DocumentParserRegistry` selects a `DocumentParserPort` implementation from declared Content-Type plus content signature. Magic bytes and actual content win over URL suffix: HTML served from a `.pdf` URL is HTML; `%PDF-` content at an extensionless URL is PDF.

All parsers return a common `NormalizedDocument` containing parse status, deterministic normalized text, artifact candidates, warnings, evidence eligibility, and untrusted-content findings.

- HTML removes non-content executable/style nodes and emits one stable UTF-8 normalized-text artifact.
- Plain text performs deterministic decoding, Unicode normalization, newline normalization, and emits one stable artifact.
- PDF preserves the raw PDF and emits one artifact per reliable page. A document-level normalized text Blob is also stored to satisfy immutable Snapshot completeness, but PDF citations may target only page artifacts with `PDF_TEXT_RANGE`.

`TEXT_RANGE` and `PDF_TEXT_RANGE` offsets are character offsets into persisted normalized artifact text. Locator resolution re-reads the artifact Blob and verifies the exact excerpt hash.

## PDF Usability Policy

The PDF parser deterministically evaluates total pages, extracted character count, meaningful-page count, and text density. It maps outcomes to `PARSED`, `PARTIALLY_PARSED`, `UNSUPPORTED_SCANNED_PDF`, `INSUFFICIENT_TEXT_LAYER`, `CORRUPT_DOCUMENT`, `ENCRYPTED_PDF`, `EMPTY_CONTENT`, or `PARSE_FAILED`.

Only reliable pages become page artifacts. Blank/scanned PDFs retain raw Snapshots, are not evidence-eligible or valid for source statistics, and create an `UNREADABLE_SOURCE` gap with reason `SCANNED_PDF_REQUIRES_OCR`. Partial PDFs keep reliable page artifacts and create a warning/gap for unreadable pages.

## Untrusted Content Boundary

Every parser applies the same basic suspicious-instruction detector after normalization. Detection never executes or promotes embedded instructions. Snapshot provenance records `external_content_trust=UNTRUSTED`, the detector version, a boolean alert, and finding codes. Source credibility and instruction trust remain independent.

## Source Acquisition Service

The non-agent `SourceAcquisitionService` performs:

`Search -> Source normalization -> Source persistence -> Fetch -> raw Blob -> parser registry -> normalized/page Blobs -> atomic Snapshot/artifact persistence -> source-validity result`.

Raw bytes are written first to the immutable Blob Store. Parsing operates on those exact bytes. Because SourceSnapshot rows are append-only, final parse metadata and all artifact rows are committed in one database transaction after parsing; no Snapshot row is mutated after insertion.

A source is valid for case statistics only when it has an acquired Snapshot, supported usable parsed content, provenance metadata, and evidence-eligible artifacts. Discovery or successful HTTP fetch alone is insufficient.

## PostgreSQL Verification

GitHub Actions supplies an ephemeral PostgreSQL service. CI applies Alembic upgrade, runs repository and recording tests against PostgreSQL, verifies FK/JSONB/enum/index and append-only behavior, then exercises downgrade/upgrade smoke. No persistent credential enters the repository. SQLite remains a fast local test backend, not evidence of PostgreSQL correctness.

## Phase 3 Acceptance

- Recording and Replay tests cover successful Search/Model calls, exact hits, misses, corrupt Blobs, failures, repeat attempts, and absence of live fallback.
- Parser tests cover HTML, text, text-layer PDF, scanned PDF, partial PDF, media mismatch, extensionless PDF, injection flags, and exact locator round trips.
- A no-LLM vertical test performs Live acquisition and then acquisition Replay into a new empty run using the same deterministic pipeline.
- Real PostgreSQL CI is green, alongside full pytest, Ruff, strict mypy, and wheel/sdist build.
- East Palestine fixture directories and a manifest placeholder identify at least one official text-layer PDF without embedding a final report or conclusion.

## Explicit Non-Goals

- Full Supervisor/Researcher/Analyst/Verifier/Writer prompts or harness orchestration.
- OCR, image extraction, JavaScript rendering, or arbitrary office-document parsing.
- Final East Palestine investigation, expected conclusions, or a prewritten report.
- ValidationPolicy, claim generation, or report release behavior changes.
