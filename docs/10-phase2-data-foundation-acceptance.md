# Phase 2 Investigation Data + Persistence Foundation 验收

日期：2026-09-21

本阶段只建立 Investigation Data + Persistence Foundation。旧 MarketPulse 继续作为 regression baseline；未删除 legacy API/domain，也未实现五 Agent、完整 Parser/Verifier/Writer、Replay runtime、OCR 或前端。

## 交付内容

- 纯 Pydantic Investigation Domain：19 个要求实体、typed lifecycle/source/claim/report enums、Evidence/Claim 分离。
- Typed locator：`TEXT_RANGE` 与 `PDF_TEXT_RANGE`，canonical JSON round trip。
- SQLAlchemy 2 persistence：24 张 `inv_` 表和规范化关系表，显式 FK/unique/check/index。
- Alembic revision `20260921_01`：可从包含 legacy `mp_runs` 的 baseline 升级并降级，只操作 Investigation schema。
- append-only DB guards：SourceSnapshot、DocumentArtifact、Evidence、ValidationResult、ReviewDecision、AuditEvent、RecordedToolCall、RecordedModelCall 禁止 UPDATE/DELETE。
- SourceSnapshot vertical slice：Source → Snapshot → raw/cleaned Blob → DB metadata → restart readback。
- Replay recording persistence contract：request/response BlobRef 均为必填，只有 hash 不能构造 replay-eligible call。
- migration 与 Alembic 配置同时进入 wheel/sdist，安装产物包含 schema revision。

## 表与关系

核心表包括 `inv_investigations`、`inv_runs`、`inv_execution_steps`、`inv_research_tasks`、`inv_sources`、`inv_source_snapshots`、`inv_document_artifacts`、`inv_evidence`、`inv_claims`、`inv_claim_evidence_relations`、`inv_conflict_sets`、`inv_validation_results`、`inv_research_gaps`、`inv_timeline_events`、`inv_reports`、`inv_report_sections`、`inv_review_decisions`、`inv_audit_events`、`inv_recorded_tool_calls`、`inv_recorded_model_calls`，以及 question/conflict/timeline/report 的规范化关联表。

关键约束：Evidence 必须引用 Snapshot；artifact locator 如存在必须与 Evidence 使用同一 Snapshot；Claim-Evidence pair 唯一；Validation/Audit 历史追加保存；Source canonical URL、lineage、run/step、BlobRef/hash 和关系查询字段均有索引。

## 验证结果

| 验证 | 结果 |
| --- | --- |
| Investigation focused tests | 22 passed，1 PostgreSQL integration skipped |
| 全量 Python offline regression | 92 passed，4 skipped，2 live deselected |
| Ruff `src tests migrations` | passed |
| strict mypy `src` | 53 source files passed |
| Alembic SQLite smoke | upgrade head/current/downgrade base passed |
| `uv build` | wheel + sdist passed |
| wheel content | Investigation package、Alembic config 和 `20260921_01` revision 均存在 |

四个 skipped：未配置专用 PostgreSQL/Redis 测试服务、Windows 不假定非特权 symlink 创建能力。主机没有可用 `docker` 命令，故 PostgreSQL integration 本阶段未实际执行；测试已实现，配置 `MARKETPULSE_TEST_POSTGRES_URL` 后会启用。

## 调试与已修复问题

- uv 默认用户缓存目录受当前沙箱 ACL 限制；确认根因后仅为本任务使用 `.codex-tmp/uv-cache`，未改用户全局配置。
- Alembic 程序化测试曾被全局 `MARKETPULSE_DATABASE_URL` 覆盖；增加显式 `Config.attributes["database_url"]` 优先级，CLI 仍使用环境变量。
- 无 ORM relationship 时，同事务新增 parent/association 的 flush 顺序不确定；Repository 先 flush 主记录，再在同一事务追加关联行。
- Alembic autogenerate 的 PostgreSQL JSONB repr 需要显式 `Text` import，并经过 Ruff 格式化；migration upgrade/downgrade 已重跑。

## 架构偏差与限制

- 已批准的本阶段要求优先于原迁移表中的 Phase 1b 顺序；generic Model/Search/Fetch recording adapters 尚未实现，但新 Investigation code 不依赖 legacy market domain。
- 本阶段只有 locator contract，没有 HTML/PDF Parser；DocumentArtifact 数据模型已为版本化处理结果预留。
- PostgreSQL 是目标 schema，当前机器只完成 SQLite migration smoke；PostgreSQL 集成用例因无专用服务而跳过，不宣称实机通过。
- ID 使用全局唯一 opaque string；Snapshot/Evidence/Claim 等 run-produced records 显式保存 `run_id`。Replay 将创建新行，可复用相同不可变 Blob 内容哈希，但不得恢复 Live 终态。
- SourceSnapshot 事务保证允许完整 orphan blob，不实现 GC；外部拥有本机文件写权限者仍可破坏 Blob，读取会以 `BLOB_INTEGRITY_ERROR` fail closed。

## 后续问题

本阶段没有需要改变 Evidence/Claim/Replay/Validation 核心语义的未决问题。下一交付单元应先完成 generic Search/Fetch/Model recording ports 与 DocumentParser registry，再进入五 Agent Harness 和 Claim-Type-Aware ValidationPolicy。
