# 任务 F：提案对齐与重复循环修复

## 交付结论

聚焦修复、离线限定条件核对与回归已完成；**F4 的真实“已验证结论 + 可发布报告”目标尚未达成**。
此前最终真实验收在第一份分析响应返回前发生模型连接异常，进入
`MODEL_CALL_OUTCOME_UNKNOWN`。未自动重试可能已计费的调用，未重启现有服务，
未改历史运行。最后的限定条件幂等补丁已通过离线真实归档重放及后端回归，
但不能据此宣称已通过最终联网端到端验收。

用户已确认网络恢复，并明确由用户统一重启后端、发起最终付费端到端验证。
本次交付核对完全离线：未联网、未重启后端、未新建付费运行，也未重试未知调用。

上一轮全量回归实际为：**452 passed / 3 skipped / 7 deselected，退出 0**；Ruff、格式、
compileall、导入与 `git diff --check` 均通过。HTTP OpenAPI 指纹与既有基线相同。

## F1：实际输出与校验要求

只读检查 `RUN-LIVE-5ef5e23234794a22` 后发现：累计 token 为 **213261**，
不是请求描述中的约 13261；实际已有 **24 条 Evidence、21 条 Claim**，
17 次 verifier 调用，21 条 Claim 均 UNVERIFIED。不能将其描述成所有分析均失败。
四个任务的分析最终通过结构与输入引用检查，最后的矛盾/缺口任务阻断。
这些 token 是数据库累计值，不是精确计费总量：无效输出未归档 usage。

| 校验项 | 实际证据 | 原要求 / 处置 |
| --- | --- | --- |
| `evidence[*].locator.quote_hash` | 历史 T-02、T-05 初始响应各报 6 个 missing；LIVE 提示却要求省略 hash | nested locator 必填。明确只省略顶层可选 hash；缺省 nested hash 可从候选 quote 计算，随后仍须通过原文完整性门 |
| `relations[].claim_key`、`conflict_observations[].claim_key` | 新的真实完整响应含 `CLAIM-461ead…` 等；这些键确实在输入 existing_claims 中，却不在输出 C1–C4 中 | 本地引用必须闭合。按可信输入复制相同既有定义进 claims，不删关系、不改立场、不猜 ID |
| 限定条件结构 | 已存 qualifiers 同时含扁平字段与 `entity/time/scope` 分组；整个 envelope 再塞入 entity 会改变去重键 | 无损还原三组字段；同既有 key 的 statement、type、canonical statement、qualifiers 必须完全匹配，变化须使用新 key |
| 引文与归档 | 真实响应重放 42 个候选中 38 个通过归档完整性门、4 个不匹配原文 | 4 个仍拒绝；不会因为结构修复而接纳不存在的原文 |
| 已处理来源 | 原 DeepMind `S-a902a55307bcef05069acf90a7347641` 同一 run 中有 5 份合格快照 | 同 run、同来源复用已落库且可用的不可变快照及 artifact ID；实测降为 1 份 |
| 重复分析 | 空分析提案的回归复现原先调用 18 次才终止 | 每任务分析反馈最多 2 次；达到上限本地受控 BLOCKED，保留记录及可操作原因 |

重要取证限制：历史无效 provider 响应没有保存原始文本，只保存了校验码；
最后两次历史修复只有 `value_error`，不能反向声称知道其完整 JSON。
本轮通过一次真实调查补获 **7 份校验前的完整模型响应**；其中 4 份明确失败于
`analysis_unknown_relation`，对照实际输入后确认是既有声明引用未本地闭合。
这解释了可复现的失败机制，但不虚构历史丢失的字节。

证据：

- [历史分析逐项记录](D:/deepsearch/reports/taskf/before/analysis/comparison.json)
- [一份真实失败的完整原始响应](D:/deepsearch/reports/taskf/live-final/analysis-raw-0007.json)
- [7 份响应的规范化与完整性对照](D:/deepsearch/reports/taskf/live-final/analysis-normalization-comparison.json)
- [18 条既有声明的原 ID/状态复用证明](D:/deepsearch/reports/taskf/live-final/claim-identity-proof.json)
- [来源复用前后统计](D:/deepsearch/reports/taskf/source-reuse-comparison.json)

