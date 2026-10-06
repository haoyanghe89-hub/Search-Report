# 任务 C：抓取与正文提取最终报告

日期：2026-10-02。调查对象：`RUN-LIVE-68180c92a8cb4cb0`。本轮仅修改后端及诊断/测试文件；保留既有 A/B/v3 和前端改动，没有提交 Git、重启现有服务或发起付费模型调查。

## 1. 结论与真实根因

本次历史运行的直接瓶颈在 **HTTP 请求之前的 DNS 安全校验**，不是已经抓到网页却被正文提取器全部误杀。

只读检查根目录 `data/blackboard.db` 及校验 SHA256 的请求记录得到：

| 历史记录 | 结果 |
| --- | --- |
| 搜索调用 | 155：132 PROVIDER_ERROR，23 SUCCESS |
| 抓取调用 | 85：全部 SECURITY_BLOCKED |
| 唯一请求 URL / 域名 | 67 / 40 |
| 已发现 Source 记录 | 67 |
| SourceSnapshot / 正文 artifact / evidence / claim | 全部 0 |
| 运行预算 | search 155、fetch 85、sources_used 85、research_rounds 4 |
| 终态 | BLOCKED / REPORT / INVALID_AGENT_PROPOSAL |

历史 85 次抓取的分类占比：**安全拦截 85/85（100%）**。这些记录没有 HTTP 响应 blob，也没有具体安全子原因；HTTP 状态、最终 URL、HTML 大小和正文长度均不可从历史记录恢复，不能填成 HTTP 0 或推断为 403/429。网络超时、反爬、重定向、正文为空和入库误杀在这批记录中均没有进入对应阶段，不能据此判断其在公网的一般占比。

当前复现中，历史请求涉及的 40 个域名都解析到 `198.18.x.x/198.19.x.x`，85 次请求实例均对应这种代理 fake-IP DNS；修改前本机 `MARKETPULSE_ALLOW_PROXY_DNS=false`。严格模式对同类 URL 在 HTTP 请求前返回安全拦截；启用项目已有的可信代理选项后，同批样本可发出请求。因此，**代理 DNS 与本机配置不匹配是有复现支持的根因判断**，但不是旧记录中已经保存的安全子原因。

搜索能返回链接而抓取不能发出请求并不矛盾：两条适配器路径的 DNS 安全校验不同。反馈态来源由 snapshot 构建，没有 snapshot 就显示 0；67 条发现记录不等于 67 条有效正文来源。旧 `sources_used=85` 也不代表 85 条有效来源，它还包含了重复失败 URL 的发现预算计数。

### 用户批准的本机配置

仅将 [项目 .env](D:/deepsearch/.env:21) 中已有 `MARKETPULSE_ALLOW_PROXY_DNS` 改为 `true`，已验证 `Settings.from_env()` 读取为 true。未改 `.env.example` 或全局默认值，未输出任何密钥。

此选项仅允许域名通过可信代理解析到 `198.18.0.0/15`；localhost、私网、直接 fake-IP URL、带凭据 URL 和不安全重定向仍被阻止。每一跳继续检查目标域名。**代理本身必须可信。现有后端进程未重启；用户重启后才会加载新配置，且启动进程中的同名环境变量仍可能覆盖 .env。**

## 2. C2：抓取健壮性

保留现有 httpx 流式请求、每跳 SSRF 校验、5 跳重定向上限、MIME 白名单、字节上限和取消语义；没有第三方阅读代理或反爬绕过。

- 保留真实的项目 User-Agent，新增 Accept；内部 Accept-Language 按调查标题中的中英文选择，不增加外部请求字段。
- 将原有有限重试扩展到 HTTP 500 等全部 5xx；429、超时及传输异常沿用有限退避。默认最多 3 次尝试，退避 0.25/0.5 秒；请求超时和运行/步骤期限仍使用现有配置。
- 403 不在同一调用中反复重试；403、最终 429 和明确挑战页按 URL 冷却 120 秒，缓存上限 256。重复调用仍如实计入逻辑 fetch 调用，但冷却期间不重复发出 HTTP 请求。其他发现链接继续由原有获取流程处理。
- 识别常见 HTML 200 挑战页；“文章只是提及 captcha”不会因此被拒绝。
- 为安全、HTTP、重定向、MIME/字节上限等错误附加内部有限原因码；原有异常类别和外部错误码保留。

