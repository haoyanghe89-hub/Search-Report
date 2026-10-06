# 任务 E：来源级抓取错误容错

日期：2026-10-02。生产改动限定为两个文件；不改 HTTP 契约、前端、质量/发布门或任务 D 的材料/预算配置。不重启后端、不恢复历史 run、不发起真实付费调查。

## E1：实际根因和冒泡路径

只读检查 `data/blackboard.db`，确认 `RUN-LIVE-42f0c4b9624c4b9c`：

- COLLECT / FAILED，运行原因 `RateLimitedError: inspect configuration and retry`。
- 失败步骤 `research:T-09-pricing-and-cost-effectiveness-audit:round-2`，错误码 RATE_LIMITED，retryable=false。
- 抓取记录 `CALL-c546fb12e3344c538303fe4549d4beb7`：www.morphllm.com / HTTP_RATE_LIMITED / HTTP 429。
- 同一失败步骤中存在多个 SUCCESS 抓取记录；外部工具完成不等于研究步骤的业务结果已经成功提交。

根因是异常类型漏项：`RateLimitedError` 与 `ProviderCallError` 都直接继承 `ExternalCallError`，并非前者继承后者。来源级 `prepare_item` 虽然在并行模式开启容错，但只捕获 ProviderCallError、SecurityBlockedError、TimeoutError，漏掉了 RateLimitedError。顺序模式则没有开启容错开关。

真实代码路径：

1. `HttpxFetchAdapter._fetch` 有限重试后抛 RateLimitedError；`fetch` 记录 HTTP_RATE_LIMITED，并缓存该 URL 的拒绝结果。
2. `RecordingFetchAdapter.fetch` 保存 RATE_LIMITED 工具调用后重新抛出；`BoundExternalCalls.fetch` 的尝试额度已计数，错误返回时不产生有效 FetchResult。
3. `SourceAcquisitionService._fetch_parse → prepare_item` 未匹配限流异常；`bounded_map` 取消尚未结束的同级任务，异常穿过 `acquisition_batch` 和 `_research`。
4. `InvestigationHarness.run_step` 将研究步骤记为 FAILED / RATE_LIMITED / retryable=false；准备好的来源/快照/缺口输出未进入正常步骤完成事务。
5. `LiveInvestigationService._execute` 的兜底异常处理将 run 判为 FAILED。恢复检查发现当前步骤不可重试且 RATE_LIMITED 不在允许的未知模型/预算错误名单内，因此拒绝恢复；watchdog 表现为 RUN_NOT_RESUMABLE。

没有在 LIVE 的顶层捕获所有异常并假装成功；修复位置是单个候选来源的边界。

## E2：改动与理由

### 1. 来源边界补齐 RateLimitedError

[source_acquisition.py](D:/deepsearch/src/marketpulse/investigation/services/source_acquisition.py:264) 的既有 opt-in 容错中加入 RateLimitedError。429、403、抓取 ProviderCallError、安全拦截和单来源 TimeoutError 均可记录后跳过，候选列表中的其他来源继续处理。

失败结果保持 discovered=true、fetched=false、parsed=false、evidence_eligible=false、valid_for_statistics=false；不生成伪造快照、正文 artifact 或证据。来源及 UNREADABLE_SOURCE 缺口进入既有研究步骤完成事务，成功来源也一并提交，不因单个限流被丢弃。

不捕获 generic Exception / ExternalCallError；取消、预算不足、回放 cache miss、输入/完整性错误和模型未知结果保护照常生效。严格 opt-out 模式仍抛异常；旧 `acquire()` 入口保持既有严格语义，本轮修复针对 LIVE 使用的 `prepare()` 路径。

### 2. 安全、持久化的失败原因

每个失败来源保留稳定 reason_code，缺口的 suggested_actions 记录域名、HTTP 状态和网络/稍后重试/替代原始材料建议；新增安全 `acquisition_result` 日志，含 run_id、source_id、domain、http_status、filter_reason、fetched=false、evidence_eligible=false。

复用已有 allowlist 诊断，不记录异常正文、URL 查询参数、凭据、敏感头或网页内容。超时/网络错误没有 HTTP 响应时，状态为 unknown/null，不伪造 429。已有工具调用录制继续保存实际尝试与 HTTP 诊断。

### 3. 顺序采集与并行采集行为一致

[orchestrator.py](D:/deepsearch/src/marketpulse/investigation/feedback/orchestrator.py:618) 为顺序路径启用已有 `tolerate_fetch_errors=True`，与并行路径一致。不增加新的批处理框架或重试循环。

继续使用原 HttpxFetchAdapter：默认最多 2 次重试，退避 0.25s、0.5s；403/429/挑战页按相同 URL 冷却 120 秒。冷却期间不再次进行 HTTP 请求；每次逻辑 fetch 尝试仍按原机制计入预算，来源发现按既有机制每 run 去重计数，不混入成功/有效来源数量。

### 4. 全部不可用时受控收尾

[orchestrator.py](D:/deepsearch/src/marketpulse/investigation/feedback/orchestrator.py:1402) 保留原有限轮次/预算/政策驱动的 BLOCKED 路径；当没有 evidence-eligible 快照，且存在没有快照的来源级抓取缺口时，补充说明：