## F2：修复及安全边界

1. **引用命名空间与提示对齐**：输入本来已含实际 `source_key`、来源标题与
   artifact 定位信息。明确 source/snapshot 不是 artifact_key；新 Evidence 用本地
   E1 等键，既有 Claim 使用输入中的精确语义键。artifact view 键仍通过 ContextBuilder
   映射到实际归档 artifact/source，不要求模型猜数据库 ID。
2. **无损结构规范化**：仅为输入中真实存在、且被关系/冲突引用的既有 Claim
   补齐原定义；精确保留 entity/time/scope。若模型把整个原 qualifiers envelope
   放进 entity，仅在原文/type/envelope 完全相同且另外两组为空时拆回原结构。
   不猜测短 ID、不删除未知引用、不替换改写的声明、不产生“已验证”状态。
3. **校验可定位**：duplicate evidence/claim、unknown evidence/relation/conflict
   使用固定应用错误码，替代笼统根级 value_error；修复提示及终止记录携带这些码，
   不携带模型拒绝值、任意异常文本或凭据。
4. **哈希规范化不是证据认证**：只补缺省 digest，不覆盖已提供 hash/位置。
   quote 必须匹配所选原文，再由既有 EvidenceCreationGuard 与完整性门检查
   archive bytes、hash、offset、PDF page、版本。离线试验的 38 个 PASS 不等于
   38 个新增入库 Evidence，更不等于 38 个已验证结论。
5. **来源复用**：LIVE 的 deduplicate_material 启用复用；只复用同一 run 中
   PARSED/PARTIALLY_PARSED、evidence_eligible 且有 artifact 的落库快照。
   不跨 run 复用，不把不可读/挑战页当成功，不新增快照或重复计新来源统计。
   原 acquisition_batch 已做批内 URL 去重，本轮不重复实现。
6. **有限分析与幂等**：`FeedbackLoopConfig.max_analysis_attempts=2`；每次生成仍
   保持最多 2 次结构修复（总计最多 3 次调用），退避保持 0.25/0.5 秒。
   上限增加一个无模型调用的本地阻断步骤，所有步骤仍事务化落盘。
   对真实 18 条已存声明核验，三组 qualifiers 正确还原后全部复用原 Claim，
   原 ID、critical 标记与验证状态不变。
7. **诊断隔离**：raw observer 默认关闭；仅隔离验收脚本显式开启，只捕获分析
   响应正文，不存请求头/密钥。查询和重放只读数据库，未把重放候选写回真实 run。

EvidenceIntegrityValidator、ValidationPolicy、来源独立性/发布阈值均未放宽。
任务 D 的材料上限、语义验证复用、VERIFY/REPORT 预留、2M token / 480 调用 /
3600 秒总上限保留。任务 E 的来源级错误容错也保留。
prompt version 更新为 v5，执行 profile 会变化，旧检查点不应混用新提案语义。

## F3：模型选择

**没有切换模型**。历史及本轮实际配置是 `deepseek-flash`（thinking=false），
不是请求举例中的 deepseek-chat。已取得的正常提案，以及失败 JSON 中真实有效的
引用/原文，证明存在明确的提示与本地引用闭合问题；没有证据支持用未经验证的
另一个模型名称来替代这次聚焦修复。无配置、密钥或依赖变更。

## F4：真实重跑结果（不得冒充成功）

两个 run 均复制同一调查到独立 SQLite/归档目录，未改根数据库：

| 项目 | 取证运行 `6c44a0b049314d96` | 最后联网尝试 `020b536dece14824` |
| --- | --- | --- |
| search / fetch / model | 43 / 27 / 42 | 12 / 8 / 6 |
| 数据库 token | 170837 / 2000000 | 10987 / 2000000（未知调用未计 usage） |
| 来源（有 snapshot）/ 快照 | 25 / 26；合格快照 21 | 7 / 7；sources_used=8 含不可用尝试 |
| Evidence / Claim / VERIFIED | 14 / 18 / **0** | 0 / 0 / **0** |
| 终态 | BLOCKED / REPORT；取证发现 dangling existing Claim refs | FAILED / ANALYZE；MODEL_CALL_OUTCOME_UNKNOWN |
| 报告 | RPT-fa0788c65ff6；INVESTIGATION_STATUS / REVIEW_REQUIRED | RPT-430fd4a9d606；INVESTIGATION_STATUS / RESTRICTED |

