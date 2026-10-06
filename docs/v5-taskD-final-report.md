# 任务 D：材料上下文与阶段预算交付报告

日期：2026-10-02（已按本轮确认恢复真实调查并更新验收）。实现已落地；**D4 的“真实调查产出可发布结论”未通过**，不能将本次交付表述为端到端问题已全部解决。最新外部阻断为模型供应商 HTTP 402，不是本地 token 上限。

## 1. D1：实际 token 流向

只读检查原运行 `RUN-LIVE-c455bfabb21d43d4` 的数据库、逐个校验 SHA256 的模型请求/响应归档。可复现命令：

```powershell
.venv/Scripts/python.exe scripts/diagnose_token_flow.py RUN-LIVE-c455bfabb21d43d4 --output reports/taskd/before/token-flow.json
```

| 角色 | 调用数 | 输入 token | 输出 token | 合计 | 占已记录用量 |
|---|---:|---:|---:|---:|---:|
| researcher.research | 36 | 500,374 | 18,512 | 518,886 | 25.18% |
| analyst.analyze | 9 | 600,360 | 21,963 | 622,323 | 30.20% |
| verifier.verify | 78 | 764,051 | 110,420 | 874,471 | 42.44% |
| analyst.decompose | 11 | 15,333 | 6,564 | 21,897 | 1.06% |
| planner.plan / route | 2 | 17,968 | 5,065 | 23,033 | 1.12% |

结论不是“验证完全未执行”：verifier 已调用 78 次。其全部来源家族 JSON 累计占 1,280,118 字符；analyst 反复携带原文摘录、旧声明与长缺口描述。74 个 artifact view 被重复送入。旧 LIVE 参数是 30 来源、60 摘录、100,000 正文字符、100 条辅助记录。

原运行 budget 计费计数为 **1,981,109**，但响应归档有 **2,060,610** 个 token。最后一次 analyst 响应的 79,501 token 已被供应商返回，随后绑定阶段被总预算限制拒绝，未加进 budget。此前检查发生在调用之后，是可以避免的晚拒绝；没有修改历史计数掩盖这一差异。

另外，53 条声明全部 UNVERIFIED 不等于未运行验证：实际结果包括原文定位有效、语义 ENTAILED，但来源质量不足、缺独立支持、缺主来源或声明类型限定不足。旧运行开放缺口 177 个，包括 EVIDENCE_GAP 49、INSUFFICIENT_INDEPENDENCE 43、ATTRIBUTION_UNDER_SUPPORTED 19、UNREADABLE_SOURCE 54 等。省 token 不会自动补齐这些条件。

## 2. D2：材料规模管理

- LIVE 每次分析最多 **8 个来源、16 条摘录、24,000 正文字符**。辅助上下文最多 **16 项**，描述性字段最多 **500 字符**。参数由 Settings/env 统一配置，见 `.env.example`；不是组件内魔法常量。
- 使用已有 BM25 原文窗口，优先问题/任务相关段落，沿用当前任务、官方/第一手属性的确定性排序。存在相关段落时不补入零相关段落。多个小任务/小批次分析，再综合已有声明；不再将百篇全文反复交给模型。
- 相同 artifact hash/page 的重复内容在模型材料选择中合并。原始来源、快照、正文归档与谱系仍全部保存，不把转载当作独立支持。
- 压缩是**可追溯的原文摘录**，保留原始 offset、quote hash、artifact hash；没有新增 LLM 摘要调用，也不改写事实或生成原文不存在的结论。
- verifier 只携带所选证据引用的来源家族，再按并行 claim batch 缩小；不改变确定性政策看到的完整来源/谱系。
- 仅在 claim 内容/类型/限定与 evidence 内容/定位/hash 完全相同时复用已归档语义判断。增加或改变证据会触发重新判断；完整性、质量、谱系、充分性、冲突仍逐条重新验证，生成新的验证记录。
- LIVE 提示明确：公司“声称某项能力”与客观能力、责任归因分开；保留版本、日期、范围、单位等限定，不通过自动改类型降低验证门。

阈值依据：旧 analyst 成功调用平均输入 66,707 token，原文最多 66,915 字符；将每次材料降为原配置约四分之一，配合辅助上下文封顶，让多个任务可以在 200 万总额内运行。并不是“8 个来源足以证明所有问题”的质量结论。阈值可调整，未选入模型的归档不丢失。

