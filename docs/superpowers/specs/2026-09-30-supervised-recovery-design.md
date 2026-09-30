# Supervised automatic recovery design

User-approved scope: no login/authentication work; add process supervision, safe automatic resume,
stall alerts, paired database/Blob backups and isolated restore drills.

Keep one API worker. Acquire a database-scoped process guard before startup recovery (OS file lock
for SQLite, session advisory lock for PostgreSQL); a second process must fail before mutating runs.
Use Docker restart policies, and ship an alternative bare-process supervisor for local Windows/Linux.
Supervisor only owns its own child; intentional stop ends supervision. Health failures restart only
after a threshold, with bounded backoff; no second child before the first has exited.

The application scans at a configurable interval. Only interrupted and retryable failed LIVE v4 runs
are eligible. Never resume user-cancelled, budget-blocked, incompatible, corrupt, or unknown-outcome
runs automatically. Reuse existing preflight/CAS; automatic resume is a SYSTEM audit action, zero
budget increase, no unknown-call consent. Cap automatic attempts durably per run and back off between
attempts. A local stalled task must be confirmed stopped before another attempt can begin.

Persist deduplicated operational alerts in the existing audit table, log sanitized structured events,
and expose current alerts and watchdog health through an operations endpoint and console banner.
No outbound message destination is configured or contacted. An external uptime monitor remains needed
for host-wide outage notification. A dead scan loop makes readiness fail.

Backups pair a transactional database snapshot with immutable Blob content, hash manifests and
atomic completion. Restore requires fresh destinations; drills do not start the API or call providers.
Support SQLite directly and PostgreSQL native tools; do not claim PostgreSQL/Docker runtime validation
when those tools are unavailable locally. Keep failed backups distinguishable, never delete source data.

Acceptance: real subprocess termination/restart under the supervisor, exactly one child, automatic
resume of saved responses, no automatic unknown/cancelled/budget retry, persisted attempt limit,
stall alert deduplication, second-instance exclusion, corrupt backup rejection and actual isolated
SQLite restore drill. Existing offline tests and replay fail-closed behavior must keep passing.