第一轮用于抓取完整响应；最终无损引用与限定条件补丁是基于该证据继续完成的。
最后联网尝试在分析请求处记录 `ProviderCallError`、`category=connection_error`，
没有拿到模型响应，之后限定条件补丁只有离线验证。最终 v5 **未获联网发布验收通过**。
未知 intent：`MODEL-INTENT-f21013166ab32bfdb637ab24811708a041302d4e26dd2e4b157f7ef90730d375`。
未授权它自动重试，未通过去掉 unknown-call 暂停机制来追求成功。

- [取证运行最终结果](D:/deepsearch/reports/taskf/live-final/final.json)
- [最后联网尝试最终结果](D:/deepsearch/reports/taskf/live-verified-code/final.json)
- [最后调用与未知 outcome 记录](D:/deepsearch/reports/taskf/live-verified-code/token-flow.json)

来源合格不等于结论可发布。第一轮仍有 EVIDENCE_GAP=15、
INSUFFICIENT_INDEPENDENCE=14、MISSING_PRIMARY_SOURCE=4 等开放缺口；来源元数据
中 official/first_hand 也未建立可用标记。本轮没有把媒体转述强行算作独立验证，
或仅因域名/正文长度就把所有结论改为 VERIFIED。

## 测试与契约

### 最后一次离线交付核对（2026-10-02）

本次未改生产代码；只为离线诊断脚本增加分组结果字段，并更新报告/验证清单。
重新读取真实归档，使用原 ClaimGuard 与 EvidenceCreationGuard 核验：

| 核对项 | 本次结果 |
| --- | --- |
| entity / time / scope 三组分别与原声明相同 | 各 18/18；没有合并分组、丢失字段或把 envelope 嵌入 entity |
| 既有 Claim 完整对象、原 ID、critical 与验证状态 | 18/18 原对象复用，无新增/升级验证状态 |
| 7 份真实响应的结构与引用重放 | 7/7 通过 |
| 原文/归档完整性 | 38/42 通过；4 个原文不匹配仍拒绝，重放候选未入库 |
| 定向测试 | 9 passed，2.14 秒，退出 0 |
| Ruff / 诊断脚本格式 / 编译 / diff | 均退出 0 |

