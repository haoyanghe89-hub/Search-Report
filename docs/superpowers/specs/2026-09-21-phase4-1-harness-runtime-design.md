# Phase 4.1 Harness Runtime + Typed Agent Contracts

Approved by the user on 2026-09-21 for implementation from commit 59b9bdc.

## Scope

Build an Investigation-only persistent Harness, typed contracts for Supervisor, Researcher, Analyst, Verifier, and Writer, a Unit of Work, durable Step/checkpoint state, persistent external-call bindings, and a durable RunBudget. Fake-agent integration reaches VERIFYING -> READY_FOR_REPORT. Real ValidationPolicy, model intelligence, report generation/release, public API, and frontend are outside Phase 4.1.

## Transaction boundary

No transaction spans Search, Fetch, or Model calls. Recorded calls may commit independently. After validating the result and publishing/verifying immutable Blobs, one short DB transaction writes business outputs, marks the Step COMPLETED, and updates checkpoint and state_version. Notify and schedule only after commit. The UnitOfWork owns the shared Session, commit, rollback, and atomic Step completion; repositories own CRUD.

## Step identity and state

logical_step_key identifies workflow work (for example planning:initial or verify:claim:C-021). input_fingerprint hashes the canonical semantic input for a particular execution. Enforce UNIQUE(run_id, logical_step_key, attempt); index input_fingerprint without uniqueness. Persist current and last completed Step, dependencies, output contract version, workflow version, owner, and heartbeat. Explicit Continue reconstructs work from durable Step/artifact state. No automatic restart scanner.

## Persistent call binding

A binding includes run_id, logical_step_key, call_site_key, call_ordinal, request_fingerprint, recorded_call_id, operation, and schema/prompt/config versions. Resume or retry reuses a durable successful binding. Replay matches exact call-site identity and fingerprint/version fields; missing or incompatible entries fail closed. Never consume a different call merely because its ordinal matches.

## Budget

Persist research_rounds_used, search_calls_used, fetch_calls_used, model_calls_used, tokens_used, and consumed_wall_time_ms. Each Step accounts monotonic active duration on completion, failure, interruption, and heartbeat; downtime is excluded. Absolute investigation_deadline, if introduced, is a separate field.

## Agent boundaries

Frozen versioned Pydantic inputs and proposals define the five roles. Agents cannot write the DB, execute tools, assign durable IDs, choose final validation/release status, or mutate review state. Harness validates all references, routes, and budgets. Writer contract is schema tested only. The fake mainline stops at READY_FOR_REPORT.

## Acceptance

Crash and explicit resume, concurrent ownership, Replay binding and mismatch, transaction rollback, budget accounting, typed-contract rejection, SQLite/PostgreSQL migration, offline tests, Ruff, strict mypy, and build are required. Preserve legacy market regression and all preexisting untracked debug files.
