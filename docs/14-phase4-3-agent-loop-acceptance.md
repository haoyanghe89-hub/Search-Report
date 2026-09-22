# Phase 4.3 — Real Multi-Agent Investigation Feedback Loop 验收记录

日期：2026-09-22。稳定 Git 基线为 `622b9033a9e46fbeeb134e894add9eda8addba0c`；
本阶段实现仍位于未提交工作区，本文不代表已经 commit、push 或完成远端 PostgreSQL CI。

## 交付范围

- Supervisor / Planner、Researcher、Analyst、Verifier 均为只依赖 `ModelPort` 的结构化
  proposal producer。提示词、bounded user context 与 response schema 分离；外部来源内容只以
  `UNTRUSTED_SOURCE_DATA` 进入 user message。Harness 仍独占 Step/Run lifecycle、工具执行、
  持久化和路由；`ValidationPolicy` 独占最终 Claim status。
- 固定主链为 Plan → Collect → Analyze → Verify。Policy 产生的 Evidence、independence、primary
  source、conflict、causal/mechanism、quantitative 与 attribution gap 形成后续 ResearchTask；
  Evidence/Claim materialization 或 Claim decomposition 失败形成 `ANALYSIS_ERROR` 并回到有界
  analysis feedback Step。
- ContextBuilder 对问题、gap、task summary、source family/hash、Verifier Claim/Evidence/conflict
  设置显式 item 上限；ArtifactSelector 同时遵守 artifact、excerpt 和总字符上限，并优先当前
  task、问题相关、primary/official、gap 与 conflict 相关材料。
- Query guard 拒绝空、过长、归一化重复、同 task 重复、预算外和明显无关 query。Evidence guard
  在创建业务对象前校验 quote、quote hash、locator 与 immutable artifact bytes。Claim guard 只
  接受 atomic normalization；复合 Claim 允许一次结构化 decomposition，canonical statement、
  ClaimType 与 qualifiers 共同形成 dedup key。
- Verifier 的 semantic judgment 作为 `ValidationPolicy` 输入，不可输出 final status 或 release。
  验证结果、judgment、family、conflict、gap、Claim latest projection 与 Harness checkpoint 在同一
  UnitOfWork 完成；外部 model/search/fetch、解析、Blob 发布、integrity 与 Policy 计算在事务外。
- RunBudget 覆盖 research round、search/fetch/model、token、source 与 active time。预检和实际
  call reservation 都执行上限；Step 中途耗尽会保留已有状态并进入可解释 `BLOCKED`。信息增益
  按完整 research round（不是单 task）结算；连续零增益触发 `NO_INFORMATION_GAIN`。
- trace 支持 Claim → Validation → Relation → Evidence → Snapshot/Artifact → Source，并聚合 Claim
  原始及后续 Evidence 的 Analyst calls、ResearchTask、Researcher model calls、Search 与 Fetch；
  Gap 可追踪 origin Validation、follow-up task 与 parent task。
- Live 与 Replay 使用同一 orchestrator 和稳定 call-site identity。Replay 不注入 provider/key，
  创建新的 Run/Step/Validation/Claim ID，并以录制的 Model/Search/Fetch 响应重新运行 Policy。
  终点只生成 typed `ReportInput(InvestigationSummary)`；完整 Writer、15-section report、release、
  Reviewer、前端和发布验收不在 Phase 4.3。

## 持久化与迁移

`20260922_05_agent_feedback_loop.py` 增加 ResearchTask target Claim、origin Gap、parent task、
purpose、preferred source types、suggested queries 与 round；RunBudget source 上限/用量；
Evidence/Claim analysis Step 与 ResearchTask provenance；ResearchGap origin Validation。ORM 对
Claim → ResearchTask 的循环 FK 使用命名 `use_alter` 约束，避免 metadata 建表排序环；索引与 FK
覆盖 Gap/Task/Claim/Step 查询路径。

## 核心验证场景

- 两轮 independence/primary-source feedback 从 UNVERIFIED 变为 VERIFIED，并验证完整
  Gap → follow-up task、Claim/source/call trace。
- 强 quantitative conflict 首轮为 DISPUTED；第二轮 final reporting-time Evidence 解释并解析
  conflict，最终由 Policy 变为 VERIFIED。
- Agent-level Replay 不调用 live provider，重新生成业务 ID，并复现 phase trace 与 Policy statuses。
- 同一 round 多 ResearchTask 生成唯一 append-only Validation ID，且 information gain 只结算一次。
- Claim decomposition 连续失败持久化 `ANALYSIS_ERROR`，不允许零 Claim 伪装成功。
- model/search/fetch 预算在 Step 中途耗尽时转换为 `BLOCKED`；transaction operation 失败回滚业务
  输出、预算与 checkpoint。
- live structured-Agent smoke 仅在显式 `RUN_LIVE_TESTS=1` 和 DeepSeek credential 存在时执行。

## 本地门禁证据

| 检查 | 结果 |
| --- | --- |
| Phase 4.3 focused pytest | 17 passed，1 skipped；skip 为未显式启用真实模型 smoke |
| 完整离线 pytest | 170 passed，1 skipped，6 deselected；skip 为 Windows 非特权 symlink 假设 |
| Ruff `src tests migrations` | All checks passed |
| Phase 4.3 变更集 Ruff format check | 33 files already formatted |
| strict mypy `src/marketpulse --strict` | Success；105 source files |
| `uv build` | wheel 与 sdist 成功；wheel 包含 feedback 包与 `20260922_05` |
| 全新 SQLite Alembic upgrade + check | `No new upgrade operations detected`；无 FK cycle warning |
| PostgreSQL integration entry | 可收集；本机无专用 URL，按合同 1 skipped |
| 真实 PostgreSQL 17 | 待 commit/push 后由 `.github/workflows/postgres-integration.yml` 验证 |

上述门禁均在最终代码上重新执行。当前没有 commit 或 push；真实 PostgreSQL 17 与 live model smoke
仍须在明确提供各自专用环境后执行，不能由本地 skip 代替。

## 已知限制

- bounded context 是确定性截断与优先级选择，不含向量检索、语义 reranker 或 OCR。
- Agent proposal 仍可能语义欠佳；deterministic guards、一次 schema/decomposition repair、budget 与
  no-progress 只保证有界和可解释停止，不保证所有公开调查都能得到充分证据。
- Information-gain detector 在一次 orchestrator 执行内维护连续轮状态；跨进程恢复的长期趋势存储
  不在本阶段。
- 本地没有执行真实 PostgreSQL service 或真实模型 smoke；两者均有独立 opt-in gate，不能用
  SQLite/fixture 结果代替。