**保守偏离**：没有做跨来源近似语义去重或生成式层级摘要；相似报道可能是独立佐证，当前只合并确定相同的内容，避免误删反证或独立证据。窗口可能重复，受总字符数约束。

## 3. D3：阶段预留和调用前上限

总额保持 **2,000,000 token / 480 次模型调用 / 3,600 秒**，没有提预算掩盖浪费。

| 配置 | 默认预留 | 作用 |
|---|---:|---|
| VERIFY token | 25% = 500,000 | 采集、分析、规划不能侵占 |
| REPORT token | 2% = 40,000 | verifier 也不能侵占 |
| VERIFY 调用 | 15% = 72 | 保留验证调用空间 |
| REPORT 调用 | 1%，向上取整 = 5 | 保留收尾空间 |

默认采集类总使用上限为 **1,460,000 token、403 次调用**；verifier 的上限为 **1,960,000 token、475 次调用**。报告目前由本地确定性 writer 生成，无模型调用，预留是明确的保底而非虚构已消费额度。

在外部模型实际 dispatch 之前，按 canonical UTF-8 请求字节数（含 schema）+ 输出上限做保守准入估计，并叠加同一 owner 事件循环中的在途请求。响应仍按供应商 usage 计费，估计不是 tokenizer 精确值。成功、失败、取消均在 finally 中释放在途估计；未知结果的收费不能假定为零。

触及采集阶段上限时停止扩张，沿合法 COLLECT → ANALYZE → VERIFY 边界处理已有声明，不伪造研究任务完成。无足够证据时仍受控阻断。有 VERIFIED 发现时可保留为 FULL_INVESTIGATION 的结论、引用与缺口，发布资格仍由原门禁决定；没有 VERIFIED 时仍如实出状态报告。

发现并修复的回归：只有 1 次模型额度时，新规则在调用前拒绝，已用计数应为 0；恢复入口原来只检查总计数，会反复恢复进同一拒绝。现在记录待调用所需 token/角色，并用追加后的预算重新校验阶段预留。原有 BUDGET_INCREASE_REQUIRED 接口语义保留。另修复辅助上下文压缩误影响离线模式，以及来源家族统计不能用截断后的模型上下文数量代替真实总量。

## 4. D4：一次真实同题调查

复制原 investigation 的题目、目标、范围和问题到隔离数据库，使用生产 LiveInvestigationService、现有本机凭据及代理 DNS 配置。没有改历史库、重启现有服务或创建第二个真实 run。本轮将用户明确确认用于恢复同一 run 的 3 个未知 verifier intent；预算增加各字段均为 0，保留已有步骤/录制/报告。

命令：

```powershell
.venv/Scripts/python.exe scripts/verify_live_token_budget.py --output reports/taskd/live-20261002
```

每 20 秒落盘 progress；目录复用会拒绝执行，避免误重复收费。首次 Windows 只读 URI 预检失败发生在创建运行/调用模型之前，修正后才启动下面这一次运行。本轮新增 `--resume-run` / `--retry-unknown-intent`：仅允许恢复 `reports/taskd` 下已存在的隔离库，必须保留 blob 归档；显式 consent 与实际未知 ID 完全匹配，否则拒绝。调用原 `RunRecovery` 的状态版本 CAS 和原恢复机制，不直接修改 run 状态。新增 6 项 runner 回归覆盖匹配、漏项、多项、重复项、不可恢复及不增加预算。

本轮恢复命令（3 个完整 ID 在 authorization.json；运行完成后不得照搬旧授权继续）：

```powershell
.venv/Scripts/python.exe scripts/verify_live_token_budget.py --resume-run RUN-LIVE-d8f6e1dff6a84924 --database reports/taskd/live-20261002/live.db --output reports/taskd/continuation/live-resume-20261002 --retry-unknown-intent <已确认的batch-2-intent> --retry-unknown-intent <已确认的batch-3-intent> --retry-unknown-intent <已确认的batch-1-intent>
.venv/Scripts/python.exe scripts/diagnose_token_flow.py RUN-LIVE-d8f6e1dff6a84924 --database reports/taskd/live-20261002/live.db --blobs reports/taskd/live-20261002/blobs/sha256 --output reports/taskd/continuation/after-token-flow.json
```

