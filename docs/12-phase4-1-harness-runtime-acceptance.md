# Phase 4.1 — Harness Runtime + Typed Agent Contracts 验收记录

日期：2026-09-21。唯一基线为 `59b9bdc`；实现提交为 `f7425be`、`cb03bd7`。本文件记录 Phase 4.1 最终验收，不代表后续阶段已交付。

## 交付范围

- Investigation 专用 Harness：显式 `PLAN → COLLECT → ANALYZE → VERIFYING → READY_FOR_REPORT`；Verifier 缺口可定向返回 COLLECT 或 ANALYZE。假 Agent 测试到 READY_FOR_REPORT 结束，不生成 Report。
- 五角色冻结 Pydantic 契约与 Protocol；跨输入校验关键问题、任务/查询预算、Artifact/Claim/Evidence 引用和 Verifier 路由。Writer 仅有草案契约，不含验证、发布、审核状态变更。
- UnitOfWork 拥有共享 SQLAlchemy Session、commit/rollback；Repository 提供 CRUD-in-session。Harness 在外部调用之前提交 Step 开始事务，在外部调用和 Blob 完整性校验之后，以短事务同时写业务输出、Step COMPLETED 和 Run checkpoint/state_version；提交后才通知。
- Step 使用 `logical_step_key` 标识工作，`input_fingerprint` 标识该次规范化语义输入；唯一约束为 `(run_id, logical_step_key, attempt)`。已完成项可读取输出复用，变更输入或不安全重试被拒绝。
- 持久化 call binding 精确保存 run、logical Step、call site、ordinal、request fingerprint、recorded call ID、operation 及 schema/prompt/config 版本。Live 录制成功而 binding 尚未提交时，重入可找回完整录制；Replay 无 Live fallback，错误位置或版本显式失败。
- RunBudget 持久化轮次、Search/Fetch/Model 调用、token 和执行中的 wall time。调用前原子预留计数；模型成功响应绑定时一次性计入 token。Step 使用 monotonic duration，在 heartbeat、完成、失败时累计；服务停机时间不计入。
- `SourceAcquisitionService.prepare` 在 Search/Fetch/解析期间不写数据库，返回稳定 Source/Snapshot/Artifact/Gap ID 与有序业务输出；可交给 Harness 的 UnitOfWork 同 Step 一起提交。原 `acquire` 路径保留给 Phase 3 回归。

## 验证

| 检查 | 结果 |
| --- | --- |
| Phase 4.1 定向测试 | 13 passed；另有 prepared acquisition 集成测试 1 passed |
| 完整离线 pytest | 133 passed，1 skipped，5 deselected；skip 为 Windows 非特权 symlink 假设 |
| Ruff `src tests migrations` | All checks passed |
| strict mypy `src/marketpulse` | Success；81 source files |
| `uv build` | wheel 与 sdist 成功；wheel 含 `20260921_03_harness_runtime.py` |
| SQLite Alembic upgrade + `command.check` | No new upgrade operations detected |
| PostgreSQL CI | **通过**。[`PostgreSQL integration` run 35622985542](https://github.com/haoyanghe89-hub/Search-Report/actions/runs/35622985542) 在 commit `cb03bd78dd19262babad29edf776619b74adf6fe` 上完成并成功；[`postgres-contract` job 106410353269](https://github.com/haoyanghe89-hub/Search-Report/actions/runs/35622985542/job/106410353269) 使用 PostgreSQL 17 service，`Verify PostgreSQL migration and repository contract` step 成功。 |

关键测试覆盖：进程遗留 owner 的超时接管、显式重入、两 worker 竞争单 Step、输出/Step/checkpoint 事务回滚、外部工作开始前 Step 已提交、无效 Agent 引用失败、调用录制与 binding 之间崩溃后的复用、同 fingerprint 不同 call site 的精确 Replay、prompt/config 变更拒绝、token 只计一次、采集 prepare 不写库并在 Step 完成时原子提交。

## 已知限制

- Phase 4.1 的 Agent 为类型契约与确定性测试替身，没有真实模型提示词、Claim-Type-Aware ValidationPolicy、语义蕴含门禁、正式报告生成/发布或 Reviewer 流程。
- 采集 prepare 已提供可原子提交的产物，但完整 Live 调查主链尚未把真实 Researcher、SourceAcquisition、Analyst、Verifier 接成产品入口。Phase 3 原 `acquire` 调用仍沿用自己的持久化路径。
- 完整 Harness Replay 案例与可携带 fixture 尚未验收。Phase 4.1 binding 要求新的 call-site 元数据；旧 Phase 3 录制缺少该元数据时会 fail closed。
- 非正常进程死亡只保留最后一次 heartbeat 已计入的活跃时长；默认 heartbeat 间隔内的最后一小段执行时间可能未记账。没有自动 RecoveryScanner、公开 API 或前端。