> 未获得可读取的合格来源；部分来源不可访问或被限流。请检查网络、稍后重试或提供可访问的原始材料。

保留原预算错误维度和恢复标记，不把正常可读取但正文太短的解析拒绝误报为 HTTP 限流。单个坏来源不立即 BLOCKED；有合格材料就继续分析、验证与报告，声明能否通过仍由完整质量门决定。

任务 D 的 8 来源 / 16 摘录 / 24,000 字符上限、VERIFY 25% 和 REPORT 2% token 预留、调用前预算准入、语义复用后重跑完整确定性验证均未修改。

## E3：红→绿与最终验证

新增 [test_source_fetch_tolerance.py](D:/deepsearch/tests/integration/investigation/test_source_fetch_tolerance.py)，19 项：

- 10 项：单个 RateLimitedError、ProviderCallError(429/403)、TimeoutError、安全拦截 + 成功来源；并发 1/3。成功材料保留，失败来源有持久化缺口、域名/状态、无伪造快照/证据，日志无 private marker。
- 5 项：取消、预算、回放缺失、本地错误、严格模式仍传播，不被当作普通来源失败吞掉。
- 4 项：真实 LIVE 服务/API、仅替换外部 I/O；混合 429/超时/成功及全部 429，顺序/并行配置。研究步骤 COMPLETED，无 FAILED 步骤；混合材料实际进入 verifier；全 429 为 REPORT/BLOCKED，原因可操作，恢复检查 can_resume=true、没有未知模型调用，生成状态报告。

修复前：**14 failed、5 passed**，包括真实 LIVE API 的 RateLimitedError → FAILED 复现。

修复后：**19 passed**；加入恢复检查断言后再跑 **19 passed，17.87 秒，退出 0**。

扩大专项（新用例、live adapters、采集 UoW）：**40 passed，18.92 秒，退出 0**。包含现有 403/429 冷却避免重复 HTTP 请求的回归。

全量非外部回归：**440 passed、3 skipped、7 deselected、1 warning，174.09 秒，退出 0**。

```powershell
.venv/Scripts/python.exe -m pytest -m 'not live and not infrastructure' --basetemp=reports/taske/pytest-full -p no:cacheprovider -q --tb=short
.venv/Scripts/python.exe -m ruff check src tests scripts
.venv/Scripts/python.exe -m ruff format --check src/marketpulse/investigation/services/source_acquisition.py src/marketpulse/investigation/feedback/orchestrator.py tests/integration/investigation/test_source_fetch_tolerance.py
.venv/Scripts/python.exe -m compileall -q src/marketpulse
git diff --check
```

独立 basetemp 与禁用 cacheprovider，未与 `.pytest-work` 竞争。3 项 skipped 为 Windows 下两项 symlink 与一项 POSIX signal 检查；7 项 live/infrastructure 测试需要真实网络/模型或独立 PostgreSQL/Redis，本轮未运行，不宣称通过这些外部测试。既有 Starlette/AnyIO 弃用警告保留。

已完成：Ruff All checks passed；compileall、acquisition→fetch→live→server 导入退出 0；Investigation Console OpenAPI SHA256 与 B/C/D 基线一致：`8a7ac4bb65c741aa7c54002ec9c12a1f75963da552e04e709547928429bdaf9e`；git diff --check 退出 0。已有 LF→CRLF 提示不是 whitespace error。

## 本轮文件清单

- 生产：`src/marketpulse/investigation/services/source_acquisition.py`、`src/marketpulse/investigation/feedback/orchestrator.py`。
- 新增测试：`tests/integration/investigation/test_source_fetch_tolerance.py`。
- 新增文档：`docs/superpowers/plans/2026-10-02-source-fetch-tolerance.md`、本报告。
- 诊断证据：`reports/taske/before.json`；独立测试产物位于 `reports/taske/pytest-*`。

没有新增依赖或改配置；没有改 fetch 适配器、错误继承体系、LIVE 顶层异常处理、HTTP API/DTO/枚举、前端、质量/发布门。现有工作区 A/B/C/D/前端改动保留，git diff 总量不能当成本轮 E 的变更量。

## 限制与交接

- 跳过单个抓取失败不保证证据足够或报告可发布；不绕过 403/反爬挑战、JS 渲染或质量门。
- 模型服务 HTTP 402、未知/可能收费的模型调用、整体运行超时、预算耗尽及本地程序错误不属于可忽略的单来源错误，继续由原安全机制处理。
- 既有冷却是单个适配器实例的内存状态，进程重启会清空；历史录制失败不被自动改写成成功。
- 历史 `RUN-LIVE-42f0c4b9624c4b9c` 的非重试失败状态未回写；本轮不会自动让其旧步骤恢复。按用户安排重启后端后，从前端创建同话题新 run 验收。
- 本轮 E2E 使用生产服务和 API，但网络/模型为测试替身，没有重新访问 morphllm 或进行付费真实调查。公网限流与真实新 run 的端到端结果仍待用户验证。