| 指标 | 原运行 | 本次真实运行 |
|---|---:|---:|
| run_id | RUN-LIVE-c455bfabb21d43d4 | RUN-LIVE-d8f6e1dff6a84924 |
| 研究轮次 | 2 | 3 |
| 搜索 / 抓取调用 | 91 / 225 | 109 / 40 |
| 模型调用 | 136 | 93：86 成功、4 PROVIDER_ERROR、3 CANCELLED（包含历史已恢复的 3 个错误） |
| 已归档响应 token | 2,060,610 | 417,965；未知调用实际收费需供应商核对 |
| budget token | 1,981,109 | 417,965 / 2,000,000（20.90%） |
| 持久化来源 / 证据 / 声明 | 128 / 45 / 53 | 29 / 29 / 34 |
| VERIFIED | 0 | 0（34 UNVERIFIED、0 PENDING） |
| 开放缺口 | 177 | 98（共 278 条历史缺口记录） |
| 报告 | RPT-4076dfe19365 | 最新 RPT-7c56d1df8f85；旧报告 RPT-f46304638648 保留 |
| report_type / release_status | INVESTIGATION_STATUS / REVIEW_REQUIRED | INVESTIGATION_STATUS / REVIEW_REQUIRED |
| 终点 | 预算受控阻断 | COLLECT / FAILED：MODEL_CALL_OUTCOME_UNKNOWN；第 3 轮 researcher.official 返回 HTTP 402 |

本次 sources_used 预算预留计数为 35；29 是实际持久化唯一来源，不混用两种口径。累计计时 314,068 / 3,600,000 ms。

成功响应的平均输入 token：researcher **13,899 → 3,720**；analyst **66,707 → 17,986**；verifier **9,796 → 2,500**。新 analyst 正文最大 18,375 字符，低于 24,000 上限。累计 **72 对**完全相同语义判断被复用，但仍重复执行完整确定性政策。运行材料和终点不同，这些是实际分布，不是严格 A/B 性能基准，更不能把提早停止当作完整调查节省率。

首次终点 VERIFY step 有 1 个成功及 3 个 PROVIDER_ERROR（connection_error）归档。按本轮确认恢复后，已越过原失败点、完成后续验证并推进到第 3 轮。新终点 `research:T-12-official-primary-documents-retrieval:round-3` 中，researcher.official 的供应商返回 **HTTP 402**，另外 3 个并行调用被取消。原未知结果安全机制将这 4 个最新 intent 保留为未知，不授权自动重试。HTTP 402 通常涉及付款/供应商额度，需要供应商侧核对；没有读取或披露错误正文、凭据或敏感头。仅凭状态码不能断言具体账户余额。

本轮诊断新增仅允许 category / transport_category / http_status 的供应商错误字段。最新 4 个未知 ID、call site 和安全类别完整保存在 `reports/taskd/continuation/after-token-flow.json`，旧 3 个 ID 的确认保存在 `continuation/live-resume-20261002/authorization.json`。不是所有 PROVIDER_ERROR 都可无条件重试；没有更换付费凭据、充值、提预算或绕过未知调用保护。

最新开放缺口分类：EVIDENCE_GAP 28、INSUFFICIENT_INDEPENDENCE 27、ATTRIBUTION_UNDER_SUPPORTED 8、INSUFFICIENT_ENTAILMENT 10、MISSING_PRIMARY_SOURCE 6、UNREADABLE_SOURCE 19。因此仍不能把已有候选声明写成确定结论或发布。现有报告首段明确说明尚无通过验证的关键发现，没有冒充 Answer-first 的事实结论。

**验收判断：**已证实上下文缩小、真实第三轮没有采集耗尽 token；阶段边界另有离线回归验证。但本次真实运行没有走到阶段预算边界或正常最终收尾，不能宣称真实 VERIFY/REPORT 全链路通过。D4 的验证比例/结论报告/发布目标仍未达成。预算修复不能解决供应商 HTTP 402，也不能代替证据质量、独立来源与主来源要求。

## 5. 改动清单（本轮 D）

