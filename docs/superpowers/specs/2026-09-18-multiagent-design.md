# Four-agent blackboard design

The user authorizes conversion of the existing market research application to four agents
and delegates the coordination/infrastructure choice. Preserve the CLI, API and ten-section
market report. This change does not add image geolocation or military tracking capabilities.

## Decision

Use a supervisor with a persistent blackboard, not peer-to-peer chat. Master creates the
plan and reviews analysis; Search chooses queries and invokes the existing search/fetch
adapters; Analyst produces evidence-bound analysis; Reporter composes the narrative while
the harness preserves structured facts, recommendation, confidence and citations.

All four roles use separate prompts and typed outputs through the existing Agents SDK / 
DeepSeek adapter. A coordinator dispatches roles based on committed state, bounds research
rounds and budgets, validates outputs and records progress. No role gets database credentials.

## Persistence and communication

SQLAlchemy blackboard: SQLite in local mode and PostgreSQL in server mode. One transaction
updates a versioned JSON snapshot and appends an event. Compare-and-swap rejects stale writes.
Each run has isolated state. Local execution invokes roles asynchronously in one process.
This is a multi-agent application, not independently deployed workers.

Optional Redis Pub/Sub announces committed run/version identifiers for live observers.
It is best-effort, never a task queue or the source of truth. Observers fetch database state;
missing Redis events do not lose committed results. Kafka/Pulsar/NATS and object storage
are unnecessary for this text-only workload. Markdown artifacts remain in reports/.

## Boundaries

Master may request at most one additional search round by default. Repeated queries and URLs
are skipped, all roles share one search/page/time budget. Failed or cancelled runs retain the
last committed state and a sanitized error category. Automatic crash recovery, distributed
workers and exactly-once external API calls are outside this change.

Explicit project .env loading with process environment precedence; no parent-directory scan.
Do not log/store model client settings, credentials, hidden reasoning or raw exception payloads.
Website content is evidence, never instructions. Citation checks are structural, not a proof
of factual truth. Existing source-type heuristics are not improved by this refactor.

## Acceptance

Verify four distinct model roles, a requested additional search, bounded loops, citation
rejection, confidence preservation, per-run isolation, stale writer rejection, event/snapshot
atomicity, persistence on error/cancellation, .env loading and redaction. Run existing Python
regressions, lint/type checks, frontend build/tests and a real DeepSeek smoke if available.
PostgreSQL/Redis tests are opt-in against dedicated test services; do not claim them executed
when the machine lacks those services.
