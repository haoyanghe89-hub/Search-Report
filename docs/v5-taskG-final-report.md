# 任务 G：结构限定、来源评分、分级与验证收敛交付

> 最新补验：用户随后授权一次 G6 真实调查。两处测试核对/增强后全量
> **487 passed**。真实运行受控 BLOCKED，结果为 **0 VERIFIED / 0 PROBABLE /
> 52 UNVERIFIED / 3 PENDING**，报告仍是 **INVESTIGATION_STATUS / REVIEW_REQUIRED**。
> **业务目标未达标，不能验收为已完成。** 最新完整记录见
> [G6 最终报告](D:/deepsearch/docs/v5-taskG-G6-report.md)。

## 结论与验收边界

G2–G5 代码已落盘，G1 已用真实归档只读诊断并保存前后对比。
新增测试验证：充分证据可 VERIFIED；仅枚举的次要缺口可 PROBABLE；
缺核心字段、没有 ENTAILS、弱来源或未解决冲突不能借此升级。
首轮 G1–G5 没有新建付费运行、联网调用、重启后端或改写历史 run。

首轮依据由用户统一重启并发起付费验收的安排，没有自行付费；
后续用户已明确授权一次，结果见上方最新 G6 补验记录。
不能把离线候选重评分或合成测试称为真实调查成功。

## G1：真实缺失分布与根因

归档运行 `RUN-LIVE-c509dea0251d4494`。诊断快照为 2026-10-02
09:45:41 UTC，实际已推进到 **86 条声明、837 条验证记录**：
85 UNVERIFIED、1 DISPUTED、0 VERIFIED、0 PROBABLE。
这比任务文件的 80 条快照晚，统计采用各声明最新验证基础。

证据文件：

- [修复前诊断](D:/deepsearch/reports/taskg/before-validation.json)
- [修复后候选重评](D:/deepsearch/reports/taskg/after-validation.json)
- [可复用只读脚本](D:/deepsearch/scripts/diagnose_validation_gaps.py)

| 最新 Profile 缺项 | 声明数/说明 |
|---|---:|
| value | 46 |
| unit | 49 |
| definition | 49 |
| methodology 或 provenance | 49 |
| 两个足够质量来源 | 35 |
| 一个足够质量来源 | 14 |
| 两个独立来源族 | 29 |
| 一个独立来源族 | 4 |
| 权威原始发言记录 | 27 |
| 分析推理依据 / 不确定性 | 各 8 |
| 未解决冲突 | 1 条声明 |

计数可重叠，不是互斥失败类别。77 条声明的最新 basis 含低于 0.6 的来源；
参与这些 basis 的评分全部为 0.48。48 条声明至少存在一项 ENTAILS，
不代表已经满足其他条件或全部证据都 ENTAILS。

### “材料有但未带上”与“材料未确定”

- 36 条声明的原句和已保存引文有共同数字，却没有结构化 value；
  34 条有百分号却没有结构化 unit；19 条已有 metric 别名却没有 definition。
  这是确定的结构携带/别名对齐问题，**字面数字重合不是完整语义蕴含**。
- 344 个缺项出现次数，仅凭捕获的引文不能确定完整材料中是否存在。
  不把它们报告为“原文确实没有”，更不补造方法、时间或范围。
- 旧 Profile 把 time/scope 字典容器当作已提供字段。
  新规则正确检查内部字段后，47 条 scope 实际缺少所需限定；
  time 的 as_of 可被读取，空容器不再误判充分。
- 首条 77.9% 声明虽有 3 个来源族，仍缺 value/unit/definition 等，
  且已保存相关判断为 PARTIALLY_SUPPORTS，不能硬升为 VERIFIED。

### 来源评分不是单纯“阈值太高”

公共搜索桥接只识别政府主机，Google/DeepMind 发布页被落为普通网页，
未带 publisher/official 元数据；同时完整的归档可追溯性未参与评分。
不是把所有网页整体提高到 0.6：候选重评普通归档网页仍为 0.52，
正确标记发行机构的相应页面为 0.61。

诊断查询到 56 个 investigation 级 Source，其中可能包含其他 run 的发现；
上述质量统计仅使用本 run 最新验证 basis 引用的来源。
重评在内存中校准发布者元数据、评分与来源族，重用已保存的完整性/语义判断；
未重新验证所有原始 Blob 字节、未调用模型、未写回数据库。

## G2：结构化限定条件

- 分析提示升级为 `investigation-prompts-zh-v6`，明确要求数量声明的
  value/unit/time/scope/definition/methodology/provenance，附 entity/time/scope 分组示例。
  必须由材料支持；缺失就保留缺口，不能照抄示例事实。
- 新声明解析无损解包模型实际提供的 qualifiers；规范 numeric_value、as_of/date、
  benchmark、metric、method、data_provenance 等明确别名。
  数值 0 保留；不同值冲突拒绝，不覆盖；不从正文猜字段，不生成不存在的事实。
- 已存在 Claim 仍使用 F 的精确身份核对，保留 entity/time/scope；
  verifier context 分别传递三组，不再把整个 envelope 塞进 entity。