## 3. C3：正文、质量过滤与可观测性

没有新增依赖，使用已有 BeautifulSoup 实现正文选择链：

`article/main/role=main/articleBody/Wikipedia 内容区 → 段落密度及祖先容器 → 清理后的 body`

- 按 HTML 声明处理编码，移除脚本、样式、隐藏内容和导航噪声。保留官方记录系统中包裹正文的普通 form，仅移除搜索 form。
- 段落候选同时考虑相邻 div/span 事实字段，避免只保留一段较长文字而漏掉官方记录中的其他事实。
- 明确拒绝挑战页、搜索结果页、导航/标签页、明显高链接密度页面、空正文、少于 120 字符的正文和短小 JS 空壳。拒绝结果保留原始 snapshot 与可解释 gap，不生成正文 artifact，不将空材料升级成证据。
- SSR 页面有实质正文则可接受；只靠 JS 生成正文的空壳明确标记 `JS_RENDER_REQUIRED`，没有新增浏览器渲染器。
- 在选择正文前检查全页可见文本中的不可信指令；外部内容仍为 UNTRUSTED。证据 hash、locator、声明校验和发布质量门完全保留。
- HTML parser 版本升为 2，支持版本表追加 2 并保留 1；未知版本仍拒绝，旧 artifact 不会重写。

观测数据写入已有位置，不增加 HTTP DTO 字段：

| 位置 | 内容 |
| --- | --- |
| `fetch_result` 结构化日志 | 域名、HTTP 状态、已读取字节数、失败类型/原因 |
| RecordedToolCall 原有 metadata | 失败原因码、域名、状态、字节数；严格白名单与类型/范围校验 |
| Snapshot 原有 provenance 字典 | `acquisition_diagnostics`：状态、HTML 字节、正文字符、是否可用、过滤原因、提取方法 |
| acquisition_result 日志 / ResearchGap | run/source ID、获取及解析结果、明确失败原因 |

不记录密钥、请求敏感头、正文全文或异常中的任意私密字符串。HTTP 错误正文未读取时，已读字节为 0，**不代表服务器错误页的实际大小为 0**。调用计数、发现来源容量及 `valid_source_count` 三者保持不同含义。

发现预算按 **本 run 已有 snapshot 来源 + 失败 gap 的 source_id** 去重，避免反复遇到同一失败 URL 重复占用来源容量。没有把 sources_used 偷换成有效来源数，也没有回写历史 85；同类 67 个唯一来源的新运行不会因相同失败 URL 重复发现而计为 85。

## 4. 同批真实 URL 前后对比

选取历史请求中的 9 个 URL（7 个内容页、2 个首页），另加 Wikipedia 与 Developers Blog 两个控制 URL。Developer 控制 URL 返回 404，**不属于原 run 请求**，如实保留，不替换为成功样本。

测试分三层，避免混淆配置收益与正文选择收益：

1. 历史严格配置：85/85 请求被安全拦截，0 snapshot。
2. 用户授权代理配置后、C 代码修改前：同批 11 个 URL，10 个 HTTP 200、1 个 404；旧提取器会接受全部 10 个非空整页文本，包含两个首页噪声。
3. C 修改后：同 URL 再次联网，并用保留的相同 HTML 单独比较提取器。仍是 10 个 HTTP 200、1 个 404；8 个实质正文可用，两个首页明确过滤。

表中“前”是启用代理后旧提取器输出，“后”是最终新提取器输出；字数下降是去除整页噪声，**不是抓取退化，也不声称提取字数增加**。HTML 单位为实际读取 bytes。除最后两个控制 URL 外，全部来自原 run。

