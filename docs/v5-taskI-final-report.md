# 任务 I 交付报告：代码与回归已落地，真实 E2E 未通过

> 最新续交付（第 3–5 项）：见 [任务 I 续交付报告](v5-taskI-continuation-report.md)。新回归 532 passed；新真实 RUN-LIVE-b178a218f9e84f09 在首个请求因 HTTP 402 余额不足 PLAN/BLOCKED。下文保留上一轮历史结果，不将它覆盖或冒充最新运行。

**结论：多页/表格入库、模型角色路由、证据限定补全和有界重试已实施。唯一真实 E2E 在 VERIFY 收到 HTTP 402 余额不足，受控 BLOCKED；0 VERIFIED / 0 PROBABLE，未达到结论性可发布报告目标。没有为凑确认数放宽质量门，也没有继续发起付费请求。**

## 1. 范围与真实诊断

本轮仅改后端内部执行、材料与测试；保留既有 HTTP 请求/响应、路由和状态语义，未改前端，也未修改历史运行数据库。沿用 evidence 完整性、精确 ENTAILS、独立来源族和未解冲突门槛。细目见 `taski/progress.md`。

- `/models` 实查 200：当前有效模型为 `deepseek-flash`（V4.1 Flash）和 `deepseek-v4-pro`（V4 Pro）；不再请求退役的 chat/reasoner。原始脱敏结果 `taski/i1-model-list.json`。
- 原运行 RUN-LIVE-434153bec43c405f：67 声明，55 UNVERIFIED / 12 PENDING；来源预算 49，实际唯一来源 43；169 search / 55 fetch / 145 model / 777058 token。原始分析录签和验证缺口均只读导出，没有用测试数据冒充真实诊断。
- 量化候选的 time 在生成时已遗漏；示例 77.9% 引文缺少模型列与测量定义，PARTIAL 本身不是错误。原官方 DeepMind 来源质量 0.64 已达门槛，不应给二手材料统一提分。
- ff1df6bd… 原始 PDF 有五页、字符数 71/2337/2896/1189/71，历史 artifact 只有封面。真实 E2E 进一步证实直接丢失点：采集合并 `_entity_identity` 将 artifact 的 snapshot_id 外键误当主键，同快照多页与表格被跨实体去重；不完整快照复用随后放大损失。
- `issuer:Google` 是同发行方族标记，不是转载深度证据；修复扣分解释，但同发行方继续合并为一个独立族。

原诊断与实际数值：`v5-taskI-diagnosis.md`、`taski/i1-validation-basis.json`、`taski/i1-analysis-recordings/`、`taski/i1-detailed-diagnosis.json`。

## 2. 按批准优先级落地

### 多页 PDF / 表格

- `feedback/orchestrator.py` 合并按各实体真实主键（artifact_id/gap_id 等），不同页、不同表格不会因相同外键丢失。
- `services/source_acquisition.py` 新 PDF 带 page/hash manifest；复用不完整 PDF/HTML 从不可变原归档校验 hash 后补齐缺页/表格，加入原子 UoW，不改旧引用、不额外抓取或重复计来源预算。
- `ingestion/html.py` v3 另存可定位表格 artifact：原始标题、caption、列名与单元格逐字对应；简单规则无法定位的合并单元格保留原文而不猜归属。
- `feedback/retrieval.py` 重叠窗口与小预算窗口不再从英文词中间开始，避免 DeepSWE 被截成 eepSWE；定位符始终指向原 artifact 的真实字符范围/hash。
- `ingestion/pdf.py` v2 保留每页文本和 PDF_TEXT_RANGE 页码；含图像页显式提示未做 OCR，稀疏图像页产生可解释缺口，不把图像单元格伪装成已提取。
- 实际 SourceAcquisition → ResearchTeam → 合并 → Harness UnitOfWork 回归覆盖五页与 HTML 表格；官方归档 SHA 验证沿同一路径通过。真实隔离运行中五页亦已恢复，全部 blob 哈希匹配。

### 模型路由 / 请求参数

