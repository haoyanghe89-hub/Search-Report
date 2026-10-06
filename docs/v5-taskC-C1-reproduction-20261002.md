# C1：即时逐 URL 抓取复现

执行时间：2026-10-02，北京时间 11:14–11:16。历史对象：`RUN-LIVE-68180c92a8cb4cb0`。

本轮已实际执行命令、逐个发出请求、逐项落盘；不是仅引用上轮结果。仅更新诊断脚本的顺序执行和增量保存能力，未改生产后端、HTTP 契约、前端、证据门或本机配置。历史 run 数据库只读，没有模型调用、后台服务重启或调查状态写入。

## 命令与记录方式

```powershell
.venv/Scripts/python.exe -u scripts/diagnose_live_fetch.py --stage c1-network-20261002111509 --allow-proxy-dns --sequential
.venv/Scripts/python.exe -u scripts/diagnose_live_fetch.py --stage c1-strict-202610021116 --sequential
```

从历史 run 的请求记录中匹配出 9 个 URL（7 内容页、2 首页），另加 2 个明确标记为 control 的 URL。每完成一个 URL 就保存 `NN.json`，更新 `results.json`，立即输出命令结果；成功获取的原始响应另存 `NN.html`。记录包含请求 URL、最终 URL、状态、HTML bytes、正文字符数、候选文本字符数、分类和完成时间。

探针使用生产 HttpxFetchAdapter 和 DocumentParserRegistry，不模拟网络响应：单请求超时 10 秒、外层 20 秒、HTTP 重试 0，顺序执行。允许代理 DNS 的联网批次起止为 11:15:10–11:15:26，约 16 秒，命令退出 0。

最初受限执行环境下的 11 次请求均立即返回传输失败、没有 HTTP 响应；结果保留在 [第一批记录](D:/deepsearch/reports/taskc-fetch/c1-now-20261002111447/results.json)。申请允许联网的执行环境后，同批 URL 得到下面的实际响应。第一批不能计为公网正文提取失败，也不能编造 HTTP 状态。

## 逐 URL 真实结果

单位：HTML 为已读取的响应 bytes；正文为清理后的字符数。前 9 项来自历史 run，后 2 项是控制 URL。

| # | 请求 URL | HTTP | 最终 URL | HTML bytes | 提取字符 / 可用正文字符 | 分类 |
| --- | --- | --- | --- | --- | --- | --- |
| 00 | https://deepmind.google/models/model-cards/gemini-3-1-pro | 200 | https://deepmind.google/models/model-cards/gemini-3-1-pro/ | 159333 | 13333 / 13333 | ACCEPTED |
| 01 | https://deepmind.google/models/gemini/pro | 200 | https://deepmind.google/models/gemini/pro/ | 194458 | 4621 / 4621 | ACCEPTED |
| 02 | https://blog.google/innovation-and-ai/technology/ai/google-ai-updates-april-2026 | 200 | https://blog.google/innovation-and-ai/technology/ai/google-ai-updates-april-2026/ | 407968 | 6648 / 6648 | ACCEPTED |
| 03 | https://blog.google/innovation-and-ai/technology/ai/google-io-2026-all-our-announcements | 200 | https://blog.google/innovation-and-ai/technology/ai/google-io-2026-all-our-announcements/ | 415350 | 30608 / 30608 | ACCEPTED |
| 04 | https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-4-argon | 200 | https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-4-argon/ | 406122 | 9753 / 9753 | ACCEPTED |
| 05 | https://techcrunch.com/2026/09/30/google-releases-gemini-4-argon-called-its-most-powerful-model-yet | 200 | https://techcrunch.com/2026/09/30/google-releases-gemini-4-argon-called-its-most-powerful-model-yet/ | 231798 | 3413 / 3413 | ACCEPTED |
| 06 | https://9to5google.com/2026/09/30/gemini-4-argon-announcement | 200 | https://9to5google.com/2026/09/30/gemini-4-argon-announcement/ | 189491 | 5591 / 5591 | ACCEPTED |
| 07 | https://deepmind.google/ | 200 | https://deepmind.google/ | 269120 | 4288 / 0 | NAVIGATION_PAGE |
| 08 | https://blog.google/ | 200 | https://blog.google/ | 359571 | 1276 / 0 | NAVIGATION_PAGE |
| 09 | https://en.wikipedia.org/wiki/Artificial_intelligence | 200 | https://en.wikipedia.org/wiki/Artificial_intelligence | 2251264 | 228707 / 228707 | ACCEPTED（control） |
| 10 | https://developers.googleblog.com/en/gemini-pro-available/ | 404 | https://developers.googleblog.com/en/gemini-pro-available/ | 未读取错误正文 | 不适用 | HTTP_ERROR（control） |

