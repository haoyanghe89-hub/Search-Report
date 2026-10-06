# 任务 B：LIVE 后端容错与搜索稳定性最终报告

日期：2026-10-01。范围：后端实现与测试；本轮未修改前端、HTTP 路由或请求/响应字段，未发起付费模型调用或真实调查，未重启现有服务。

## B1. 定位结论及证据边界

### 历史运行不能在当前环境复核

`RUN-LIVE-9bf9ed6116524faf` 在 `data/blackboard.db`、`frontend/data/blackboard.db` 中均不存在；当前 `localhost:8000` API 返回 404 / `RUN_NOT_FOUND`。扫描当前工作区也未找到对应异常堆栈。因此不能把某一抛出点宣布为该运行已经确认的直接根因。

用户提供的约 140 次搜索、269 次抓取、56 次模型调用以及 0 声明 / 0 证据，说明调用投入并未转化为已提交的事实实体，但不能单凭计数区分：搜索无有效结果、分析提案不合规、引用绑定失败、重复后续任务或其他中断。搜索不稳定属于已实测的风险，尚不能证明它与这一次 ProposalGuardError 的因果链。

### 代码中真实的守卫与失败链

- `feedback/guards.py` 定义 `ProposalGuardError(ValueError)`，错误码为 `INVALID_AGENT_PROPOSAL`。QueryGuard 检查空查询、长度、预算、规范化重复及明显偏题；EvidenceGuard 保留引文 SHA256、定位器哈希及原文完整性校验；ClaimGuard 保留原子声明规范化与去重。
- orchestrator 还会对无任务、无可执行查询、重复历史任务、未知问题/缺口引用等拒绝执行。该异常本身**没有最低来源数或最低声明数阈值**。验证策略中某些配置要求至少两个独立来源家族/支持来源，这是另一层质量要求，本轮未调整。
- 原 StructuredAgent 最多一次结构修复、两次模型调用，修复间没有退避；重复后续任务的实体化校验在修复循环外，无法获得修复机会。
- 原流程中这些未捕获异常进入 Harness：步骤失败、run 标记 FAILED 并保存错误码，再由 LIVE 服务生成状态报告；普通 ProposalGuardError 不属于 TimeoutError/ConnectionError 重试路径。最终原因过于笼统，常显示“检查配置后重试”。

本轮用确定性回归复现了重复后续任务、无可执行查询、分析输出反复无法解析，以及初始规划不合规；修复的是这些已确认的代码路径，不是对缺失历史堆栈的猜测。

## B2. Proposal 容错与受控结束

1. **有限修复**：结构、引用或可由输入上下文判定的重复错误最多两次修复（三次总调用），间隔 0.25s / 0.5s；提示继续明确要求完整可解析 JSON、所需字段及安全的校验问题，不把原始响应/凭据写入提示或报告。ProviderCallError、取消请求、预算耗尽及调用结果不明不会被当作格式问题盲目重试。
2. **先校验后实体化**：根据真实 `prior_task_summaries` 检查重复任务；根据 `executed_queries` 检查全重复查询，纳入原结构修复循环。没有自动捏造替代任务、来源或证据。原实体化守卫仍保留作为第二道检查。
3. **受控 BLOCKED**：后续规划、研究查询、分析提案在已知提案错误耗尽后，由应用生成空的既有类型结果、阻断缺口和现有 `Route.BLOCKED`。已采集来源、artifact 与步骤记录保留，可生成 `INVESTIGATION_STATUS` 报告；不把“证据不足”伪装成调查成功。
4. **仍需 FAILED 的情况**：初始规划/验证阶段无法安全形成结果时保留现有 FAILED 语义，但原因明确标注“未形成可确认结论”，建议补充可访问的原始材料或检查/更换模型。未知异常仍按既有失败路径处理，没有整体吞掉异常。
5. **预算不变**：模型修复仍逐次登记和扣除模型调用预算；预算不足沿用既有 BUDGET_EXHAUSTED 路径。嵌套的 claim decomposition 保持最多一次修复，以免小预算被嵌套修复耗尽。本轮验证时发现并修复了这一回归，没有提高预算或放宽原子声明门槛。

证据完整性、定位器/哈希、原子声明、验证策略及发布质量门均未放宽。报告明确显示阻断及缺口，不生成未经验证的结论。

## B3. 搜索后端稳定性

### 当前环境实测

安装的 DDGS 版本为 9.16.0，其 text 引擎包含 Yahoo、Brave、DuckDuckGo、Wikipedia 等，**不包含 Bing**。Bing HTML 与 DDGS Bing 是两条不同路径。

公开网络只读探测中：Bing HTML 返回 200 但没有可用解析结果；DuckDuckGo 超时；Yahoo HTML 返回 500；多个 DDGS 引擎报错；DDGS Yahoo 能返回结果。因此默认优先级改为：

`ddgs:yahoo → bing（HTML）→ ddgs:brave → duckduckgo（HTML）→ ddgs:wikipedia`

Yahoo HTML 降为可显式选择的后端；无效 DDGS Bing 从默认列表移除。逐个指定已安装引擎，防止混合 backend 参数被 DDGS 内部重排，或无效引擎意外回退到 auto。成功后端在下一查询中优先，失败时仍尝试其他后端。

修改后的真实公开查询探测：英文 East Palestine / EPA 查询返回 4 条经相关性过滤后的可用结果；中文同类查询返回 2 条。两次查询各只预留一次搜索预算，没有调用模型或创建调查。

