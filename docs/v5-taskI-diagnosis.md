# 任务 I：真实运行诊断（I1，执行记录）

日期：2026-10-02。对象：`RUN-LIVE-434153bec43c405f`。

本轮完成真实只读诊断并落盘；尚未修改后端/前端/HTTP 契约、验证门槛或历史运行数据，也未发起新的付费模型生成/调查。第二步实施及第三步回归/E2E 尚未完成，不能把本文当作任务 I 最终通过报告。

## 1. 官方模型清单：任务中两个旧 ID 已退役

用项目 `.env` 的凭证 GET `https://api.deepseek.com/models`，返回 HTTP 200。密钥和 Authorization 头未打印或落盘。沙箱首次请求被 WinError 10013 拦截，获准执行网络请求后成功；此权限错误不能作为运行中的网络故障证据。

| 请求核对的 ID | 真实清单 | 官方说明 |
|---|---|---|
| deepseek-flash | 有，名称 DeepSeek-V4.1-Flash | 当前模型，文本/图像输入、文本输出 |
| deepseek-chat | 无 | 官方公告说明旧 ID 于 2026-07-24 退役 |
| deepseek-reasoner | 无 | 官方公告说明旧 ID 于 2026-07-24 退役 |
| deepseek-v4-pro | 有，名称 DeepSeek-V4-Pro | 当前 Pro 模型，文本输入/输出 |

两款列出的模型均返回 1,048,576 context_window、393,216 max_output_tokens，effort 支持 low/high/max、默认 high。`/models` 证明当前可用清单，不等于已对每个 ID 发起付费生成探测；没有为确认已退役 ID 而进行付费请求。