| 请求 URL | HTTP / 最终 URL | HTML 前 → 后 | 文本字符前 → 后 | 结果 |
| --- | --- | --- | --- | --- |
| https://deepmind.google/models/model-cards/gemini-3-1-pro | 200；原 URL 加末尾 `/` | 159333 → 159333 | 18076 → 13333 | 可用 |
| https://deepmind.google/models/gemini/pro | 200；原 URL 加末尾 `/` | 194458 → 194458 | 9444 → 4621 | 可用 |
| https://blog.google/innovation-and-ai/technology/ai/google-ai-updates-april-2026 | 200；原 URL 加末尾 `/` | 407968 → 407968 | 12960 → 6648 | 可用 |
| https://blog.google/innovation-and-ai/technology/ai/google-io-2026-all-our-announcements | 200；原 URL 加末尾 `/` | 415350 → 415350 | 35203 → 30608 | 可用 |
| https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-4-argon | 200；原 URL 加末尾 `/` | 406122 → 406122 | 15950 → 9753 | 可用 |
| https://techcrunch.com/2026/09/30/google-releases-gemini-4-argon-called-its-most-powerful-model-yet | 200；原 URL 加末尾 `/` | 231798 → 231798 | 4926 → 3413 | 可用 |
| https://9to5google.com/2026/09/30/gemini-4-argon-announcement | 200；原 URL 加末尾 `/` | 189949 → 189491 | 7056 → 5591 | 可用 |
| https://deepmind.google/ | 200；未变 | 269120 → 269120 | 9001 → 无 artifact | NAVIGATION_PAGE；候选文本 4288 字符 |
| https://blog.google/ | 200；未变 | 359571 → 359571 | 4992 → 无 artifact | NAVIGATION_PAGE；候选文本 1276 字符 |
| https://en.wikipedia.org/wiki/Artificial_intelligence | 200；未变 | 2251186 → 2251264 | 235080 → 228707 | 控制：可用 |
| https://developers.googleblog.com/en/gemini-pro-available/ | 404；未变 | 错误正文未读取 | 不适用 | 控制：HTTP_ERROR |

9to5Google/Wikipedia 两次联网有轻微动态内容差异；对同一份修改前 HTML 重解析也得到同样分类，Wikipedia 同字节输入的新正文为 228709 字符。URLs 仅用于获取测量，本报告不验证其页面事实。

本次样本分类：

| 分母 | 可用正文 | 导航过滤 | HTTP 失败 |
| --- | --- | --- | --- |
| 全部 11 URL | 8/11，72.73% | 2/11，18.18% | 1/11，9.09%，404 |
| 历史选取的 9 URL | 7/9，77.78% | 2/9，22.22% | 0/9 |
| 历史选取的 7 内容页 | 7/7，100% | 0/7 | 0/7 |
| 当前 10 个 HTTP 200 | 8/10，80% | 2/10，20% | 不适用 |

这批真实探针没有遇到 403/429、挑战页、网络失败或重定向异常；相应健壮性由可控单元测试覆盖。不能把 11 个选定样本的成功率推断为全部 85 次请求的成功率。

### 实际入库验证

将本次已保存的 10 个 HTTP 200 响应，通过真实 `SourceAcquisitionService.acquire()` 和 repository 在**新建隔离数据库**持久化：10 条 Source、10 条 snapshot、8 个正文 artifact、2 个质量 gap，`valid_source_count=8`。没有网络请求或模型调用，evidence/claim 均为 0，符合“正文来源不自动等于验证证据”的质量边界。历史数据库只读，未修改。

留存证据：

- [修改前探针结果](D:/deepsearch/reports/taskc-fetch/before/results.json)
- [修改后联网结果](D:/deepsearch/reports/taskc-fetch/after/results.json)
- [最终缓存解析和隔离入库结果](D:/deepsearch/reports/taskc-fetch/final-cached/results.json)
- [隔离入库数据库](D:/deepsearch/reports/taskc-fetch/final-cached/isolated-ingestion.db)

