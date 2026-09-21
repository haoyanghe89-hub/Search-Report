# MarketPulse Agent 最终验收报告

- 验收日期：2026-09-17
- 项目版本：0.1.0
- 验收结论：**通过（存在已记录的非阻断限制）**
- 验收环境：Windows / Python 3.11+ / uv / Node.js + npm

## 1. 验收范围

本次验收覆盖：Python 类型检查与代码规范、单元/集成/真实联网测试、Python 分发包构建、前端测试与生产构建、交付物完整性、README 启动说明，以及阶段 5 生成的示例报告和页面截图。

真实联网测试使用用户级 `DEEPSEEK_API_KEY`，运行时注入进程环境；命令和日志均未打印密钥。在当前可信本地代理把公网域名解析到 `198.18.0.0/15` 的环境中，显式设置了 `MARKETPULSE_ALLOW_PROXY_DNS=true`。

## 2. 全量验证结果

| 验证项 | 命令 | 结果 | 证据摘要 |
|---|---|---|---|
| mypy 类型检查 | `uv run mypy src` | 通过 | `Success: no issues found in 27 source files` |
| Ruff lint | `uv run ruff check src tests` | 通过 | `All checks passed!` |
| 全量 pytest | `RUN_LIVE_TESTS=1` 后执行 `uv run pytest -q` | 通过 | `32 passed in 190.88s`；包含 unit、integration、真实搜索和 DeepSeek live 用例 |
| Python 分发包 | `uv build --clear` | 通过 | 生成 wheel 与 sdist |
| wheel 内容 | `python -m zipfile -l ...whl` | 通过 | 包含 `cli.py`、`workflow.py`、`web_api.py`、报告模板和 METADATA |
| 前端测试 | `npm test -- --run` | 通过 | 1 个测试文件、2 项测试通过 |
| 前端 lint | `npm run lint` | 通过，有警告 | 退出码 0；2 条 shadcn Fast Refresh 非阻断警告 |
| 前端生产构建 | `npm run build` | 通过 | TypeScript 编译和 Vite 构建成功，2029 个模块完成转换 |

构建产物：

- `dist/marketpulse_agent-0.1.0-py3-none-any.whl`
- `dist/marketpulse_agent-0.1.0.tar.gz`
- `web/dist/`

## 3. 交付物核对

| 交付物 | 状态 | 核对结果 |
|---|---|---|
| `docs/01-brainstorming.md` | 已交付 | 包含需求澄清、方案比较、MVP 范围与验收标准 |
| `docs/02-implementation-plan.md` | 已交付 | 包含模块划分、任务步骤、依赖、验收条件和风险预案 |
| `docs/03-acceptance.md` | 已交付 | 本验收报告 |
| `src/marketpulse/` | 已交付 | Agent、搜索/抓取适配器、证据处理、分析、报告、CLI、FastAPI API 均存在 |
| `tests/` | 已交付 | unit、integration、live 分层测试均存在 |
| `web/` | 已交付 | Vite + React + TypeScript + shadcn/ui 前端及测试存在 |
| `reports/example-report.md` | 已交付 | 20,084 字节；固定 10 个二级章节；记录 20 个成功来源 |
| `reports/example-report-ui.png` | 已交付 | 662,746 字节；阶段 5 的真实页面展示截图 |
| `README.md` | 已交付 | 安装、配置、CLI、API、前端和测试说明完整 |
| `.env.example` | 已交付 | 包含 DeepSeek 必填项和全部主要可选配置，不含真实密钥 |

## 4. README 启动说明审计

逐项核对结果：

- DeepSeek：说明 `DEEPSEEK_API_KEY` 必填、`base_url=https://api.deepseek.com`、模型 `deepseek-chat`，并明确项目不会自动读取 `.env`。
- 安装：提供 `uv sync --extra dev`；Web 运行提供 `uv sync --extra dev --extra web`。
- CLI：提供基本调用、竞品数量、输出文件和日志文件示例；全局选项已修正为放在关键词之前，并与 `uv run marketpulse --help` 一致。
- 后端：提供 `uv run marketpulse-api`，默认监听本地 8000 端口。
- 前端：提供 `cd web`、`npm install`、`npm run dev` 及 `http://localhost:5173` 访问地址，并说明 `/api` 代理关系。
- 测试：区分离线测试与需显式启用、会产生 DeepSeek 费用的完整 `tests/live` 冒烟测试。
- 调试：说明 JSONL 日志、重试行为、质量降级和可信代理 DNS 开关。