### 有界重试与熔断

- 单个逻辑查询最多 25s，且不超过运行剩余时长；HTML 请求最多 5s，DDGS 内部网络 timeout 5s、外层等待最多 7s。
- 每个后端最多一次重试（两次尝试，仍受配置 max_retries 限制），退避 0.25s；覆盖超时、连接错误、429、所有 5xx。普通 4xx、挑战页/重定向没有反复重试。
- 后端失败或无可用结果短期熔断 60s，429 为 120s；后续查询跳过，期满可恢复。全部熔断时快速返回可解释的搜索不可用错误。
- 每个逻辑查询只扣一个搜索预算，内部切换不重复扣款；结果相关性、URL 安全、规范化与去重规则保留。
- 超时不能强杀 Python 工作线程；保留未结束 DDGS task 的引用与异常消费回调，按现有 max_search_concurrency 限制未结束线程调用数量，避免重复查询无限生成遗留线程。取消请求不触发重试/后端切换。
- 不新增搜索密钥或新依赖；网络探测结论仅代表本次环境，不承诺公共后端永久可用。

## 改动文件清单

生产代码（6）：

- `src/marketpulse/adapters/search.py`：独立引擎选择、优先级、期限、退避、熔断、线程调用上限。
- `src/marketpulse/investigation/agents/contracts.py`：仅增加上下文校验函数，契约模型字段不变。
- `src/marketpulse/investigation/agents/model_agents.py`：有限结构修复、退避及嵌套分解预算边界。
- `src/marketpulse/investigation/feedback/orchestrator.py`：已知提案错误的受控阻断与可操作缺口。
- `src/marketpulse/investigation/feedback/research_team.py`：全研究员无可用提案归入已知提案错误。
- `src/marketpulse/investigation/live_runtime.py`：初始规划/验证失败的安全、可解释原因。

测试（4）：

- `tests/unit/test_search.py`。
- `tests/unit/investigation/test_live_model_output.py`。
- `tests/integration/investigation/test_phase43_feedback_loop.py`。
- `tests/integration/investigation/test_live_runtime.py`。

文档（2）：本报告及 `docs/superpowers/plans/2026-10-01-live-backend-resilience.md`。

未修改 HTTP/API 路由、请求/响应字段、状态枚举、前端、证据守卫、验证策略或发布门。工作区此前的前端和 uv.lock 改动原样保留，不计入本轮文件清单。

## B4. 验证结果

| 检查 | 结果 |
| --- | --- |
| 修改前默认后端回归 | 367 passed，3 skipped，7 deselected；退出码 0 |
| 最终针对性四文件测试 | 61 passed；退出码 0 |
| 最终默认后端回归 | **384 passed，3 skipped，7 deselected**；160.89s，退出码 0 |
| 修改的 10 个 Python 文件 Ruff 检查 | All checks passed；退出码 0 |
| `python -m compileall -q src/marketpulse` | 退出码 0 |
| 搜索、orchestrator、LIVE runtime、server 基本导入 | OK；退出码 0 |
| 服务/HTTP 状态报告检查 | 隔离数据库的 LIVE runtime 集成测试通过，包含真实应用 TestClient 生命周期及报告读取 |
| OpenAPI 前后比较 | SHA256 完全一致：`8a7ac4bb65c741aa7c54002ec9c12a1f75963da552e04e709547928429bdaf9e` |
| `git diff --check` | 通过；退出码 0 |

最终后端命令：`.venv/Scripts/python.exe -m pytest -m 'not live and not infrastructure' -q`。

新增 17 个测试用例覆盖：坏输出两次后修复、修复次数上限、不可恢复 provider 错误不重试、重复任务/查询修复、三类提案耗尽的阻断与资料保留、初始错误的安全状态报告、500/429/timeout 后端切换与熔断恢复、缺失引擎不回退 auto、单引擎相关性、遗留线程上限和取消请求。关键路径先运行失败测试，再实施修复并转绿。

三个跳过项是 Windows 用户无 symlink 权限（两项）及 POSIX SIGTERM 专用测试（一项）。七项 live/infrastructure 用例未运行；未配置 PostgreSQL/Redis 或发起付费在线模型调查。一个已有 Starlette / AnyIO BlockingPortal 弃用警告不影响通过结果。pytest/pytest-asyncio/Ruff 使用项目已声明的开发依赖安装，无 manifest 或 lockfile 新改动。

## 限制与交接

- 原失败运行的数据库/堆栈不在当前环境，历史根因仍需原日志才能进一步确认；不能保证这批修复覆盖未知抛出点。
- 公共搜索受网络、限流、反爬及库版本影响；熔断是每个适配器实例的短期状态，不是跨进程分布式熔断。Python 超时线程只能限额与等待自然结束，不能安全强杀。
- 未进行真实模型端到端调查；已验证确定性故障路径、真实公开搜索及完整默认后端回归。没有借验收发起可能收费的新 run。
- 修改已落盘；**本轮未重启常驻后端。请在没有需要保留的运行任务时重启后端加载新代码，再从前端发起新的 LIVE 调查。** 本轮不会自动恢复或改写原失败运行。

结论：已复现的提案与搜索容错缺陷已修复，质量门与外部 API 保持不变；下一步等待用户加载新代码后发起真实联网调查验证。
