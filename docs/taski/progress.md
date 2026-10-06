# 任务 I 执行记录

## 步骤 1：真实诊断复核（2026-10-02）

- 官方 GET /models：HTTP 200；有效 ID 为 deepseek-flash、deepseek-v4-pro。旧 chat/reasoner 不在清单中。
- 数据库只读诊断脚本退出码均为 0：67 声明，55 UNVERIFIED / 12 PENDING；12 次完整 typed 分析输出导出。
- 主要断点：量化候选 time 已在生成时缺失；PDF 归档有五页，但历史可引用 artifact 仅第一页；77.9% 引文缺表头导致 PARTIAL 是合理判断；官方 DeepMind 质量 0.64 已达门槛，不能把二手来源 0.52 强行改高。
- 具体评分缺陷：issuer:Google 来源族标记被误当作转载标记；修正质量解释时仍保留同发行方独立性分组。
- HTTP、历史数据库与证据门槛未修改；尚未发起新的付费调查。

## 步骤 2：实施中

先做角色路由、请求参数/记录身份与发行方评分的针对性回归；再处理有定位依据的证据上下文与限定条件。不得用弱化 ENTAILS 或拆分官方来源族来制造确认数。

### 优先级 1：多页材料

- 真实原始 PDF SHA ff1df6bd… 已在隔离数据库沿 SourceAcquisitionService.prepare + UnitOfWork 重放。首次解析正确产生 5 页，旧复用分支在模拟仅封面入库后只返回 1 页；回归先失败，证实问题是“不完整快照被视为完整并复用”，不是当前 PDF 循环只解析一页。
- 补齐缺页从 hash 校验的原始归档重解析，保持旧 snapshot、旧 artifact 和引用不变；缺页与步骤完成一同提交。新快照带页号/hash manifest。真实归档修复后 5 页均持久化，字符数 71/2337/2896/1189/71；真实回归 1 passed，退出码 0。
- HTML 表格增加独立可定位 artifact，把原始标题/列头与对应单元格一起归档；复杂合并单元格不猜列归属。分段不再从英文词内开始。两项回归先失败后修复，合并回归执行中。
- 限制：PDF 页中的纯图像表格不会伪装成已提取文本；没有 OCR 就不能编造那些单元格。后续优先引用有真实列头的 HTML 表格，保留原 PDF 可读页。

### 优先级 2–3：角色路由、限定条件与来源

- Harness 在请求指纹/预算/durable intent 前明确选模型、thinking、effort；恢复 profile 包含全部路由配置。flash 常规、v4-pro 关键分析/验证；强制单模型可关闭分流。思考模式不传 temperature，最终只解析 content；保持 JSON schema 校验。角色/适配器相关 41 项通过。
- 新增内部 qualifier_supplements：值和证据引文必须逐字来自本声明的支撑 Evidence，禁止覆盖/重复/竞争值；时间还需明确 RESULTS_AS_OF / EVALUATION_PERIOD，不使用发布日期猜评测日期；必须同时有完整 ENTAILS。补全先做 Evidence 完整性校验，随后与验证投影、补全审计记录原子提交，保留 entity/time/scope。
- 实际 GET 官方方法学 URL 返回 301 → storage.googleapis.com/deepmind-media/gemini/gemini_4_argon_model_evaluation.pdf，最终 200；证据已写 i2-publisher-chain.json。采集记录官方 URL 到 PDF 的实际重定向链和方法学出处，任意 storage 域名不自动成为官方。
- 官方发布自有材料作为一手“发布方报告”，不当作独立真实性证明；修正 issuer: 来源族被误扣转载分，同发行方仍只算一个独立族。限定条件/质量相关 28 项通过。
- PROBABLE 的核心精确蕴含与独立性门槛保持不变，未改 PARTIAL 或未解冲突的判定。

### 优先级 4–5：分级与有界网络重试

