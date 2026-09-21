# Phase 4.2 — Validation Core Implementation Plan

1. Extend enums/domain contracts for semantic judgments, integrity errors, lineage, conflict
   resolution, rich gaps, and versioned ValidationResult while preserving Phase 4.1 compatibility.
2. Implement integrity, entailment, normalization, lineage, independence, quality, conflicts, eight
   profiles, and the fixed ValidationPolicy pipeline in an Agent/Harness-free package.
3. Add deterministic canonical hashing and a persistence service that inserts append-only results
   and atomically updates Claim latest projection.
4. Add Alembic `20260922_04` for semantic judgments, family relations, conflict evidence relations,
   indexes/FKs, rich conflict fields, and ValidationResult versioning fields.
5. Add focused unit tests for all sixteen mandatory cases and integration tests for persistence,
   append-only behavior, latest projection consistency, indexes/FKs, and migration checks.
6. Extend real PostgreSQL CI assertions, update architecture documentation, and write
   `docs/13-phase4-2-validation-core-acceptance.md`.
7. Run targeted and full pytest, Ruff, strict mypy, build, SQLite migration/check, commit, push the
   approved feature branch, and verify the real PostgreSQL GitHub Actions job before closing 4.2.