- `config.py`、`.env.example`：常规模型 flash 非思考，关键分析/分解/验证 v4-pro 思考；环境变量配置推理模型、强制单模型、effort（默认 high）、思考输出额度（16000）。
- `harness/model_routing.py` 在 request fingerprint、预算和 durable intent 之前固定选择模型及参数；`recovery.py` execution profile 包含这些配置，防止恢复时偷偷换模型。
- `adapters/model.py` 思考模式不传 temperature，thinking 放入 extra_body、effort 独立参数，最终结构化结果只取 content，不解析 reasoning_content；保留 JSON/Pydantic 校验与合法 fenced JSON 解析。
- `agents/factory.py` 旧 Agents SDK 路径也分流角色、统一超时与有界只读重试，不再把 402 当成可重试网络失败。

官方参数依据：[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/) 与 [Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion/)。

### Qualifiers / 元数据 / 质量

- `agents/prompts.py` v7 明确 value/unit/time/scope/definition/methodology/provenance 的结构化位置，保留 entity/time/scope 分组；要求表格列头、实体、日期/方法学证据，不用发布日期猜测评测日期。
- `agents/contracts.py`、`agents/supplements.py`：内部补全需本声明关联支撑 Evidence 的逐字 value/source_quote、明确时间类型及同 Evidence 完整 ENTAILS；不能覆盖已有值、采用竞争值或补造日期。
- `feedback/supplements.py`：补全与验证投影在同一事务原子提交，审计保存 claim/evidence/原值/新值/引文；回滚测试确认不会留半次补全。
- `feedback/verification_team.py` / `feedback/semantic_reuse.py`：验证输入带真实来源元数据、快照出处，复用身份包含出处信息，不误复用旧判定。
- `services/source_acquisition.py` 保存真实官方发布 URL → PDF 重定向链与方法学出处。实际网络核对见 `taski/i2-publisher-chain.json`；裸 storage URL 无链时不自动成为官方。
- `adapters/investigation_search.py` 区分官方自有材料的一手发布行为与“能力被独立证明”；`validation/quality.py` 修复 issuer 族误扣转载分，同发行方仍一个族。官方发布链正例质量 ≥0.6、裸云存储反例 <0.6，均有回归。

### PROBABLE / 网络韧性

- 保留现有各类 profile 的分级：VERIFIED 满足完整 profile；PROBABLE 仍需精确 ENTAILS、至少两个独立族与可信支撑、无强反证/未解冲突，仅枚举次要缺口可接受。定义、单位、语义核心、关键因果/归属边界不能豁免。
- QUANTITATIVE / STATEMENT / ATTRIBUTION / ANALYTIC_INFERENCE 对照测试：可信支撑与限定次要缺口可 PROBABLE；PARTIAL 或单族依然 UNVERIFIED，没有为凑数改门槛。
- `harness/calls.py` / `model_retry.py` 默认最多 3 次重试（总 4 次 dispatch），指数退避 1/2/4 秒；超时、连接中断、未知结果、429/5xx 自动恢复，400/402 不重试。
- retry 前重新准备 durable intent，明确 `ALLOW_POSSIBLE_DUPLICATE_CHARGE`，成功录签可复用，恢复后也受持久化 dispatch 上限约束。未知用量保守计入预算，不能绕过阶段预留。
- 连接 15 秒、读取 120 秒，运行级 AsyncOpenAI 客户端复用且关闭 SDK 隐式重试；超时取消后再调度。有界耗尽 BLOCKED 并保留材料，402 明确余额不足。搜索/抓取保留已有退避、熔断与坏 URL 跳过。
- 模型角色均为无工具/外部写操作的只读文本推理，重试不重复业务写入，但可能重复 provider token 计费；这与用户批准的边界一致。

## 3. 验证记录

最终完整后端回归：**524 passed / 3 skipped / 7 deselected，退出码 0，254.98 秒**。

命令：`.venv/Scripts/python.exe -m pytest -m 'not live and not infrastructure' -q --basetemp reports/taski/final-delivery-20261002 -p no:cacheprovider --junitxml=reports/taski/final-delivery.xml`。