官方 [退役公告](https://api-docs.deepseek.com/news/news260424/)、[最新更新](https://api-docs.deepseek.com/updates/)、[思考模式参数](https://api-docs.deepseek.com/guides/thinking_mode/)、[Chat Completions 参数](https://api-docs.deepseek.com/api/create-chat-completion/) 均与本次清单一致。现行思考模式通过 `thinking.type=enabled` 和 `reasoning_effort` 控制；temperature 在思考模式无效，最终答案在 content，reasoning_content 不能当作结构化答案解析。

因此不能按任务文本把默认直接改为 deepseek-chat / deepseek-reasoner。用户随后指示执行诊断后继续修改：采用 flash 非思考模式作为常规调用、v4-pro 思考模式作为关键推理角色，并保留环境变量及强制单模型选项。退役 ID 不会被自动替换为另一个模型。

2026-10-02 11:29:23 UTC 再次实际 GET，HTTP 200，清单不变。最新原始清单已保存至 `docs/taski/i1-model-list.json`，不含凭证。

同轮已实际重跑数据库排查：`docs/taski/i1-validation-basis.json` 与 `docs/taski/i1-analysis-recordings/`；补充详细分布、质量组件、上下文与归档 PDF 重解析数据已复制至 `docs/taski/`。所有历史诊断均保留，数据库没有写入。

## 2. 运行实际规模与终态

数据库以 SQLite mode=ro 打开，只读事务采样；Blob 按 SHA-256 校验后读取。

| 项 | 实际值 |
|---|---|
| Run | BLOCKED / REPORT |
| 原因 | VERIFICATION_LIMIT_REACHED，已有验证上限正确生效 |
| 搜索 / 抓取 / 模型调用预算计数 | 169 / 55 / 145 |
| tokens_used / max_tokens | 777,058 / 2,000,000 |
| sources_used | 49（预算计数，不等于去重来源数） |
| 有本 run Snapshot 的去重 Source | 43 |
| Evidence | 68，来自 10 个 Source |
| Claim | 67：55 UNVERIFIED / 12 PENDING / 0 VERIFIED / 0 PROBABLE |
| ValidationResult | 295（历史累计，非 295 个不同声明） |
| Report | RPT-1e7478a2f45d / INVESTIGATION_STATUS / REVIEW_REQUIRED |

145 个模型记录：12 analyst.analyze 成功，9 analyst.decompose 成功、2 INVALID_RESPONSE，4 planner 成功，60 researcher 成功，58 verifier 成功。成功记录全部 model=deepseek-flash。不能据本次记录单独断言“已经测试了强模型但仍失败”。

## 3. 分 claim_type 的缺口分布

下面只统计每条声明的 latest_validation_id；PENDING 不混入缺口分母。历史重复验证不重复计入本表。

| 类型 | 总数 / 已验证评估数 | 至少一个 ENTAILS 的声明 | 主要缺口（声明数，可重叠） |
|---|---:|---:|---|
| QUANTITATIVE | 26 / 20 | 11 | time 20；definition 15；value 7；unit 9；scope 3；2 adequate-quality Sources 16，1 adequate-quality Source 4；2 independent families 13，1 independent family 1；无完整 ENTAILS 9 |
| STATEMENT | 4 / 4 | 2 | authoritative original statement record 4；attributed statement 无精确 ENTAILS 2 |
| ATTRIBUTION | 18 / 12 | 9 | attribution_kind、interested-party boundary、independent support、2 quality Sources、direct finding 各 12；无完整 ENTAILS 3 |
| ANALYTIC_INFERENCE | 19 / 19 | 14 | reasoning_basis、uncertainty、2 quality Sources 各 19；multi-family 17；multiple Evidence 13；无完整 ENTAILS 5 |

最新评估的 73 个 claim/evidence 判断为 39 ENTAILS / 33 PARTIALLY_SUPPORTS / 1 CONTRADICTS。55 条已评估声明中已有 36 条至少有一个 ENTAILS；“0 VERIFIED”不等于“没有任何 ENTAILS”。

12 次分析输出中，排除复制 existing_claim 的定义后有 48 个新候选：QUANTITATIVE 14、STATEMENT 3、ATTRIBUTION 11、ANALYTIC_INFERENCE 20。候选与最终声明不是同一分母（去重、分解会改变数量）。14 个新数值候选中显式字段出现次数：value 8、unit 6、time 0、scope 14、definition 3、methodology 1、provenance 14。原始分析输出的 time_qualifiers 已为空，不是持久化后才全部丢失。

14 个数值候选的分析上下文均有日期字样，但不能据此认定该日期就是该指标的测量时间；它可能属于其他材料。20 个缺 time 的最新数值声明的完整性合格引文均没有检测到明确日期模式。这是文本线索统计，不是自动填值依据。

保留了 entity/time/scope 分组，未扁平化修改历史声明。证据：`i1-validation-basis.json`、`i1-detailed-diagnosis.json`、12 个 `i1-analysis-recordings/CALL-*.json`。

## 4. 77.9% 示例：确切断点是引文上下文被截断

声明 `C-1be3b1dca342dcdbfbccf40a`：谷歌官方公布的评测表中，Gemini 4 Argon 在 DeepSWE v1.1（Agentic coding）得分为 77.9%。

第一次生成该声明的分析记录 `CALL-7ef4d9ae6bf44c6abc2bb27544a28efc` 已有 value=77.9、unit=%、benchmark、scope、methodology URL、vendor-reported provenance，但 time_qualifiers={} 且没有 definition。现有 parser 没有凭空移除这两个字段。

该声明最终具有 5 个完整性合格 Evidence，但只有 3 个在 latest basis 里有语义判断，均为 PARTIALLY_SUPPORTS；没有 integrity failure、strong contradiction 或 unresolved conflict。独立 family 数为 3，但质量合格的支持 Source 只有 DeepMind 官网一个（0.64），另两个是二手站（各 0.52）。

真实验证记录 `CALL-330d01d3ec29414c8fb56eb0862e340a` 的完整 typed output 已保存。它没有空 judgments，也没有缺失 claim_key/evidence_key/entailment/rationale：

- 官网表格引文含 DeepSWE v1.1、Agentic coding、77.9% 等数字，但没有列头和 Gemini 4 Argon 名称；首字符甚至从 `eepSWE` 开始。验证器说明无法确认 77.9% 属于哪个实体、发布方是否谷歌。
- 中文二手引文含同一基准和得分，但缺实体及官方出处归属。
- 第三方引文含得分、vendor-reported/no independent replication，但同样没有点名 Gemini 4 Argon。

这三段 PARTIAL 的依据是可解释的证据不足，不应直接改判 ENTAILS。强模型也不能靠猜测表格列归属；应提供真实可定位的同表列头/相邻语境再判断。

该例有 33 个历史语义记录（3 个 Evidence 的判断重复存储），不足以当作 33 次不同模型推理。本轮 58 次 verifier 成功调用的 typed outputs 合计 91 个判断：ENTAILS 47 / PARTIALLY_SUPPORTS 43 / CONTRADICTS 1；数据库语义历史累计是 195 / 228 / 9。复用与重复落库必须和真实调用次数区分。

## 5. 原材料不缺：官方 PDF 后续页面未进入 artifact 记录

官方 PDF Source `S-ecb4c55bf181277ed4ce17799031be36` 已 ACCEPTED，归档 352,830 bytes，cleaned text 6,617 字符，包含 5 页。原始 PDF SHA-256：`ff1df6bdeddc4c0f48840c09a8a7813b10ae7ad9e053892da68dabf64f09bff7`。

对该归档原文件离线重跑当前 parser，得到 5 个 PDF_PAGE_TEXT，字数为 71 / 2,337 / 2,896 / 1,189 / 71；页面 hash 均落盘。数据库却只存在 page 1 的 71 字符封面 artifact（ID `A-d2adf71a421818a99feeae39051667df`）。

12 次分析共暴露 192 个 artifact 片段；该 PDF 出现 3 次，全都只有封面 0:71。官网博客出现 8 个片段（其中一个含 Sep 30, 2026）；两者都未产生 Evidence。完整 PDF 第 2 页有“所有 Argon scores 是 pass @1，除非另有说明”，后续有 DeepSWE self-computed/mini-swe harness；第 2 页有 September 2026、第 5 页有 October 2026。定义确实存在于归档，但没有送入模型的可引用 artifact；日期需区分 benchmark 范围与结果截至时间，不能挑一个猜填。

当前源码的 PDF parser 返回多页，source_acquisition 循环生成 artifact，`_stable_factory` 为各 artifact 生成不同 ID；没有找到当前源码中明确的“只存第一页”分支。由此证明历史 run 的可引用页面缺失，但尚不能断言是当前工作区该循环的 bug。必须先核对实际启动后端使用的 checkout/代码路径，并用真实归档做采集 UnitOfWork 回归，不能盲改 parser 或数据库。

证据：`i1-pdf-reparse.json`、`i1-qualifier-contexts.json`。

## 6. 来源质量：元数据缺失与未进入验证，不能混为评分阈值问题

仅 10 个 Source 进入 latest validation 的 quality_scores：9 个二手站 0.52、DeepMind 官网 0.64。PDF 与官方博客都没有 persisted claim-validation score，因为未形成 Evidence。

| 来源 | 持久化 latest 分数 | 全本 run 来源族的离线重算 | 真实原因 |
|---|---:|---:|---|
| deepmind.google/models/gemini | 0.64 | 0.61 | 已识别官方，满足 0.6；离线全 run 族与原验证子集的族大小不同，分数不能混同 |
| 官方发布博客 | 未评分 | 0.61 | 已识别官方，但 Evidence=0 |
| storage.googleapis.com/deepmind-media 官方评测 PDF | 未评分 | 0.52 | source_type=WEB_PAGE、official=false、first_hand=false、publisher=null；方法学正文存在，但 provenance 没带入 methodology |

PDF 的 component 值：first_hand 0.25、official 0.5、primary_source 0.25、named_author_source 0.25、methodology 0.5；可追溯 archived provenance 已是 1.0。应该修正有实际发布链证据的元数据，不是让任意 storage.googleapis.com 内容都自动成为官方，亦不是给二手站统一保底 0.6。

官网已归档 HTML 明确链接 `https://deepmind.google/models/evals-methodology/gemini-4-argon`；没有在这些已检查的原始链接中发现对具体 storage PDF 的直接 href。若要传播官方身份，需追溯该方法学 URL 到 PDF 的发布链或其他明确出处，不能仅凭 host 猜测所有权。

另有一个具体评分问题待测试：`syndication_cluster_id=issuer:Google` 用于同发行方来源族，当前质量评估却把任意 syndication_cluster_id 当成转载深度较高，给 retransmission_depth=0.25。这不应通过拆开 Google 来源族来修复；来源独立性仍必须合并同发行方。

证据：`i1-materials-quality.json` 的完整 components/basis。

## 7. 实施边界与尚需确认项

属于现有验证链的有界修复：模型角色路由/兼容参数，真正可引用的多页与表格语境，基于定位证据的 qualifiers 补全，发布链元数据评分，现有严格 PROBABLE 规则对齐。HTTP、前端、独立性底线、引用 hash 和完整语义判断门槛不变。

有效模型路线已按后续继续执行指令实施；不得默认发出旧 ID 请求。后续每一步结果另记于 `docs/taski/progress.md`，在测试与实际 E2E 完成前不宣称最终通过。

还有工作区前提不一致：当前 `harness/calls.py` 的 model 方法仍是单次 `_model` 调用，`live_runtime.py` 仍开启 pause_on_unknown_outcome，未见任务 H 的自动指数重试循环；Settings 也未见模型独立超时/重试配置。本报告只能描述当前磁盘源码，不能宣称 H 已在这份 checkout 生效。真实运行的“网络抖动已恢复”不能代替核对启动代码路径。

待确认后才进入实现、独立 basetemp 全量测试/Ruff/导入/diff，以及一次经授权的真实 E2E；不会为了凑 VERIFIED/PROBABLE 数修改历史数据或放松来源独立性。

## 8. 本轮交付与限制

新增诊断报告及 reports/taski 诊断产物；后端和测试代码零改动。旧运行记录的是模型已解析/可能规整后的完整 typed output，而不是 HTTP 原始 response text：未被留存的原始 wire JSON 不能恢复，报告不把 typed output 冒称原始 wire 内容。

所有诊断/归档重解析命令成功；完整性 hash 校验成功。模型清单 HTTP 200。尚未运行任务 I 修改后的后端测试（因为未实施），尚未发起付费 E2E，不能宣称任务 I 全部完成或结果已可发布。