- 四类 PROBABLE 针对性测试（QUANTITATIVE/STATEMENT/ATTRIBUTION/ANALYTIC_INFERENCE）核对：真实引用、精确 ENTAILS 和独立性仍不可豁免；PARTIAL 或单族仍 UNVERIFIED，未修改现有门槛。
- 所有 LIVE Harness 模型调用默认启用最多 3 次重试（总计 4 次 dispatch），指数退避 1/2/4 秒；同 durable intent 重试记录 ALLOW_POSSIBLE_DUPLICATE_CHARGE，恢复后仍受持久化次数上限约束，成功结果复用不重付费。
- 传输读取 120 秒/连接 15 秒，SDK 重试关闭，运行级异步客户端复用；超时取消后才重试。未知结果保守计入 token 预算，避免重试绕过总量/阶段预留。
- 429/5xx/超时/连接中断可重试；400/402 不重试。耗尽进入受控 BLOCKED 且保留材料，402 明确余额不足。仅 LLM 只读推理无外部写入副作用，自动重试仍可能产生重复 token 费用。
- 搜索已有多后端超时/429/5xx 退避与熔断，抓取已有有界重试/坏 URL 冷却与来源级跳过；不重复新增其他重试层。
- 前两次未知第三次成功、持续未知受控 BLOCKED、结果复用和材料保留的模型恢复/LIVE 回归 19 passed；新增错误类别和限定条件原子提交回滚测试通过。
- 全量首次 487 passed / 15 failed：14 项是旧测试 integrity 白名单未识别 HTML v3，1 项是补全持久化操作归属 validation 违反层间依赖。已增加合法 v3 白名单，并把操作移到 feedback 层，未弱化 Evidence 完整性门；相关 27 项重新通过。
- 最终全量回归运行中；Ruff、compileall、核心导入和 git diff --check 均已通过。未修改前端、HTTP schema 或历史数据库。

官方参数核对：https://api-docs.deepseek.com/guides/thinking_mode/ 及 /api/create-chat-completion/；thinking 通过 extra_body，effort 独立参数，思考模式不传 temperature，reasoning_content 不作为最终结构化答案。

## 步骤 3：测试与唯一真实 E2E（2026-10-02）

- 全量后端回归：514 passed / 3 Windows 平台能力 skipped / 7 live/infrastructure deselected，186.67 秒，退出码 0。PDF image 缺口标记加入后真实归档 + 解析回归另跑 25 passed；再次全量执行并输出 JUnit XML。
- PDF 文本解析 v2 显式记录含图像未提取页；旧 v1 artifact 仍受原完整性规则认可，无 OCR 时保留图像缺口，不把纯图像表格视为文本完备。
- OpenAPI SHA256 改动前后一致：8a7ac4bb65c741aa7c54002ec9c12a1f75963da552e04e709547928429bdaf9e。
- 用户授权的唯一真实 E2E 已启动：RUN-LIVE-7217d8f06f34422a，UTC 2026-10-02 12:07:26；隔离库 reports/taski/i3-live-20261002/live.db。原题目复制自 RUN-LIVE-434153bec43c405f，历史数据库仅只读。
- 配置：flash 非思考，v4-pro/high 思考；总 token 2,000,000；最多 480 model dispatch；墙钟 3600 秒；未知结果最多 3 次重试。configuration.json、progress*.json、分析 content 和最终 final.json 落在上述目录。不默认再发起第二次付费调查。
- E2E 的确认数、报告类型与发布状态尚未得出，不能以单测通过冒充真实达成。

### 真实 E2E 暴露的首要入库根因与修复

- 更正前面的初步归因：不完整快照复用是次级放大因素。真实 E2E 原始 HTML 可解析为主正文与表格两个 artifact，但数据库只保留第一项，证实直接丢失点在 feedback/orchestrator.py::_entity_identity：按字段顺序误选 DocumentArtifact.snapshot_id 外键作为身份，同一 PDF/HTML 快照的兄弟 artifact 被合并掉。ResearchGap.source_id 也有相同问题。
- 已改为各实体真正主键（artifact_id/gap_id 等），保持同主键幂等，不再跨页或跨表格去重。新回归沿完整 ResearchTeam → 合并 → Harness UnitOfWork 路径，确认五页 PDF 与 HTML 表格全部持久化；HTML 不完整快照从 hash 校验归档补回表格，无重复抓取。
- 采集相关 13 passed；真实 ff1df6bd… 研究步骤路径已另跑 1 passed。最终全量再次运行，不能用修复之前的 514 passed 代替最新结果。
- UTC 12:28 核对并终止本任务隔离 worker，随后仅恢复同一 RUN-LIVE-7217d8f06f34422a，从 durable checkpoint 加载新代码；没有新建第二次调查。续跑输出 reports/taski/i3-resumed-20261002，数据库及 blob 仍为原隔离目录。恢复时保留 370014 已用 token / 51 model dispatch / 36 fetch，未重置预算。
- UTC 12:35 的真实隔离数据库审计确认 ff1df6bd… PDF 五页全部存在，字符数仍为 71/2337/2896/1189/71、哈希全部匹配。后续结果不会靠只计 cover 的测试代替真实路径验证。
- 增加官方方法学 URL 实际重定向到 PDF 的采集/评分回归，以及裸 storage URL 不得判官方的反例；采集组 15 passed。这不把缺少发布链的云存储材料自动补成官方。
- 旧 CLI 的 Agents SDK 路径也统一连接/读取超时及有界退避；400 不重试，402 明确余额不足。直接/包装的 TimeoutError、ConnectionResetError 纳入允许的诊断类别，不记录异常敏感文本；相关 13 passed。

