# Phase 5 Report Governance Design

Date: 2026-09-22. This specification freezes the approved Phase 5 architecture. It does not
include the Investigation Console, East Palestine live acceptance, legacy removal, OCR, or
public multi-user IAM.

## Trust boundary and data flow

The only Phase 5 component allowed to query Phase 4.3 persisted business state is
`ReportInputAssembler`. It produces an immutable, content-addressed `ReportInputSnapshot`.
The Writer receives only a bounded projection of that snapshot and cannot query repositories,
search, fetch, alter Claim status, or emit trusted URL, locator, quote, hash, or source metadata.

The fixed flow is:

```text
Phase 4.3 state -> ReportInputAssembler -> ReportInputSnapshot -> WriterProjection
-> structured draft -> CitationFactory -> CitationValidator -> ReportValidator
-> ReportReleasePolicy -> optional Human Review -> PUBLISHED / RESTRICTED / REVIEW_REQUIRED
```

`snapshot_hash` is SHA-256 over canonical semantic input only. Runtime IDs, row IDs,
`assembled_at`, process-local values, and temporary ordering metadata are excluded. A separate
stable `source_state_fingerprint` covers Claim stable keys, latest Validation semantic hashes,
relations, Conflict/Gap/Timeline state, Artifact/Snapshot hashes, citation material, and relevant
schema/policy versions. Database state versions are concurrency controls, not semantic identity.

## Writer and report schemas

The Writer emits typed NarrativeUnits with prose, content class, wording class, Claim refs,
optional Evidence selection intents, and typed placement. It may compress or combine compatible
Claims, but every factual or analytical unit must remain semantically contained by its Claim refs.
Evidence never bypasses Claim.

`FULL_INVESTIGATION` and `RESTRICTED_INVESTIGATION` use the fixed 15-section schema:

1. EXECUTIVE_SUMMARY
2. SCOPE_AND_MANDATE
3. INVESTIGATION_QUESTIONS
4. METHODOLOGY
5. SOURCE_COVERAGE
6. TIMELINE
7. VERIFIED_FINDINGS
8. PROBABLE_FINDINGS
9. DISPUTED_FINDINGS
10. QUANTITATIVE_FINDINGS
11. CAUSAL_AND_MECHANISM_ANALYSIS
12. ACTOR_AND_ATTRIBUTION_ASSESSMENT
13. CONFLICT_ANALYSIS
14. LIMITATIONS_AND_RESEARCH_GAPS
15. CONCLUSIONS_AND_NEXT_STEPS

Restricted sections may be `CONTENT`, `NOT_APPLICABLE`, or
`INSUFFICIENT_SUPPORTED_MATERIAL`. `INVESTIGATION_STATUS` uses a compact seven-section schema:
EXECUTIVE_STATUS, SCOPE_AND_MANDATE, INVESTIGATION_QUESTIONS, SEARCH_AND_SOURCE_SUMMARY,
AVAILABLE_FINDINGS, BLOCKING_GAPS_AND_LIMITATIONS, and NEXT_STEPS.

Content classes are FACTUAL_ASSERTION, ANALYTICAL_SYNTHESIS, GOVERNANCE_DISCLOSURE, and
PRESENTATIONAL. VERIFIED may be stated within its exact qualifiers. PROBABLE requires explicit
uncertainty. DISPUTED must remain unsettled. UNVERIFIED may only be disclosed as not established.
The most restrictive status governs merged Claim refs.

## Citations and validation

`CitationFactory` deterministically materializes citations from
Claim -> current ValidationResult -> ClaimEvidenceRelation -> Evidence -> Snapshot/Artifact ->
typed locator/exact quote -> Source. It never searches, fetches, creates Evidence, or trusts Writer
metadata.

`CitationValidator` independently verifies the complete chain, immutable bytes, content hashes,
locator resolution, quote hash, Evidence-to-Claim entailment, and NarrativeUnit-to-Claim scope.
It never changes Claim status or replaces ValidationPolicy. NOT_ENTAILED, INCONCLUSIVE, or a
material inconsistency with recorded semantic judgment produces a HARD finding and fails closed.
Claim status can change only through fresh Evidence/Judgment -> ValidationPolicy -> append-only
ValidationResult.

`citation_hash` uses stable semantic identity: snapshot/claim-set hashes, section/unit stable keys,
Claim/Validation semantic hashes, relation semantics, Evidence content semantic hash, canonical
locator, quote hash, Artifact/Snapshot hashes, stable Source identity, entailment version, and
schema versions. Runtime IDs, replay-created row IDs, timestamps, and display ordinals are
excluded.

