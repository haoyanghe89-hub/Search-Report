# Phase 5 — Report Governance 验收记录

日期：2026-09-22。代码基线：`5581b85`（Phase 4.3 验收）+ 本阶段未提交工作区实现。本文件记录 Phase 5 本地验收；PostgreSQL CI 在提交推送后运行。

## 交付范围

- `reporting/hashing.py`：域分隔 canonical JSON SHA-256；mapping 键排序、set 规范化、runtime ID/时间戳天然排除。
- `reporting/models.py`：`ReportInputSnapshot`（semantic payload + runtime envelope 分离）、`Citation`/`CitationSemanticIdentity`、`ReportValidationFinding`、`ReleasePolicyEvaluation`（content-addressed evaluation_hash）。
- `reporting/assembler.py`：`ReportInputAssembler` 是 Phase 5 唯一读取 Phase 4.3 持久化状态的组件；fail closed（run 未 READY_FOR_REPORT、claim 缺 latest validation、投影 stale、跨 run evidence、conflict 引用未知 claim）；相同语义状态重复装配得到相同 `snapshot_hash`，幂等持久化。
- `reporting/writer.py`：`WriterProjection`（不含 URL/locator/quote hash/blob ref）、15 节 FULL/RESTRICTED + 7 节 STATUS 固定 schema、`NarrativeUnit`（content class + claim_refs）、`DeterministicWriter`（状态保真措辞；UNVERIFIED 仅以 "could not be established" 披露）。
- `reporting/citations.py`：`CitationFactory` 确定性物化 NarrativeUnit→Claim→ValidationResult→Relation→Evidence→Snapshot/Artifact→locator/quote→Source；drift/mismatch 产生 HARD finding。
- `reporting/validation.py`：`CitationValidator`（独立重验链与 hash）+ `ReportValidator`（schema 完整、unsupported content、qualifier loss、status wording、critical 遗漏、gap 披露）。
- `reporting/release.py`：`ReportReleasePolicy` 纯确定性；任何 HARD finding → `BLOCK/DRAFT/NOT_REQUIRED` 且不可降级；RESTRICTED/STATUS ceiling；governance gate 只产生 `REQUIRE_REVIEW/REVIEW_REQUIRED/PENDING`。
- `reporting/pipeline.py`：端到端装配→草案→引用→校验→策略评估→原子持久化（Report/ReportSection/Citation/finding/evaluation/projection）；REVIEW_REQUIRED 时自动开 ReviewRequest。
- `review/`：`ConfiguredReviewerAuthenticator`（Argon2id；DB 只存 config fingerprint）；`ReviewerSessionService`（opaque 256-bit token、DB 只存 token hash、固定 TTL、单 active session、HMAC 客户端指纹限流）；`review/api.py`（login/logout/me/decisions + Origin/CSRF/Idempotency-Key）；`review/service.py`（绑定校验、stale cycle 拒绝、硬门禁不可覆盖、原子决策写入、幂等回放）；`review/replay.py`（RecordedHumanReviewDecision 精确语义指纹匹配、免认证、release ceiling=RESTRICTED）。
- 持久化：migration `20260922_06_report_governance` 新增 12 张治理表并演进 `inv_reports`（append-only 版本表）/`inv_review_decisions`（认证溯源列）/`inv_runs`（follow-up 溯源列）；新不可变表全部安装 append-only 触发器。

## 验证

| 检查 | 结果 |
| --- | --- |
| Phase 5.1 单测（hash/snapshot/citation identity） | 4 passed |
| Phase 5.1 持久化 + migration 集成 | 5 passed（含 append-only 触发器、FK、唯一约束） |
| Phase 5.1 assembler 集成 | 9 passed（含 fail-closed 与 hash 稳定） |
| Phase 5.2 writer/validation 单测 | 11 passed |
| Phase 5.2 report pipeline 集成 | 2 passed（端到端引用报告 + drift fail-closed + 版本递增 hash 稳定） |
| Phase 5.3 release policy 单测 | 10 passed（决策矩阵、ceiling、governance 触发、hash 稳定） |
| Phase 5.4 review 生命周期 + API 集成 | 6 passed（登录/登出/me/CSRF/幂等/硬门禁拒绝/stale 拒绝/决策不可变） |
| Phase 5.5 review replay 集成 | 3 passed（指纹精确匹配、RESTRICTED ceiling、hard-gate 拒绝） |
| 全套离线 pytest | 220 passed, 7 skipped（skip 为 live/Windows symlink/PG 未配置） |
| Ruff check / format（Phase 5 路径） | 通过 |
| strict mypy（src/marketpulse） | 通过（除并行 Workstream B 的 api.py 在制品） |
| uv build | 成功 |
| Alembic upgrade/downgrade cycle（SQLite） | 通过（test_migrations.py） |
| PostgreSQL CI | NOT RUN（待提交推送后远端运行） |

## 冻结语义确认

- Writer 不是 Verifier/Citation authority/Release authority；Reviewer 不能覆盖 Hard Gate（`ReviewHardGateBlockedError`）。
- 任何 HARD finding → `BLOCK/DRAFT/NOT_REQUIRED`，无降级路径。
- Replay 真人审核：不登录、不算 Argon2、不建 session；语义指纹精确匹配；release ceiling=RESTRICTED。
- Evidence 不绕过 Claim；无 claim_refs 的 factual unit = `UNSUPPORTED_REPORT_CONTENT` HARD。
