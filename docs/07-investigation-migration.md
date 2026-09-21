# Investigation 原地迁移边界

授权范围：同仓库原地分阶段迁移；用户已允许开始基线与已确认基础设施。2026-09-21 起将现有目录接入新建空远程 `https://github.com/haoyanghe89-hub/Search-Report.git`。不创建第二套项目、不 copy-paste fork。

## 当前 inventory

旧入口 CLI/FastAPI -> workflow -> TeamCoordinator -> Master/Search/Analysis/Report。黑板 mp_runs/mp_events 存 SQLAlchemy JSON 快照和事件元数据；默认 SQLite，已有 PostgreSQL adapter 尚未实机联调。模型为 DeepSeek + Agents SDK。React/Vite/shadcn 页面持有内存结果，未实现刷新恢复。已有搜索、抓取、robots、预算、日志、结构验证和离线 fake fixtures。

现有缺口：EvidenceClaim 混合证据/主张；正文未持久化；无源快照/PDF/lineage/conflict/独立 Verifier/审核；复核仅 research/report；API 长请求且局部锁；Compose 仅 PG/Redis，无完整 app Dockerfile；无正式数据库 migration、恢复器或逐调用录制。

## 分类

| 决策 | 现有模块 | 处理 |
| --- | --- | --- |
| keep | 搜索回退机制、robots、agents/factory.py 模型封装、budget.py、UI primitives、测试工具链 | 保留资产，抽接口时消除市场契约依赖 |
| refactor | adapters/fetch.py、collector/extractor、blackboard、coordinator、workflow、config、observability、CLI/FastAPI、前端壳、基础设施测试 | 增强安全/持久化/通用 ports，分离 Harness 与 domain |
| replace | domain/analysis.py、research.py 中市场 intent、EvidenceClaim、market prompts/agents、quality/report 模板、竞品/价格/Go-No-Go 页面 | 新 Investigation 类型、五角色、显式 Policy、Console；不得只改提示词/名字 |
| delete after gate | 旧 market API/UI/类型/prompts/仅兼容旧业务 adapter 与无引用测试 | Gate 全通过后移除；旧 debug 脚本另行确认归属，当前不动 |

## 阶段与依赖

原先“Phase 1 baseline”在本轮拆为 Phase 0 基线和 Phase 1 基础设施，避免把本轮存储完成误称整个迁移完成。

| 阶段 | 可交付单元 | 出口 |
| --- | --- | --- |
| 0 | 旧工程 Git baseline、离线/静态/前端/打包验证、架构合同 | 可回溯到未重构代码，准确记录跳过项 |
| 1a（本轮） | BlobRef、BlobStoragePort、LocalContentAddressedBlobStorage | 去重、并发、损坏/缺失、异常写入、重开持久化、无市场依赖测试 |
| 1b | 通用 model/search/fetch/recording/context/trace ports 与 provider 装配 | legacy 可依赖 generic，反向 import 被测试禁止 |
| 2A–2D（已完成） | PostgreSQL schema migrations、调查实体/repository、Snapshot persistence、locator foundation | 24 张 `inv_` 表、round-trip、版本化 artifacts、事务与引用约束；Parser 按批准范围留后续 |
| 3 | 五 Agent + Harness + Step/Checkpoint + typed ValidationPolicy | 可运行主链、定向返工、状态/置信度分离 |
| 4 | ReportValidator/ReleasePolicy、Reviewer auth/audit、InProcessExecutor/SSE/recovery | 硬门禁、版本绑定审批、人工补查、手动恢复 |
| 5 | Investigation Console、Live/Replay 便携 fixture 纵向切片 | Legacy Removal Gate A–J 全通过 |
| 6 | 删除旧 market 业务/兼容支路，更新产品文档/命名 | 单领域产品，回归持续通过 |
| 7 | East Palestine 完整验收、Docker 一键交付、Eval、完整文档 | Live + Replay + recovery E2E + PUBLISHED |

Snapshot/录制接口必须早于 Agent 对接；不能等到末尾才补引用与 Replay。每阶段保持工程可启动、可测试；本轮只实现 0 与 1a。

## Legacy Removal Gate（AND）

A. Investigation/Source/SourceSnapshot/Evidence/Claim/ClaimEvidenceRelation/ValidationResult 正式持久化。
B. Supervisor/Planner -> Researcher -> Analyst -> Verifier -> Writer 实际运行。
C. evidence_gap -> COLLECT -> VERIFY 的实际返工与集成测试。
D. ReportSection -> Claim -> Evidence -> Snapshot -> exact locator 完整可追溯。
E. Live 可运行。
F. 禁网、无外部 key、空库 Replay 重执行关联/状态/冲突/引用/验证/报告，非恢复终态。
G. 前端创建/进度/来源/证据主张/验证/报告/引用跳转纵向切片。
H. 刷新与服务重启后状态可读取。
I. Investigation 核心测试通过。
J. Investigation/generic 无 market-specific 依赖。

达到 A–J 前保留旧流程；达到后不继续维持双业务兼容。完整 case 验收仍要求 PUBLISHED，受限报告不代表项目验收通过。