- 数量 Profile 实际检查 time/scope 内部值。核心五项缺失仍 UNVERIFIED，
  数值竞争仍不得取平均。

## G3：来源评分与独立性配套

- 显式、可注入的发行主机目录识别 `deepmind.google`、`blog.google`、
  `developers.googleblog.com` 的 HTTPS 发布身份；不信查询词/域名子串猜测。
- 共享 GCS、相似域名、HTTP 链接、带用户身份的 URL 不自动升级。
  `is_first_hand` 不凭官方身份设置；官方宣传也不是独立能力验证。
- 新 Source 带 `issuer:Google` 来源族，同一机构多个官方页面合并来源族，
  不虚增独立佐证。来源角色与分数分离，不硬编码 Google 的数值评分。
- 成功解析、具备 cleaned hash、HTTP 200、请求/最终 URL 的归档材料，
  可以得到可追溯性评分；它不等同于测量方法、权威性或真实性。
  12 项平均评分框架不变；普通网页仍低于充分质量档。
- 没有新增依赖、付费抓取服务或数据库迁移。

## G4：VERIFIED / PROBABLE 客观规则

VERIFIED 保留各 Profile 的完整要求，包含完整性链、真实引用、真实 ENTAILS、
所需核心限定、适当来源质量与独立性。`sufficient` 仍表示完整满足，
不能把 PROBABLE 的次要缺口伪装成充分。

新增 PROBABLE 共通条件：至少一个完整声明 ENTAILS、至少两个独立来源族、
至少两个支持来源达到基础可信档 0.5，无强反证、无未解决冲突。
仅允许下表枚举的次要缺口，其余仍 UNVERIFIED；高严重度未解冲突/强反证
继续由原政策判为 DISPUTED。

| Profile | 允许的 PROBABLE 次要缺口；仍不可省略的核心 |
|---|---|
| STATEMENT | 缺权威原始发言；需明确 speaker/publisher 且两个 ENTAILS。只确认谁说过，不确认内容客观为真 |
| EVENT_FACT | 佐证质量差一档；主来源 ENTAILS 且质量 ≥0.6，独立佐证仍需满足 |
| QUANTITATIVE | 质量差一档，或仅缺 methodology/provenance；后一种必须两个来源 ≥0.6 且无其他缺口。value/unit/time/scope/definition 永不豁免 |
| CAUSAL | 仅质量差一档；时间顺序、机制、因果归因、替代解释必须完整 |
| IMPACT | 仅适用质量档不足；因果影响的机制、时序、归因仍不可省略。原因果影响最高 PROBABLE 不变 |
| ATTRIBUTION | 仅质量差一档；合法类型、直接认定、非单一利害方断言不可省略 |
| ANALYTIC_INFERENCE | 仅质量差一档；推理依据、不确定性、多证据不可省略，仍最高 PROBABLE |
| INSTITUTIONAL_ACTION | 缺直接机构原始记录；行动者、行动、时间、范围仍须完整，并由两个可信独立来源支持 |

评分档位 0.5 仅用于**明示保留的 PROBABLE**，不降低原 VERIFIED 的 0.6 门。
完整分级理由与 `missing:` 条目写入已有 basis 文本，不新增 HTTP 字段。
内部版本为 `validation-profiles-v2`、`validation-policy-v2`。

报告生成把 VERIFIED 与 PROBABLE 都视为证据支持的发现，但分别标为
“已验证”和“很可能成立（仍有明确保留项，不等同于已验证）”。
Answer-first 优先已验证发现、再补很可能成立的发现，不再只有状态计数。
writer 内部版本为 `report-writer-zh-v3`。

受控 BLOCKED 的运行若至少有一个支持结论、且所有声明已有一致的最新验证，
可生成 FULL_INVESTIGATION，包含停止原因和限制；若仍有未验证声明，
保留状态报告并展示已有支持发现。**报告类型不等于发布批准**：
引用完整性、关键缺口、冲突、发布审核门均未改，PROBABLE 不自动 PUBLISHED。

## G5：验证上限与收敛

`FeedbackLoopConfig` 内部配置默认：

| 上限 | 默认值 |
|---|---:|
| 完成的验证批次 | 24 |
| verifier 实际模型调用（含修复/失败尝试） | 64 |
| verifier token 上限 | 总 token 的 35%，2,000,000 下为 700,000 |

token 用实际 usage 计量，缺失 usage 用请求字节/输出上限保守估计；
调用在 provider dispatch 前检查。既有调用意图和归档 usage 参与计数，
恢复不清零；同一事件循环的在途请求预算也参与准入。

连续两次完整验证 input fingerprint、结果、引用证据内容集合、冲突集合与
未解决冲突一致时受控收敛；新 Claim、证据或冲突不会被这个停止条件隐藏。
没有可用 Evidence 的声明不派无意义模型调用，仍走原验证政策记录证据缺口。

限额/收敛原因分别为 `VERIFICATION_LIMIT_REACHED` /
`VERIFICATION_NO_INFORMATION_GAIN`，走现有 BLOCKED→REPORT 路径，
不改 FAILED/BLOCKED 对外枚举语义，也不合成通过结果。

