# Phase 4.2 — Evidence / Claim / Validation Core 验收记录

日期：2026-09-22。唯一代码基线为 `760d37c6016600b1545304c5c853068cfbec63a3`；Phase 4.2 实现提交为 `7a0abdc066ce4e608afd81d46ec7eccefff8097a`。本文件记录 Phase 4.2 独立验收；不代表 Phase 4.3、真实 Agent、报告或发布流程已交付。

## 交付范围

- `marketpulse.investigation.validation` 是独立内核，不导入 Agents 或 Harness。输入为 Claim、Evidence、relation、Source/Snapshot/Artifact metadata、lineage、语义判断和既有冲突；输出为 ValidationResult、ConflictSet、ResearchGap、独立性/质量评估和机器可读 basis。
- `EvidenceIntegrityValidator` 按 Evidence、Snapshot、Artifact、Blob、locator、exact excerpt、quote hash 和版本逐层 fail closed。Evidence ID 存在不等于可用于支持 Claim。
- `SemanticJudgment` 将 ENTAILS、PARTIALLY_SUPPORTS、CONTRADICTS、NOT_RELEVANT、UNCERTAIN 与最终 Claim status 分离；可重放语义判断，但最终 Policy 每次重新计算。
- Claim normalization 只验证结构化语义 proposal，保留 canonical statement、实体/时间/范围限定、ClaimType、importance 和 critical 标志；不实现通用 NLP 拆解器。
- `SourceLineageResolver` 根据显式 origin、syndication cluster、attribution 与 metadata 形成稳定 Evidence/Source family；publisher/organization 只作为依据。`SourceIndependencePolicy` 按 family 计数并报告转载成员及 primary/secondary family。
- 来源质量使用 first-hand、官方/直接参与、primary、数据 provenance、方法透明度、具名来源、时间接近度、转载深度、推测程度、独立性、显式不确定性、与更强证据一致性等 12 个维度；可选分数不单独决定 VERIFIED，也没有品牌固定分。
- `ConflictDetector` 支持 QUANTITATIVE、TEMPORAL、ATTRIBUTION、CAUSAL、SCOPE、DEFINITION、OTHER，允许用时间/范围/定义解释差异，不平均数值。`StrongContradictionGate` 在独立性和数量充分性之前执行，不以多数投票覆盖强反证。
- 八个显式 Python profile 覆盖 STATEMENT、INSTITUTIONAL_ACTION、EVENT_FACT、QUANTITATIVE、CAUSAL、IMPACT、ATTRIBUTION、ANALYTIC_INFERENCE；不使用 DSL。ANALYTIC_INFERENCE 最多为 PROBABLE，IMPACT basis 保留 subtype。
- `ValidationPolicy` 固定执行 15 个阶段：存在性、完整性、locator、语义蕴含、lineage、强反证、独立性、质量、分类型充分性、冲突、status、confidence、validation basis、confidence basis、ResearchGap。status 与 confidence 分离，confidence 是带 basis 的 policy-calibrated indicator。
- Policy 生成结构化 ResearchGap，但不调度 Researcher。每次验证插入新的 append-only ValidationResult；同一事务写 family/judgment/conflict relations、结果并更新 Claim latest projection。

## 持久化与迁移

Focused migration `20260922_04_validation_core.py` 新增 semantic judgment、source family/member、validation-conflict 和 conflict-evidence 关系，补充验证版本/hash/basis、冲突与 gap 字段及索引/FK。数据库触发器保护不可变验证、语义判断、family/member 和验证关系记录；Claim 仅保存 latest projection。

## 核心案例

测试覆盖用户指定的 16 个场景：statement 与客观事实区分；单一官方因果声明不足；五份转载只算一个 family；1500/2000 冲突且不平均；三份普通支持不能覆盖一份强直接反证；reported symptom 与 causal impact 区分；无效 quote/locator 在充分性前失败；NOT_RELEVANT 不支持；EVENT_FACT 独立性 gap；10 miles/10 km 单位冲突；early/final 数字按时间演进解释；利益相关方单独归责不足；分析推断最多 PROBABLE；DISPUTED 可有高 confidence；相同语义输入得到相同语义结果；Replay 语义判断后 fresh recompute status。

附加测试覆盖全部 12 个质量维度、八个 profile、institutional action、Blob/版本/Snapshot mismatch、越界 locator、append-only 约束、lineage/conflict relations、索引/FK 和 Claim latest projection 一致性。

## 验证状态

| 检查 | 结果 |
| --- | --- |
| Phase 4.2 定向测试 | 20 passed |
| 完整离线 pytest | 154 passed，1 skipped，5 deselected；skip 为 Windows 非特权 symlink 假设 |
| Ruff `src tests migrations` | All checks passed |
| Phase 4.2 变更集 Ruff format check | 22 files already formatted |
| strict mypy `src/marketpulse` | Success；93 source files |
| `uv build` | wheel 与 sdist 成功；wheel 包含 `20260922_04_validation_core.py` |
| SQLite Alembic upgrade + `command.check` | No new upgrade operations detected |
| PostgreSQL CI | **通过**。[`PostgreSQL integration` run 35631868269](https://github.com/haoyanghe89-hub/Search-Report/actions/runs/35631868269) 在 commit `7a0abdc066ce4e608afd81d46ec7eccefff8097a` 上完成并成功；[`postgres-contract` job 106439739811](https://github.com/haoyanghe89-hub/Search-Report/actions/runs/35631868269/job/106439739811) 的 `Verify PostgreSQL migration and repository contract` step 成功，验证了真实 PostgreSQL migration、append-only ValidationResult、lineage/family relations、conflict relations、索引、FK 与 latest projection consistency。 |

## 已知限制

- Phase 4.2 的 semantic judge 是合同与确定性替身，不含真实模型提示词或 Agent 推理；Claim normalization 不自动拆解自然语言复合 Claim。
- Lineage 只使用结构化 origin/syndication/attribution metadata；没有网页级实体解析、相似度聚类或语义辅助 resolver。缺少 lineage metadata 时保守地形成 UNKNOWN family。
- 质量组件和 confidence 是可解释的确定性政策指标，不是统计概率，也不代替人工风险判断。
- 冲突解析覆盖本阶段类型化 observations；复杂跨文档口径映射仍需要上游产生可靠结构化 metadata。
- ResearchGap 只生成和持久化，不调度 Supervisor/Researcher。真实 Agent Loop、Writer、报告验证/发布、Reviewer、公共 API 和前端均不在本阶段。