### 真实 E2E 终态与交付边界

- UTC 12:38:08 唯一 RUN 在 VERIFY 返回 HTTP 402，明确余额不足；受控 BLOCKED，生成 RPT-7d27f1b675ad / INVESTIGATION_STATUS / RESTRICTED，材料保留，不再请求付费模型。
- 实际 44 来源（38 合格）、34 Evidence、37 Claims：36 UNVERIFIED / 1 PENDING / 0 VERIFIED / 0 PROBABLE；82 search / 44 fetch / 77 model dispatch / 599743 token。PDF 五页完整入库，第 2 页有 2 个 Evidence；没有声称其他页已引用。
- 真实发布目标未达成，不能仅归因于 402：缺 time/definition、二手支撑与 PARTIAL 等缺口仍在。完整审计与剩余分布已写 docs/taski/i3-terminal-audit.json 和 docs/v5-taskI-final-report.md。
- 新增全部回归后的最新全量执行中；此前 522 passed 仅作为阶段结果，不代替最后包含发布链两项测试的全量。
- 最终全量 524 passed / 3 平台 skipped / 7 live/infrastructure deselected，254.98 秒，退出码 0；JUnit reports/taski/final-delivery.xml。Ruff、compileall、核心导入、git diff --check 最后重跑均为 0，OpenAPI SHA256 仍与基线完全相同。

## 继续实施第 3–5 项（2026-10-02）

- 已扩展有证据的补全字段到 value/unit/scope/speaker；仍要求关联 Evidence 原文精确包含值、全文 ENTAILS、禁止覆盖、日期语义明确。保留 entity/time/scope 分组与原子提交。
- 修复 Profile 只读根字段的对齐缺陷：数值、方法、说话者、归属与推理限定均能读取持久化分组；根与分组冲突时缺失处理，不擅自选值。先跑限定条件与 Profile 回归 37 passed。
- 新增官方 HTML 发布 PDF 的链接记录（归档原文 + anchor），以及同次运行、hash 核验的官方发布链视图。仅同哈希官方重定向或先于文档取得的官方发布链接能校准裸云存储 PDF；不按 storage 域名判断，不抬高二手来源。质量 basis 保留发布者快照 ID/hash 与关系；出版页/PDF 合并同 issuer 家族，不能当作两个独立来源。
- 历史 Source/原始档案不改写；采集发布边持久化在 snapshot.provenance，分析与验证使用可重建的元数据视图。新 E2E 尚未开始，不能声称确认/发布目标达成。
- 发布边收紧到明确发布者/our report 的原文锚点，不把官方页面的一般外部引用当作一手身份依据。校准 proof 进入持久化 validation_basis_payload.special_checks。
- 首轮全量 530 passed / 2 failed / 3 skipped / 7 deselected；两项录签回放均因新增出处 run-local snapshot_id 导致指纹不一致。改为稳定 raw hash 标识后，两项单独通过；再次全量使用独立 i4-full-fixed-20261002 basetemp 和 JUnit。
- 最终全量 532 passed / 3 Windows 能力 skipped / 7 live/infrastructure deselected，206.85 秒，退出码 0；Ruff、编译/导入与 diff 检查通过。网络重试耗尽 BLOCKED/材料保留用例额外单独通过。
- 按本次授权，仅启动一轮同原话题的隔离真实 E2E：输出 reports/taski/i4-live-20261002；复制 RUN-LIVE-434153bec43c405f 的原调查问题，历史库只读，token 2,000,000 / 480 model dispatch / 3600 秒，无额外扩大预算。
- 真实新 RUN-LIVE-b178a218f9e84f09 在首个规划请求返回 HTTP 402；录签 provider_diagnostics 明确 http_error/402，受控 PLAN/BLOCKED，1 model dispatch、0 token、0 来源/证据/声明。未重试 402、未新建第二个付费 RUN；进程退出码 0（受控结束，不代表目标达成）。
- 状态报告 RPT-3e63ed7f3794 / INVESTIGATION_STATUS / RESTRICTED；终态审计 docs/taski/i4-terminal-audit.json，续交付报告 docs/v5-taskI-continuation-report.md。结论报告/真实 VERIFIED-PROBABLE 发布目标仍受余额不足阻断，不能以回归通过替代验收。