- 独立 basetemp 与禁用 cacheprovider，未使用 `.pytest-work`。
- 3 个 skipped 为 Windows 无符号链接权限 / POSIX SIGTERM 能力限制；7 个 deselected 为显式排除的 live/infrastructure 测试，不将它们宣称为通过。真正付费 LIVE 已独立运行并记录未通过的结果。
- Ruff 全仓 `src tests` 与本轮审计/E2E 脚本：All checks passed，退出码 0。
- `compileall -q src`、核心导入检查、`git diff --check`：退出码均为 0。已有工作区 LF/CRLF 提示不是 diff 空白错误；没有为消除这些提示重写前端。
- 一项第三方 Starlette/AnyIO deprecated alias 警告不影响结果，未做无关依赖升级。
- 采集/发布链组 15 passed；角色/适配器组 41 passed；限定条件/质量组 28 passed；恢复/LIVE 韧性组 19 passed；额外旧 SDK / HTTP 类别组 13 passed。分组可重复覆盖，不与全量数相加。

OpenAPI 改动前后 SHA256 相同：`8a7ac4bb65c741aa7c54002ec9c12a1f75963da552e04e709547928429bdaf9e`。接口与前端无需联动改动。

## 4. 唯一真实 E2E 终态

- 同原话题实际运行：RUN-LIVE-7217d8f06f34422a。隔离库 `reports/taski/i3-live-20261002/live.db`，历史库仅只读。
- 总上限保持 2,000,000 token / 480 model dispatch / 3600 秒；没有临时加预算制造通过。
- 入库修复在 E2E 中找到后，核对并停止该隔离 worker，恢复同一 RUN；`i3-resumed-20261002` 保存后续进度/最终文件，材料和预算不重置，不创建第二次调查。
- UTC 2026-10-02 12:38:08 终态：VERIFY / BLOCKED，原因 `MODEL_INSUFFICIENT_BALANCE：模型服务余额不足，请充值后重试。`。402 未自动重试，已采集材料、预算、录签与状态报告保留；不是 FAILED/RUN_NOT_RESUMABLE。

| 实际指标 | 结果 |
|---|---:|
| 发现并记录的唯一来源 / 有合格快照的来源 | 44 / 38 |
| 运行状态中具有快照的来源 | 40 |
| Evidence / Claims | 34 / 37 |
| VERIFIED / PROBABLE / UNVERIFIED / PENDING | 0 / 0 / 36 / 1 |
| search / fetch / model dispatch | 82 / 44 / 77 |
| 计入运行预算 token / 上限 | 599743 / 2000000 |
| 实际计入墙钟 / 上限 | 1823172 / 3600000 ms |
| 报告 | RPT-7d27f1b675ad |
| report_type / release_status | INVESTIGATION_STATUS / RESTRICTED |

- ff1df6bd… 五页完整入库，页数/字符数/hash 全部核验；第 2 页已产生两个真实 Evidence，其他页尚未产生 Evidence。不能将“五页入库”写成“每页已引用”。
- 真实录签：规划/研究为 flash；分析/分解/验证为 v4-pro。语义记录为 37 ENTAILS / 124 PARTIALLY_SUPPORTS / 15 NOT_RELEVANT（这是累计判断记录数，不是确认声明数）。
- 同 RUN 恢复包含 1 个明确 `ALLOW_POSSIBLE_DUPLICATE_CHARGE` 意图。它是停止旧代码 worker 后的未知结果续跑，不冒充本次实际出现的网络超时自动恢复；自然超时“前两次失败、第三次成功”的自动恢复由离线测试验证。
- 未产生通过所有门槛的 qualifier 补全审计；没有因测试存在补全能力而宣称真实材料已经补齐。
- 最终脱敏只读审计 `taski/i3-terminal-audit.json`；原始 final.json 位于 `reports/taski/i3-resumed-20261002/final.json`。预算中的 token 是本地可记录用量，不是供应商账单对账；未知 dispatch 可能另有 provider 费用。