生产配置/实现：

- `.env.example`、`src/marketpulse/config.py`
- `src/marketpulse/investigation/recovery.py`、`live_runtime.py`
- `agents/model_agents.py`
- `feedback/models.py`、`context.py`、`selection.py`、`retrieval.py`、`verification_team.py`、`orchestrator.py`
- 新增 `feedback/semantic_reuse.py`、`harness/stage_budget.py`
- `harness/calls.py`、`harness/persistence.py`
- `reporting/chinese_writer.py`

诊断/验证/文档：

- 新增 `scripts/diagnose_token_flow.py`、`scripts/verify_live_token_budget.py`
- 新增 `tests/unit/investigation/test_stage_budget.py`、`test_live_budget_runner.py`；更新 `test_retrieval.py`
- 更新 integration 的 `test_phase43_feedback_loop.py`、`test_model_call_recovery.py`、`test_phase5_report_pipeline.py`、`test_live_resume.py`、`test_auto_recovery.py`
- `docs/superpowers/plans/2026-10-02-stage-token-budget.md`、本报告

已有 A/B/C/前端修改保留；工作区 git diff 不全属于本轮。未新增依赖，不改 HTTP routes/DTO/enums、前端、验证 profiles/quality/policy、release policy 或历史数据。Settings 增项是运行配置，非 HTTP 契约。

## 6. 最终验证

```powershell
.venv/Scripts/python.exe -m pytest -m 'not live and not infrastructure' --basetemp=reports/taskd/continuation/pytest-full -p no:cacheprovider -q
.venv/Scripts/python.exe -m ruff check src tests scripts
.venv/Scripts/python.exe -m compileall -q src/marketpulse scripts/diagnose_token_flow.py scripts/verify_live_token_budget.py
git diff --check
```

- 本轮后端回归：**421 passed、3 skipped、7 deselected、1 warning，退出码 0，166.39 秒**；使用独立 `reports/taskd/continuation/pytest-full` 与禁用 cacheprovider，没有与 `.pytest-work` 竞争。专项 runner/stage-budget：10 passed，退出码 0。上一轮 415 passed 结果仅作为历史，不代替本轮验收。
- Ruff / 编译 / 导入：退出码 0。
- Investigation Console `server.create_app().openapi()` 经 `json.dumps(schema, sort_keys=True)` 的 SHA256：`8a7ac4bb65c741aa7c54002ec9c12a1f75963da552e04e709547928429bdaf9e`，与 B/C 基线一致。没有使用旧 MarketPulse web_api app 的不同 schema 混做前后比较。
- git diff --check：退出码 0；已有前端/uv.lock 的 LF→CRLF 提示不是 whitespace error。
- 3 项 Windows 平台跳过：两个无权限 symlink 测试、一个 POSIX signal 测试；7 项 live/infrastructure 测试需要另外的外部配置，本回归未执行。单次真实模型调查是上节的独立验证，不冒充这 7 项通过。已有 Starlette/AnyIO 弃用 warning 保留。

## 7. 剩余限制与后续授权

本轮修复针对 token/context，不通过降质量门解决资料不足。真实样本依然需要足够质量、独立且匹配声明范围的原始材料；拿到网页不等于声明已验证。近似去重和生成式摘要未引入。预算估计与供应商计费不是同一量，未知或取消调用的费用需与供应商核对。

**外部阻断：需要先处理供应商 HTTP 402。**本轮已使用用户确认恢复原 3 个 verifier intent，不再等待该旧确认。后续继续之前，需要供应商额度/付款限制恢复，并核对本轮 4 个未知/取消调用是否计费，随后对最新 intent 作明确恢复确认。当前不自动再付费重试、不更换凭据、不放行报告；同一 run 的材料和检查点均保留，可安全恢复。

证据文件：历史 `reports/taskd/before/token-flow.json`、`after/token-flow.json`、`live-20261002/configuration.json`、`progress-*.json`、`final.json`、`live.db` 与 hash-addressed blobs 均保留。本轮新增 `reports/taskd/continuation/before-token-flow.json`、`after-token-flow.json`、`live-resume-20261002/recovery-before.json`、`authorization.json`、`progress-*.json`、`final.json`。旧 final.json 未被新终点覆盖。
