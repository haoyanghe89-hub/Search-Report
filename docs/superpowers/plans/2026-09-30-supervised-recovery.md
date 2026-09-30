# Supervised Recovery Implementation Plan

**Goal:** Automatically continue safe interrupted runs and provide supervised execution, alerts and paired recovery backups.
**Architecture:** Single guarded API process, durable audit-backed automatic retry policy, platform-neutral child supervisor, immutable paired archives.
**Tech Stack:** Python, asyncio, SQLAlchemy, FastAPI, Vue, SQLite/PostgreSQL, Docker Compose.
**Spec:** ../specs/2026-09-30-supervised-recovery-design.md

## Global constraints
No login/authentication changes. No auto consent for unknown outcomes. No automatic budget increase.
Do not restart user-cancelled runs. Restore only into fresh paths/databases. No external notifications sent.

- [x] Process ownership: operations/ownership.py; acquire before startup mutation; release on shutdown.
  Verify two processes cannot own one SQLite database; PostgreSQL uses session advisory lock.
- [x] Automatic recovery: operations/watchdog.py plus Settings and RunRecovery automatic policy.
  Test persisted retry counts/backoff, unknown/cancelled/budget/version blocks, recorded-response reuse.
- [x] Alerts/readiness: audit event IDs deduplicate by run/state/code; operations endpoint and Vue banner.
  Test stale heartbeat alerts, unhealthy watchdog, secret-free messages, retry limits.
- [x] Supervision: operations/supervisor.py; restart its own child after exit/unhealthy streak, bounded
  backoff and intentional shutdown. Test real child kill/restart with files recording process IDs.
- [x] Paired backups: operations/backup.py and backup_cli.py, SQLite snapshot/PG dump, immutable Blob
  manifest, verify/restore/drill; test corruption, traversal, occupied destination, real isolated drill.
- [x] Deployment/docs: Compose restart/init/grace-period settings, ops tools image/profile, environment
  examples and scripts for scheduling backup without adding user automations or changing host services.
- [x] Verification: targeted failure tests, full offline pytest, Ruff/mypy, frontend tests/build. Export
  source and patch; sync to remote main under existing user authorization (delivery step).