### 不能将剩余缺口全部归咎于 402

402 是本次不能继续真实验证的外部阻碍，但其发生前已经没有确认声明。终态真实缺口仍是：

| 类型 | 已验证声明数 | 主要 missing（可重叠） |
|---|---:|---|
| QUANTITATIVE | 14（另 1 PENDING） | time 9、definition 14、value/unit 各 5、完整 ENTAILS 11、一个合格质量来源 9 |
| ANALYTIC_INFERENCE | 14 | 合格支撑来源 14、完整 ENTAILS 12、多族 12、多 Evidence 12 |
| STATEMENT | 7 | 官方原始声明记录 7、完整蕴含 2 |
| EVENT_FACT | 1 | 一手/独立佐证/质量/精确蕴含缺口各 1 |

质量审计中官方 DeepMind `/models/gemini` 为 0.76；进入支撑关系的二手站点为 0.52，未为了确认改高。裸云存储 PDF 的发布链没有在此 RUN 被完整获取，无法凭独立诊断时的网络核对，回写该 RUN 的官方来源身份。强模型仍有字段漏提和裸行引文，这些真实现象保留在原始输出与缺口记录；充值不会自动保证这些问题消失。

## 5. 已知限制

- 无 OCR，PDF 纯图像表格不能冒充完整文本；已提供可定位文字页与有列头的真实 HTML 表格，并保留图像缺口。
- 没有实际官方发布链的云存储 PDF 不补造官方身份；复制转载不算独立复现，缺失评测日期/定义不猜。
- 强模型仍可能遗漏字段或只提取裸行；解析/语义/证据门仍拒绝不合格输出，单测通过不保证任意主题必有 VERIFIED/PROBABLE。
- 一次 E2E 初始步骤在修复前运行，已保存前后证据并同 RUN 恢复。结果不能称作全程从零使用最终版本的第二次调查；未自行追加付费运行。
- 因 402 不继续在线验证；当前交付不能声称任务 I 的结论报告验收已完成。需要供应商余额恢复后，沿原严格门槛再做端到端确认。

## 6. 本轮改动清单（不混入工作区既有前端/A–G 修改）

核心文件：

- `.env.example`、`src/marketpulse/config.py`、`src/marketpulse/agents/factory.py`
- `src/marketpulse/adapters/investigation_search.py`
- `src/marketpulse/investigation/ingestion/{html,pdf}.py`
- `src/marketpulse/investigation/services/source_acquisition.py`
- `src/marketpulse/investigation/feedback/{orchestrator,retrieval,verification_team,semantic_reuse,supplements}.py`
- `src/marketpulse/investigation/agents/{contracts,prompts,supplements}.py`
- `src/marketpulse/investigation/ports/external.py`、`adapters/model.py`
- `src/marketpulse/investigation/harness/{calls,model_call_journal,model_routing,model_retry}.py`
- `src/marketpulse/investigation/{live_runtime,recovery,case_replay}.py`
- `src/marketpulse/investigation/recording/diagnostics.py`、`validation/quality.py`

回归测试：

- `tests/integration/investigation/test_source_acquisition.py`
- `tests/integration/investigation/test_qualifier_supplement_persistence.py`
- `tests/integration/investigation/{test_model_call_recovery,test_live_runtime,test_live_resume,test_auto_recovery}.py`
- `tests/integration/investigation/{test_phase41_acquisition_uow,test_phase43_feedback_loop,test_phase5_report_pipeline}.py`
- `tests/unit/investigation/{test_model_routing,test_model_retry_policy,test_qualifier_supplements,test_table_artifacts,test_retrieval,test_validation_core,test_recording_adapters}.py`
- `tests/unit/test_agents_factory.py`

诊断与交付脚本/文件：`scripts/{diagnose_validation_gaps,diagnose_analysis_proposals,verify_live_token_budget,audit_taski_e2e}.py`、`docs/v5-taskI-diagnosis.md`、本报告、`docs/taski/`。现有脚本中沿用早期任务诊断功能，不把其全部历史改动归为任务 I。无新增第三方依赖。