任务 D 的阶段预留保持不变：采集为验证预留 25% token、15% 调用；
非 writer 为报告保留 2% token、1% 调用。默认 2M token 留 40,000 给报告，
总量 2M、总调用 480、墙钟上限仍保留；没有通过无限提高总预算掩盖问题。
目前报告 writer 是本地确定性实现，不会额外发起付费写作调用。

## 验证记录

- 新增测试初始红测 5 failed / 8 passed；逐项实现后转绿。
- 早期阶段针对性套件 57 passed；补限额/质量用例后 55 passed。
- 最新修复/多 Profile/收敛/报告针对性回归 **52 passed，10.04 秒，退出 0**。
- 首次全量发现 3 个失败：内部 policy/writer 版本断言过时；
  新测试错误更新 append-only 验证历史。已更新版本断言，
  测试改为初始化目标状态，**未移除不可变数据库保护**。
- 最终全量 **486 passed / 3 skipped / 7 deselected / 1 warning，189.43 秒，退出 0**。
  3 项是 Windows 符号链接/POSIX 条件跳过，7 项依赖 live/infrastructure 未运行；
  保留既有 Starlette/AnyIO 弃用警告，不将跳过项冒充通过。
  命令：`.venv/Scripts/python.exe -m pytest -m 'not live and not infrastructure'
  --basetemp=reports/taskg/pytest-release -p no:cacheprovider -q --tb=short`。
- Ruff `src tests scripts`、本轮 22 个 Python 文件格式检查、compileall、导入、
  `git diff --check` 已退出 0；既有 LF→CRLF 提示不是空白错误。
- Investigation Console OpenAPI SHA256（排序、默认 JSON separators）：
  `8a7ac4bb65c741aa7c54002ec9c12a1f75963da552e04e709547928429bdaf9e`，
  与 B–F 基线一致。路由、请求/响应字段、状态枚举、前端均未因 G 改动。

离线候选重评：**0 VERIFIED / 0 PROBABLE / 85 UNVERIFIED / 1 DISPUTED**。
它不是新模型生成后的端到端结果，也没有报告产出或发布状态变化。
仅升级评分不能修复旧 Claim 中缺失的数字核心与部分支持关系；
这些声明保持未验证正是严谨性检查的预期结果。

## 本轮文件清单

生产代码（均在原 A–F/UI dirty tree 上增量修改）：

- `src/marketpulse/adapters/investigation_search.py`
- `src/marketpulse/investigation/agents/{normalization,prompts}.py`
- `src/marketpulse/investigation/feedback/{context,models,orchestrator}.py`
- `src/marketpulse/investigation/harness/{calls,stage_budget}.py`
- `src/marketpulse/investigation/live_runtime.py`
- `src/marketpulse/investigation/reporting/{assembler,chinese_writer}.py`
- `src/marketpulse/investigation/services/source_acquisition.py`
- `src/marketpulse/investigation/validation/{policy,profiles,quality}.py`

测试：

- 新增 `tests/unit/investigation/test_validation_convergence.py`
- 更新 `tests/unit/investigation/{test_validation_core,test_phase5_writer_validation}.py`
- 更新 `tests/integration/investigation/{test_phase42_validation_persistence,test_phase43_feedback_loop,test_phase5_report_pipeline}.py`

诊断/交付：`scripts/diagnose_validation_gaps.py`、本报告、
[执行计划](D:/deepsearch/docs/superpowers/plans/2026-10-02-validation-convergence.md)、
`reports/taskg/{before-validation,after-validation,verification}.json`。
仓库整体 diff 包含前轮工作，不作为 G 的修改范围；未提交、重置或清理用户文件。

## 已知限制与用户交接

1. 首轮未付费重跑；后续授权的 G6 已实际运行，但最终结论性发布目标未通过。
   不保证模型执行新提示后必然完整，也不为了达成比例把部分支持升级。
2. 发布主机目录仅覆盖本题已核对的 Google 发布入口与既有政府识别。
   GCS 等共享域名不凭 URL 推断为官方；其他发布者需可信明确元数据。
3. 历史 Source 元数据、Claim 及验证历史没有改写。提示/政策/配置版本已变化，
   **重启后请新建同话题 investigation/run，不恢复旧检查点**；
   在旧 investigation 下复用原 Source 仍会带旧元数据，不能假设自动回填。
4. 有价值的正文与高来源分不等于支持完整声明；引用不匹配、缺数字范围、
   高严重度冲突仍可阻止验证或发布。达到限额时未验证部分仍保留不确定性。
5. 没有新增后台进程；旧后端可能仍运行已加载的旧代码，本轮未接管或停止它。

首轮代码与离线修复交付；后续授权 G6 的真实可发布结论目标未通过，
具体残留和运行证据以 [G6 最终报告](D:/deepsearch/docs/v5-taskG-G6-report.md)为准。
不能据回归全绿宣称业务目标完成；本次授权的一次真实运行已结束，未追加第二次付费。