复现命令（在项目根目录、可信代理环境执行；隔离入库需使用新的 stage 名称）：

```powershell
.venv/Scripts/python.exe scripts/diagnose_live_fetch.py --stage fresh-network --allow-proxy-dns
.venv/Scripts/python.exe scripts/diagnose_live_fetch.py --stage fresh-ingestion --cached-stage fresh-network --allow-proxy-dns --verify-ingestion
```

探针专用限制为并发 3、单请求 10 秒/外层 20 秒、HTTP 重试 0；生产有限重试仍按第 2 节。脚本读取固定历史 run、校验请求 blob、保存公开响应并输出计数，不会创建真实模型调查。

## 5. 发现并修复的回归问题

| 问题 | 处理与验证 |
| --- | --- |
| 先单独导入 SourceAcquisitionService 时出现既有 feedback 包循环导入 | 将 bounded_map 导入延后至 prepare；隔离导入与相应测试通过 |
| 用“全球新插入 Source”计数导致 LIVE→REPLAY 预算上下文指纹变化 | 舍弃该实现，改用 run 内 snapshot/gap 来源集合去重；记录回放与重复失败来源预算测试通过 |
| 新正文最低长度导致刻意极短的虚构测试 fixture 被拒绝 | 仅扩展这些测试材料为实质段落；原引用事实和断言保留，真实案例材料未改 |
| 官方 NTSB 页面正文被 form 清理丢弃，随后仅选中长段落又遗漏相邻字段 | 保留普通 form，加入祖先容器与相邻字段评分；新增红→绿测试。NTSB 正文最终 5168 字符，所有已审核 HTML 引文仍存在；既有完整报告/审核/导出 E2E 断言通过 |

没有降低验证或发布门、扩大案例预算来绕过这些回归。

## 6. 本轮改动文件

生产代码（9 个；其中 orchestrator/live_runtime 已含前轮 B 改动，本轮仅叠加所述获取相关逻辑）：

- [fetch.py](D:/deepsearch/src/marketpulse/investigation/adapters/fetch.py)：请求头、重试、冷却、挑战页与诊断。
- [html.py](D:/deepsearch/src/marketpulse/investigation/ingestion/html.py)：正文选择链、质量分类、parser v2。
- [errors.py](D:/deepsearch/src/marketpulse/investigation/recording/errors.py)：内部安全原因/诊断属性。
- [diagnostics.py](D:/deepsearch/src/marketpulse/investigation/recording/diagnostics.py)：安全白名单序列化。
- [recording/adapters.py](D:/deepsearch/src/marketpulse/investigation/recording/adapters.py)：抓取失败记录诊断。
- [source_acquisition.py](D:/deepsearch/src/marketpulse/investigation/services/source_acquisition.py)：获取/质量日志、snapshot provenance、失败 gap、循环导入修复。
- [orchestrator.py](D:/deepsearch/src/marketpulse/investigation/feedback/orchestrator.py)：来源发现预算按 run 去重。
- [live_runtime.py](D:/deepsearch/src/marketpulse/investigation/live_runtime.py)：内部请求语言、支持 HTML parser v2。
- [case_replay.py](D:/deepsearch/src/marketpulse/investigation/case_replay.py)：支持 HTML parser v2，保留 v1。

测试文件（6 个）：

- [test_live_adapters.py](D:/deepsearch/tests/unit/investigation/test_live_adapters.py)
- [test_document_parsers.py](D:/deepsearch/tests/unit/investigation/test_document_parsers.py)
- [test_recording_adapters.py](D:/deepsearch/tests/unit/investigation/test_recording_adapters.py)
- [test_source_acquisition.py](D:/deepsearch/tests/integration/investigation/test_source_acquisition.py)
- [test_phase41_acquisition_uow.py](D:/deepsearch/tests/integration/investigation/test_phase41_acquisition_uow.py)
- [test_phase43_feedback_loop.py](D:/deepsearch/tests/integration/investigation/test_phase43_feedback_loop.py)

