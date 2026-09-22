# Phase 4.3 — Agent Feedback Loop Implementation Plan

1. Extend strict Agent contracts, prompt/version catalog, ModelPort-backed Agents and bounded repair.
2. Add bounded contexts, artifact selection, query/evidence/Claim guards, dedup, information gain,
   no-progress and ReportInput contracts.
3. Add step-scoped recorded external ports and generic UnitOfWork transaction operations so a
   verification result and Step checkpoint publish atomically.
4. Extend ResearchTask, RunBudget, ResearchGap, Evidence and Claim provenance with focused Alembic
   migration `20260922_05` and repository mappings.
5. Implement the feedback orchestrator and trace resolver, keeping every external call outside DB
   transactions and every final status inside ValidationPolicy.
6. Add unit coverage for the 24 required behaviors, two deterministic feedback integrations,
   conflict feedback, Agent-level no-network Replay, optional live smoke and PostgreSQL assertions.
7. Update README/ARCHITECTURE, produce `docs/14-phase4-3-agent-loop-acceptance.md`, run all local
   gates, commit, obtain explicit push authorization if needed, and verify real PostgreSQL CI.