只读重放前后 `reports/taskf/live-final/live.db` 的 SHA256 保持
`4be2607d8c223bac9ce31880baf61953fa1662c3e588fdfef4e6f52773859979`。
分组逐项证据见 [claim-identity-proof.json](D:/deepsearch/reports/taskf/live-final/claim-identity-proof.json)。

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/investigation/test_analysis_existing_references.py tests/unit/investigation/test_proposal_alignment.py --basetemp=reports/taskf/pytest-handoff-offline -p no:cacheprovider -q --tb=short
.venv/Scripts/python.exe scripts/replay_analysis_diagnostics.py reports/taskf/live-final
```

### 上一轮全量回归记录

新增用例红→绿：初始缺省 hash/错误码组 4 failed / 1 passed；
来源复用及反馈上限组 3 failed；真实既有引用组 1 failed / 1 passed。
修复后覆盖缺省/已有 hash、虚构 artifact/claim/evidence 引用、引文不匹配、
关系立场不变、限定条件幂等、canonical 偷换拒绝、不可读来源不复用、
同 run 来源复用及跨 run 不复用、分析上限和 BLOCKED 原因。

上一轮全量命令与结果（本次未重复运行全量套件）：

```powershell
.venv/Scripts/python.exe -m pytest -m 'not live and not infrastructure' --basetemp=reports/taskf/pytest-release -p no:cacheprovider -q --tb=short
.venv/Scripts/python.exe -m ruff check src tests scripts
.venv/Scripts/python.exe -m ruff format --check <本轮 16 个 Python 文件>
.venv/Scripts/python.exe -m compileall -q src/marketpulse scripts/diagnose_analysis_proposals.py scripts/replay_analysis_diagnostics.py scripts/verify_live_token_budget.py
git diff --check
```

**452 passed、3 skipped、7 deselected、1 warning，204.53 秒，退出 0**。
3 项 Windows/POSIX 条件跳过；7 项依赖外部 live/infrastructure，未冒充通过。
保留既有 Starlette/AnyIO 弃用警告。独立 basetemp、禁用 pytest cache，未使用
`.pytest-work`。Ruff/格式/编译/导入/diff 均退出 0；既有 LF→CRLF 提示非 whitespace error。

Investigation Console OpenAPI SHA256：
`8a7ac4bb65c741aa7c54002ec9c12a1f75963da552e04e709547928429bdaf9e`，
与 B/C/D/E 基线一致。路由、请求/响应字段、对外状态枚举未改；前端不需要改动。

## 本轮文件

生产：

- [contracts.py](D:/deepsearch/src/marketpulse/investigation/agents/contracts.py)
- [model_agents.py](D:/deepsearch/src/marketpulse/investigation/agents/model_agents.py)
- [normalization.py](D:/deepsearch/src/marketpulse/investigation/agents/normalization.py)（新增）
- [prompts.py](D:/deepsearch/src/marketpulse/investigation/agents/prompts.py)
- [adapters/model.py](D:/deepsearch/src/marketpulse/investigation/adapters/model.py)
- [feedback/models.py](D:/deepsearch/src/marketpulse/investigation/feedback/models.py)
- [orchestrator.py](D:/deepsearch/src/marketpulse/investigation/feedback/orchestrator.py)
- [repositories.py](D:/deepsearch/src/marketpulse/investigation/persistence/repositories.py)
- [source_acquisition.py](D:/deepsearch/src/marketpulse/investigation/services/source_acquisition.py)

测试：新增 [test_proposal_alignment.py](D:/deepsearch/tests/unit/investigation/test_proposal_alignment.py)、
[test_analysis_existing_references.py](D:/deepsearch/tests/unit/investigation/test_analysis_existing_references.py)；
更新 [test_source_acquisition.py](D:/deepsearch/tests/integration/investigation/test_source_acquisition.py)、
[test_phase43_feedback_loop.py](D:/deepsearch/tests/integration/investigation/test_phase43_feedback_loop.py)。
脚本：新增 [diagnose_analysis_proposals.py](D:/deepsearch/scripts/diagnose_analysis_proposals.py)、
[replay_analysis_diagnostics.py](D:/deepsearch/scripts/replay_analysis_diagnostics.py)；
更新 [verify_live_token_budget.py](D:/deepsearch/scripts/verify_live_token_budget.py)（默认流程不捕获 raw）。
文档/证据：本报告、[执行记录](D:/deepsearch/docs/superpowers/plans/2026-10-02-proposal-alignment.md)、
[验证清单](D:/deepsearch/reports/taskf/verification.json)。未新增依赖，未改前端或本机配置；保留既有 dirty tree 和用户文件。
总 git diff 含前面 A–E/UI 工作，不可当作本轮 F 的变更量。

## 剩余限制与交接

- 代码修复与离线/回归验收通过，真实最终报告目标仍需用户联网确认；不能宣称达到可发布。
- 来源复用只针对同一 run 已接受的落库材料；JS 空壳等不作为成功缓存。
  同一来源对不同问题提供不同相关片段仍允许，不能用全局禁用旧来源代替调查。
- 严格的引用、独立性、主来源、冲突及发布门仍可能阻止发布，合格正文量不保证结论。
- 最后的未知模型调用可能已计费，不自动重试。用户已接管后端重启与付费运行，
  不再由本任务自行发起联网验收；历史连接错误不代表当前网络仍不可用。
  prompt/profile 已变更，用户按计划重启后端后应新建同话题 run 验证，不混用旧检查点。
- 未启动新的后台服务，没有需要用户额外停止的验收进程。任务 F 代码与离线交付完成，
  最终端到端可发布性由用户重启后以新 run 确认。