工具/本机配置/文档：

- [diagnose_live_fetch.py](D:/deepsearch/scripts/diagnose_live_fetch.py)
- [项目 .env](D:/deepsearch/.env:21)：仅用户授权的代理 DNS 标志；此文件被 Git 忽略。
- [实施计划](D:/deepsearch/docs/superpowers/plans/2026-10-02-live-fetch-resilience.md)
- 本报告。

未增加依赖，未改 pyproject；既有 uv.lock、搜索后端、ProposalGuard、前端及其他工作区变更没有纳入本轮修改清单或回滚。

## 7. 最终验证

按 systematic-debugging 技能先取证，按实施计划做最小修复和红→绿回归，并按 verification-before-completion 技能以新鲜测试结果作为完成依据。

| 验证 | 最终结果 |
| --- | --- |
| 修改前基线 `pytest -m 'not live and not infrastructure' -q` | 384 passed、3 skipped、7 deselected；退出 0 |
| 修改后同命令全量回归 | **405 passed、3 skipped、7 deselected**；163.92 秒，退出 0 |
| 最终专项：6 个改动测试文件 + investigation_server | **68 passed**；40.81 秒，退出 0 |
| `ruff check src tests scripts/diagnose_live_fetch.py --output-format concise` | All checks passed；退出 0 |
| `compileall -q src/marketpulse scripts/diagnose_live_fetch.py` | 退出 0 |
| acquisition 首先导入、fetch/registry/live/server 基本导入 | 通过 |
| 隔离服务与既有案例报告 E2E | 通过；包括已验证声明、引用、审核及导出 |
| OpenAPI 前后 SHA256 | 相同：`8a7ac4bb65c741aa7c54002ec9c12a1f75963da552e04e709547928429bdaf9e` |
| `git diff --check` | 退出 0 |

未改 HTTP 路由、请求/响应字段或状态枚举；内部诊断仅使用已有 metadata/provenance/gap 载体，前端无需改动。任务 C 为后端任务，没有新增前端构建动作。

3 个 skipped 为 Windows 环境下的两项 symlink 与一项 POSIX SIGTERM 检查；7 个 live/infrastructure 用例未运行，避免付费模型和未配置的外部基础设施。全量/专项各有既有 Starlette/AnyIO BlockingPortal 弃用警告，不是测试失败。Git 对既有部分前端/uv.lock 文件提示 LF→CRLF，不影响 diff 检查退出码。

## 8. 限制与交接

- 公网可用性和代理行为会变化；本轮只复测上述 11 URL，没有重新抓取全部 67 URL，也没有进行真实模型端到端调查。
- 403/429/挑战页不保证能获得正文：本实现识别、有限重试/冷却并保留原因，不绕过反爬。JS-only 页面仍不能渲染。
- 正文选择和导航检测是启发式，不宣称适配所有站点。120 字符门可能拒绝有意义的极短页面，但会保留原始材料和明确 gap，不让空材料混过证据门。未新增“主题相关性”模型过滤，避免凭标题误杀合格长文；结论仍受现有分析/验证门约束。
- parser v2 会改变新获取材料的正文和 downstream 输入指纹；旧录制在输入不匹配时仍 fail closed，不自动重写旧 snapshot 或假装兼容所有旧模型录制。
- 代理允许项严格限于本机批准配置；它依赖可信代理，不能在不可信网络中泛化启用。
- 历史 run 与预算未回写；已保存报告证据和隔离数据库便于审计。现有后端未重启。

**交接：用户重启后端、确认启动环境加载项目 .env，然后从原前端发起新的真实联网调查验证。当前代码已通过后端回归与真实公开 URL 获取/离线入库检查；最终新 run 的模型生成和发布结果仍需该端到端验证。**