07/08 不是“提取为空”：有 4288/1276 字符候选文本，但 URL 和页面结构属于导航首页，因此不生成可用正文 artifact。10 是真实 HTTP 404，诊断中的 `html_bytes=0` 仅表示未读取错误正文，不代表服务器实际错误页为 0 bytes。HTTP 状态与最终 URL 来自实际 response hook。

## 原因分类与占比

允许可信代理 DNS、允许联网环境中的 11 URL：

| 类别 | 数量 / 分母 | 占比 |
| --- | --- | --- |
| 可用实质正文 | 8/11 | 72.73% |
| 导航首页过滤 | 2/11 | 18.18% |
| HTTP 404 | 1/11 | 9.09% |
| 网络不可达/超时 | 0/11 | 0% |
| 403/429/挑战页 | 0/11 | 0% |
| 重定向异常 | 0/11 | 0% |
| 空/过短正文或 JS 空壳 | 0/11 | 0% |

HTTP 成功为 10/11（90.91%）。历史选取的 9 URL 均返回 HTTP 200，其中 7 内容页全部取得可用正文（3413–30608 字符），2 首页过滤；内容页成功率 7/7。没有在这批样本中发现合格长文被质量门拒绝；不能将这些选取样本外推为整个公网或全部历史请求的成功率。

严格 DNS 对照：同一批 11 URL 全部 `NON_PUBLIC_DNS`（11/11，100%），HTTP 状态和最终 URL 均为 null，尚未发出 HTTP 请求。DNS 答案均为 `198.18.0.0/15` 内的本机代理 fake-IP；这组命令仅不传 `--allow-proxy-dns`，**没有把用户批准的 .env 配置改回 false**。

历史记录本身是 85/85 SECURITY_BLOCKED，未保存具体安全子原因。当前严格/允许代理的配对复现确认了 DNS 配置不匹配能产生同阶段阻断，但不将当前 NON_PUBLIC_DNS 子原因冒充成历史日志里已有的字段。

## 已读代码与质量边界

- [fetch.py](D:/deepsearch/src/marketpulse/investigation/adapters/fetch.py)：httpx 流式获取，手工跟随重定向，每跳验证目标域名，默认最多 5 跳，MIME/字节上限保留；403、429、挑战页有明确分类。代理允许只覆盖域名经可信代理解析到 fake-IP，直接 fake-IP URL、localhost 和私网仍阻止。
- [html.py](D:/deepsearch/src/marketpulse/investigation/ingestion/html.py)：BeautifulSoup；语义区域 → 段落密度祖先容器 → 清理后 body；当前最低 120 字符，导航/搜索/挑战/JS 空壳与空短正文分别记录原因；外部内容仍按 UNTRUSTED 处理。
- 可用正文不等于已经验证的 evidence/claim；本轮 C1 只做获取和解析诊断，不入库历史来源，也不生成事实结论。入库门与上轮隔离持久化结果见 [任务 C 完整报告](D:/deepsearch/docs/v5-taskC-final-report.md)。

## 落盘与校验

- [允许代理的最新联网汇总](D:/deepsearch/reports/taskc-fetch/c1-network-20261002111509/results.json)：11 逐项 JSON、10 原始 HTML。
- [严格 DNS 对照汇总](D:/deepsearch/reports/taskc-fetch/c1-strict-202610021116/results.json)：11 逐项失败 JSON，无 HTTP 正文。
- 逐项文件核对：11 个 JSON 的 URL 与汇总顺序一致；10 个 HTML 文件的实际长度均与所录 bytes 相同。
- [诊断脚本](D:/deepsearch/scripts/diagnose_live_fetch.py) 本轮新增 `--sequential`、每项 JSON 与增量汇总、开始/完成时间；没有生产功能修改。
- 本轮脚本 Ruff、compileall、git diff --check 检查通过。未将上轮 405 passed 冒充本轮重跑：本轮只修改探针与文档，生产代码未变；上轮后端全量结果另见原报告。

结论：C1 即时逐项复现已执行并落盘。当前可信代理环境可以取得本批全部 7 个历史内容页的正文；历史直接失败路径仍对应 HTTP 前安全校验，当前未复现“内容页抓到 HTML 却全部空提取”的问题。