## 5. 本轮及端到端阶段已修复问题

1. **CLI 文档参数顺序**：Typer 全局选项必须位于关键词之前；已修正 README 示例并用 CLI help 核对。
2. **代理 DNS 与 SSRF 防护冲突**：可信代理把公网 DNS 映射到 `198.18.0.0/15`；新增默认关闭的显式开关，仅放行该基准测试网段，localhost 和其他私网仍拒绝。
3. **Bing/Yahoo 跳转链接**：搜索结果包装 URL 会导致抓取错误页面；已解码并规范化实际目标地址。
4. **低相关搜索结果**：Bing HTML 在部分请求中返回不相关结果；已增加查询相关性过滤。
5. **公开搜索限流**：DuckDuckGo/Bing/Yahoo 可能挑战、限流或改变 HTML；新增无 API Key 的 `ddgs` 元搜索最终回退。
6. **搜索超时累积**：原实现对每个提供方最多重试 3 次、单次 15 秒，多个查询可在到达有效回退前耗尽 300 秒。回归测试先复现 DuckDuckGo 被调用 3 次；现将搜索请求上限设为 5 秒，并在连接/读取超时后立即切换下一提供方，HTTP 429/5xx 仍保留重试。修复后全量 live 套件通过。
7. **测试环境污染**：默认配置测试会继承验收进程的代理开关；已显式清除该变量，保证测试隔离。

## 6. 已知限制

- 公开搜索 HTML 与无密钥元搜索没有服务等级保证，可能受限流、地区、验证码或页面结构变化影响；当前通过多提供方、超时、重试和降级缓解。
- live 测试依赖外部网络和 DeepSeek 服务，会产生少量 API 费用，结果耗时和来源数量可能波动，因此默认必须用 `RUN_LIVE_TESTS=1` 显式启用。
- `MARKETPULSE_ALLOW_PROXY_DNS=true` 只适合确认可信的本地透明代理环境；普通环境应保持默认关闭。
- 当前 FastAPI 请求同步等待完整 Agent 工作流，未实现后台任务队列、断点续跑、取消任务或多租户隔离。
- MVP 不包含账号、鉴权、历史报告数据库、配额管理和生产部署配置。
- 示例报告对市场规模与定价的官方一手来源覆盖有限，因此结论为 `Conditional Go` 且置信度较低；重要商业决策前仍需人工复核关键来源。
- shadcn 的 `badge.tsx` 与 `button.tsx` 触发 2 条 `react(only-export-components)` Fast Refresh 警告；不影响 lint 退出码、测试或生产构建。

## 7. 后续建议

1. 将 Web 运行改为异步任务：创建任务后轮询或通过 SSE 推送阶段进度，并支持取消与恢复。
2. 为搜索提供方增加成功率、延迟、回退次数指标，按运行环境动态调整顺序和熔断策略。
3. 增加来源域名白名单/权威度评分与报价日期提取，提高官方定价和市场规模证据的可靠性。
4. 在 CI 中默认执行离线测试、mypy、Ruff、wheel 和前端构建；将 live 套件设置为人工触发或定时任务。
5. 生产化前增加认证、限流、密钥托管、任务持久化、审计日志和部署健康检查。

## 8. 最终判定

MVP 的核心链路——关键词输入、公开网络搜索、页面采集、DeepSeek 分析、中文 Markdown 报告、FastAPI 接口及 React 可视化——已有真实运行证据。所有阻断性验证项通过，构建产物和要求的交付物齐全；上述限制均为 MVP 边界或非阻断项，因此本次交付判定为 **通过**。