`ReportValidator` checks schema completeness, unsupported content, Claim scope, qualifiers,
status-aware wording, citation completeness, and critical Claim/Conflict/Gap coverage. Any factual
content without a current Claim ref is `UNSUPPORTED_REPORT_CONTENT` and a HARD finding.

## Release and review governance

`ReportReleasePolicy` is deterministic. Any HARD finding yields exactly
`decision=BLOCK`, `release_status=DRAFT`, `review_status=NOT_REQUIRED`; it can never be downgraded
to a restricted release. RESTRICTED means integrity-valid content whose report type or governance
ceiling permits only restricted distribution.

ReportType and ReleaseStatus are independent. Changing report type or report content requires a
new immutable ReportVersion and the full Writer/Citation/Validator/Policy flow. FULL is the only
type that can be PUBLISHED. RESTRICTED and STATUS have a RESTRICTED ceiling. Governance-only
triggers may create an immutable ReviewRequest with exact report/snapshot/claim/citation,
validator, policy, and evaluation-hash binding.

APPROVE applies only the target precomputed by policy. REJECT applies the precomputed rejection
target. REQUEST_MORE_RESEARCH creates an append-only request and a fresh follow-up
InvestigationRun; it never reopens the completed run or changes Claim status. Material Claim,
Evidence, Citation, report, schema, validator, policy, or governance-profile changes invalidate
applicability of old approvals and require a new evaluation/review cycle.

Expired ReviewRequests remain immutable. If bindings and versions remain exact, a new cycle may be
created. Version or policy drift requires fresh validation, policy evaluation, and review request;
an old cycle can never be approved after an on-the-fly policy recomputation.

Successful review mutation atomically writes ReviewDecision, AuditEvent, report projection, and
optional ReviewResearchRequest. Failure rolls back the whole mutation. A safe failed-attempt audit
may be written only afterward in a best-effort separate transaction.

Recorded HumanReviewDecision replay uses exact semantic fingerprint matching, never interactive
authentication. Replay can reproduce the decision path but has a RESTRICTED release ceiling and
never performs real publication.

## Reviewer security

V1 has one server-configured reviewer: `REVIEWER_ID`, `REVIEWER_DISPLAY_NAME`, and an Argon2id-only
`REVIEWER_PASSWORD_HASH`. Authentication creates a 256-bit opaque token held only in an HttpOnly,
SameSite=Strict Cookie. The database stores only a domain-separated token hash. TTL is fixed;
logout revokes immediately; a new login invalidates the previous active session.

Production Cookie mode is Secure and host-only. Secure=false requires an explicit loopback-only
demo configuration. Login/logout/review mutations require exact Origin allowlisting, JSON content,
a custom CSRF header, and strict credentialed CORS. Review identity is injected from the session;
client reviewer IDs are rejected.

Rate-limit client identity is
`HMAC-SHA256(rate_limit_fingerprint_secret, normalized_client_address)`. Raw addresses and plain
hashes are not persisted. Only explicitly trusted proxies may supply forwarded addresses. The
secret is never logged, persisted, or returned.

`reviewer_config_fingerprint` is a domain-separated cryptographic fingerprint/HMAC derived from
current reviewer ID/password-hash configuration. Only the final fingerprint is persisted; the
password hash is never copied into the database.

ReviewerSession is credential material and may be deleted after retention. ReviewDecision,
AuditEvent, and RecordedHumanReviewDecision store immutable reviewer ID, session public ID,
decision origin, and authentication provenance values without a required long-lived FK to the
session row.

## Persistence and transaction boundary

ReportInputSnapshot, ReportVersion, ReportSection, Citation, ReportValidationFinding,
ReleasePolicyEvaluation, ReviewRequest, ReviewDecision, ReviewResearchRequest,
RecordedHumanReviewDecision, and governance AuditEvent are append-only. ReviewerSession,
ReviewerAuthState, rate buckets, idempotency records, and latest report projections are controlled
mutable state.

Model calls, Blob reads, locator resolution, and semantic validation occur outside long database
transactions. A final short transaction persists the immutable report graph, findings, policy
evaluation, lifecycle event, and latest projection atomically.

## Acceptance boundary

Acceptance requires deterministic hashes across repeated assembly and replay; FULL and compact
STATUS output; unsupported/status-upgraded prose rejection; exact citation/entailment validation;
deterministic release decisions; non-overridable Hard Gates; version-bound review actions;
Argon2id/session/rate-limit/CSRF/idempotency/concurrency coverage; recorded review replay with no
true publication; real PostgreSQL migration/repository/concurrency assertions; and full offline
pytest, Ruff, strict mypy, build, and Alembic gates.
