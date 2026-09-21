# MarketPulse Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个单次运行的 CLI Agent，接收产品方向或关键词，在受控预算内检索全球英文公开网页，并生成带可追溯证据的中文 Markdown 市场可行性报告。

**Architecture:** 采用 OpenAI Agents SDK 与显式阶段编排相结合的单 Agent 工作流。LLM 负责研究规划、搜索结果结构化、证据抽取和市场分析；Python 工作流负责预算、抓取、数据契约、错误降级、报告渲染与质量门禁，使每个阶段可隔离测试和回放。

**Tech Stack:** Python 3.11–3.13、`openai-agents==0.22.2`、OpenAI Responses API / `WebSearchTool`、Pydantic 2、Typer、HTTPX、Beautiful Soup 4、Jinja2、pytest、pytest-asyncio、respx、Ruff、mypy。

**Spec:** `docs/01-brainstorming.md`

## Global Constraints

- 交付形态固定为单次运行 CLI；不创建 Web UI、HTTP 服务、数据库或云部署。
- 研究范围固定为全球市场，主要检索英文公开网页，报告输出语言固定为中文。
- 输入主题长度为 2–200 个 Unicode 字符；竞品研究候选上限默认 5，允许范围 3–8；最终核心竞品表选择其中相关性最高的 3–5 个。
- 正常网络条件下单次运行目标不超过 300 秒；硬性总超时为 300 秒。
- 默认最多生成 8 个首轮搜索查询和 4 个补充查询，搜索查询总数最多 12 个。
- 默认最多抓取 24 个页面；单页超时 15 秒；单页网络重试最多 2 次；并发抓取上限 5。
- 关键事实只能来自成功读取的页面正文；搜索摘要仅用于发现 URL，不得进入最终证据集。
- 最终报告至少含 8 个去重来源，其中至少 3 个竞品官方来源；若预算耗尽仍未达到门槛，允许输出但必须标记为低覆盖，并降低置信度。
- 报告必须包含固定的 10 个章节、3–5 个竞品、Go / Conditional Go / No-Go 建议、置信度、至少 3 条判断依据、风险和下一步动作。
- 默认只要求 `OPENAI_API_KEY` 一个外部服务密钥；模型通过 `MARKETPULSE_MODEL` 配置，默认值为 `gpt-5.6-sol`。
- 不登录网站，不绕过付费墙、验证码、robots.txt 或反爬限制；不以浏览器自动化作为抓取兜底。
- API Key、完整环境变量和模型隐藏推理不得写入终端、日志、报告或测试快照。
- 默认测试全部离线运行；需要真实网络与 API Key 的测试必须使用 `live` marker 显式启用。
- Windows PowerShell 与 POSIX shell 均应可运行入口命令；路径处理统一使用 `pathlib.Path`。

---

## 1. 项目结构与模块职责

```text
marketpulse-agent/
├─ pyproject.toml                         # 包元数据、依赖、CLI 入口、pytest/Ruff/mypy 配置
├─ .env.example                          # 非敏感配置示例
├─ .gitignore                            # 忽略虚拟环境、缓存、日志和生成报告
├─ README.md                             # 安装、配置、使用、退出码和调试说明
├─ docs/
│  ├─ 01-brainstorming.md                # 已确认的产品与架构范围
│  └─ 02-implementation-plan.md           # 本实施计划
├─ src/marketpulse/
│  ├─ __init__.py                        # 包版本
│  ├─ cli.py                             # Typer CLI、参数校验、退出码、终端阶段输出
│  ├─ config.py                          # 环境变量和默认预算配置
│  ├─ errors.py                          # 稳定错误分类与退出码
│  ├─ budget.py                          # 总时限、调用数、页面数和重试预算
│  ├─ observability.py                   # run_id、结构化日志、阶段指标和敏感字段过滤
│  ├─ workflow.py                        # 显式阶段编排、降级决策和依赖注入
│  ├─ domain/
│  │  ├─ research.py                     # ResearchPlan、SearchQuery、SearchCandidate
│  │  ├─ evidence.py                     # Source、EvidenceClaim、PageEvidence、EvidenceBundle
│  │  └─ analysis.py                     # Competitor、Pricing、MarketAnalysis、QualityResult
│  ├─ agents/
│  │  ├─ factory.py                      # 创建结构化输出 Agent，集中配置模型与追踪
│  │  └─ prompts.py                      # 规划、搜索、抽取、分析提示词
│  ├─ adapters/
│  │  ├─ search.py                       # SearchClient 协议与 OpenAI WebSearchTool 适配器
│  │  ├─ robots.py                       # robots.txt 查询、缓存和访问判定
│  │  └─ fetch.py                        # HTTP 抓取、内容类型/大小限制与重试
│  ├─ services/
│  │  ├─ planner.py                      # 主题规范化与研究计划生成
│  │  ├─ collector.py                    # 查询执行、候选去重、排序和抓取调度
│  │  ├─ extractor.py                    # HTML 文本清洗与证据结构化抽取
│  │  ├─ evidence_store.py               # 内存证据去重、冲突标记和来源映射
│  │  ├─ analyzer.py                     # 基于证据生成市场分析
│  │  ├─ quality.py                      # 输入、证据和报告质量门禁
│  │  └─ reporter.py                     # Jinja2 渲染和原子写入 Markdown
│  └─ templates/
│     └─ report.md.j2                    # 固定 10 章节中文报告模板
└─ tests/
   ├─ conftest.py                        # 共用 fixtures、固定时钟和 fake runner
   ├─ fixtures/
   │  ├─ search_batches.json             # 离线搜索结果
   │  ├─ pages/                           # 官方页、普通页、空页、超大页 HTML 样本
   │  ├─ evidence_bundle.json             # 分析阶段回放输入
   │  └─ market_analysis.json             # 报告阶段回放输入
   ├─ unit/                               # 与 src 模块一一对应的快速单元测试
   ├─ integration/                        # 离线工作流和 CLI 集成测试
   └─ live/test_live_smoke.py             # 显式启用的真实联网烟雾测试
```

### 关键边界

- `domain/` 只定义稳定数据契约，不导入 SDK、HTTPX、Typer 或 Jinja2。
- `adapters/` 隔离外部系统；测试通过协议注入 fake，不直接 monkeypatch 业务逻辑。
- `services/` 每个文件只负责一个业务阶段，不读取环境变量，不直接退出进程。
- `workflow.py` 是唯一跨阶段协调者；CLI 只解析参数、展示进度和映射退出码。
- 模型输出先经过 Pydantic 校验，再进入下一阶段；字符串 JSON 不在业务层流转。

## 2. 任务依赖顺序

```text
Task 1 基础工程与领域契约
  ├─ Task 2 预算、错误与可观测性
  ├─ Task 3 研究规划 Agent
  └─ Task 4 搜索适配器
Task 2 + Task 4 → Task 5 robots 与页面抓取
Task 1 + Task 5 → Task 6 证据抽取与证据仓库
Task 1 + Task 6 → Task 7 市场分析 Agent
Task 1 + Task 7 → Task 8 报告与质量门禁
Task 2–8 → Task 9 显式工作流编排
Task 9 → Task 10 CLI、文档与端到端验收
```

---

### Task 1: 基础工程、配置与领域数据契约

**Files:**

- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `src/marketpulse/__init__.py`
- Create: `src/marketpulse/config.py`
- Create: `src/marketpulse/domain/research.py`
- Create: `src/marketpulse/domain/evidence.py`
- Create: `src/marketpulse/domain/analysis.py`
- Create: `tests/unit/test_config.py`
- Create: `tests/unit/test_domain_models.py`

**Interfaces:**

- Produces: `Settings.from_env() -> Settings`
- Produces: `SearchQuery`, `ResearchPlan`, `SearchCandidate`, `SearchBatch`
- Produces: `Source`, `EvidenceClaim`, `PageEvidence`, `EvidenceBundle`, `CoverageSummary`
- Produces: `Pricing`, `Competitor`, `MarketAnalysis`, `QualityIssue`, `QualityResult`
- Consumes: 无；这是后续所有任务的数据契约基础。

- [ ] **Step 1: 写项目元数据和依赖配置**

  在 `pyproject.toml` 中设置 `requires-python = ">=3.11,<3.14"`，固定 `openai-agents==0.22.2`，加入 `pydantic>=2.11,<3`、`typer>=0.16,<1`、`httpx>=0.28,<1`、`beautifulsoup4>=4.13,<5`、`jinja2>=3.1,<4`；开发依赖加入 pytest、pytest-asyncio、respx、Ruff 和 mypy。声明入口 `marketpulse = "marketpulse.cli:app"`，但本任务不创建 `cli.py`，入口在 Task 10 生效。

- [ ] **Step 2: 先写配置和数据模型失败测试**

  测试必须覆盖：默认模型、300 秒总预算、12 个查询上限、24 个页面上限、竞品范围 3–8、URL 仅允许 `http/https`、`EvidenceClaim.source_id` 非空、`MarketAnalysis.recommendation` 只允许三种枚举值。

  ```python
  def test_settings_defaults(monkeypatch):
      monkeypatch.setenv("OPENAI_API_KEY", "test-key")
      settings = Settings.from_env()
      assert settings.total_timeout_seconds == 300
      assert settings.max_search_queries == 12
      assert settings.max_pages == 24

  def test_market_analysis_rejects_unknown_recommendation():
      with pytest.raises(ValidationError):
          MarketAnalysis(recommendation="maybe", confidence=0.5, competitors=[])
  ```

- [ ] **Step 3: 运行测试确认红灯**

  Run: `python -m pytest tests/unit/test_config.py tests/unit/test_domain_models.py -q`

  Expected: collection 阶段因 `marketpulse.config` 或领域模型不存在而失败。

- [ ] **Step 4: 创建最小配置与 Pydantic 模型**

  `Settings` 使用不可变 Pydantic model；环境变量只在 `from_env()` 中读取。所有领域对象使用明确枚举和约束；日期使用 `date`，访问时间使用带时区 `datetime`，金额保留来源原始字符串并可选保存数值/币种，避免错误换汇。

- [ ] **Step 5: 添加跨模型不变量**

  `EvidenceBundle` 必须保证 `EvidenceClaim.source_id` 可在 `sources` 中解析；`Competitor.source_ids` 必须非空；`MarketAnalysis.confidence` 范围为 0–1；`ResearchPlan.queries` 最多 12 个且查询文本去除空白后唯一。

- [ ] **Step 6: 运行质量检查**

  Run: `python -m pytest tests/unit/test_config.py tests/unit/test_domain_models.py -q`

  Expected: 全部通过，至少 12 个测试。

  Run: `ruff check src tests && mypy src`

  Expected: 0 error。

- [ ] **Step 7: 提交独立变更**

  ```bash
  git add pyproject.toml .env.example .gitignore src/marketpulse tests/unit/test_config.py tests/unit/test_domain_models.py
  git commit -m "chore: define MarketPulse project contracts"
  ```

**Acceptance:** `pip install -e ".[dev]"` 成功；配置测试与领域模型测试全部通过；后续任务需要的所有类型都有唯一、稳定的定义位置。

---

### Task 2: 错误分类、运行预算与结构化可观测性

**Files:**

- Create: `src/marketpulse/errors.py`
- Create: `src/marketpulse/budget.py`
- Create: `src/marketpulse/observability.py`
- Create: `tests/unit/test_budget.py`
- Create: `tests/unit/test_observability.py`

**Interfaces:**

- Consumes: `Settings` from Task 1。
- Produces: `ErrorCode`, `MarketPulseError`, `FatalResearchError`, `RecoverableResearchError`, `BudgetExceeded`
- Produces: `RunBudget.start(settings, clock)`, `reserve_search()`, `reserve_page()`, `ensure_time_remaining()`
- Produces: `RunStats`, `StageEvent`, `RunLogger`, `redact_sensitive(mapping)`

- [ ] **Step 1: 写预算耗尽与敏感信息过滤失败测试**

  ```python
  def test_search_budget_stops_at_twelve(settings, fake_clock):
      budget = RunBudget.start(settings, fake_clock)
      for _ in range(12):
          budget.reserve_search()
      with pytest.raises(BudgetExceeded) as exc:
          budget.reserve_search()
      assert exc.value.dimension == "search_queries"

  def test_logger_redacts_api_keys(caplog):
      logger = RunLogger(run_id="run_test")
      logger.info("config", OPENAI_API_KEY="sk-secret")
      assert "sk-secret" not in caplog.text
  ```

- [ ] **Step 2: 运行测试确认红灯**

  Run: `python -m pytest tests/unit/test_budget.py tests/unit/test_observability.py -q`

  Expected: 模块不存在导致失败。

- [ ] **Step 3: 实现单调时钟预算和稳定错误码**

  使用注入的 `clock: Callable[[], float]`，避免测试真实等待。错误码固定为 `INVALID_INPUT=2`、`CONFIG_ERROR=3`、`SEARCH_UNAVAILABLE=10`、`NO_USABLE_EVIDENCE=11`、`TIMEOUT=12`、`OUTPUT_WRITE_FAILED=13`、`INTERNAL_ERROR=20`。可恢复错误只写入 `RunStats.warnings`，致命错误由 CLI 映射为非零退出码。

- [ ] **Step 4: 实现 JSON Lines 日志和阶段指标**

  每条日志包含 `timestamp`、`run_id`、`stage`、`event`、`level`、`duration_ms` 和计数字段。只允许白名单字段；字段名含 `key`、`token`、`secret`、`authorization` 时替换为 `***REDACTED***`。

- [ ] **Step 5: 验证边界和错误映射**

  Run: `python -m pytest tests/unit/test_budget.py tests/unit/test_observability.py -q`

  Expected: 至少 10 个测试通过；模拟时钟到 299.9 秒时允许继续，达到 300 秒时抛出 `BudgetExceeded(dimension="wall_time")`；日志快照中无密钥明文。

- [ ] **Step 6: 提交独立变更**

  ```bash
  git add src/marketpulse/errors.py src/marketpulse/budget.py src/marketpulse/observability.py tests/unit/test_budget.py tests/unit/test_observability.py
  git commit -m "feat: add run budgets and structured telemetry"
  ```

**Acceptance:** 所有预算都可用 fake clock 和计数器确定性测试；错误具有稳定类型和退出码；日志可按 `run_id` 与阶段检索且不会泄露密钥。

---

### Task 3: 研究规划 Agent

**Files:**

- Create: `src/marketpulse/agents/__init__.py`
- Create: `src/marketpulse/agents/factory.py`
- Create: `src/marketpulse/agents/prompts.py`
- Create: `src/marketpulse/services/planner.py`
- Create: `tests/unit/test_planner.py`
- Create: `tests/conftest.py`

**Interfaces:**

- Consumes: `Settings`, `ResearchPlan`, `SearchQuery`, `RunLogger`。
- Produces: `AgentRunner` protocol with `async run(agent, prompt) -> object`
- Produces: `build_planner_agent(settings) -> Agent`
- Produces: `async create_research_plan(topic: str, competitor_limit: int, runner: AgentRunner, settings: Settings) -> ResearchPlan`

- [ ] **Step 1: 创建 fake runner fixture 并写规划测试**

  用 fake runner 返回固定 `ResearchPlan`，验证中文输入会生成英文规范化主题；查询覆盖 `market demand`、`competitors`、`official product`、`pricing` 四类意图；首轮查询不超过 8 个。

  ```python
  async def test_planner_returns_bounded_diverse_queries(fake_runner, settings):
      plan = await create_research_plan("AI 会议纪要工具", 5, fake_runner, settings)
      assert plan.normalized_topic == "AI meeting notes tools"
      assert len(plan.queries) <= 8
      assert {q.intent for q in plan.queries} >= {"demand", "competitor", "product", "pricing"}
  ```

- [ ] **Step 2: 运行测试确认红灯**

  Run: `python -m pytest tests/unit/test_planner.py -q`

  Expected: planner 模块或函数不存在。

- [ ] **Step 3: 创建集中式 Agent factory**

  `factory.py` 只负责把 `settings.model`、`output_type`、提示词和 tracing 配置组装成 SDK `Agent`。使用 Agents SDK 的 Pydantic `output_type`；`RunConfig` 设置 `workflow_name="MarketPulse"`、`group_id=run_id`、`trace_include_sensitive_data=False`。

- [ ] **Step 4: 实现规划提示词与调用包装**

  提示词要求输出英文搜索主题、4–8 个首轮查询、每个查询唯一意图、不得直接回答市场结论。`create_research_plan` 在调用前做主题 trim，在调用后再次验证数量和唯一性；结构校验失败只允许一次修复调用。

- [ ] **Step 5: 验证正常与错误路径**

  Run: `python -m pytest tests/unit/test_planner.py -q`

  Expected: 至少 7 个测试通过，包括空查询列表、重复查询、runner 超时、首次结构错误后修复成功、连续两次结构错误转为 `FatalResearchError`。

- [ ] **Step 6: 提交独立变更**

  ```bash
  git add src/marketpulse/agents src/marketpulse/services/planner.py tests/conftest.py tests/unit/test_planner.py
  git commit -m "feat: add bounded research planning agent"
  ```

**Acceptance:** 任意合法中英文主题均转换为受预算约束、意图覆盖完整的英文研究计划；离线测试不调用 OpenAI API。

---

### Task 4: OpenAI Hosted Web Search 适配器

**Files:**

- Create: `src/marketpulse/adapters/__init__.py`
- Create: `src/marketpulse/adapters/search.py`
- Create: `tests/unit/test_search_adapter.py`
- Create: `tests/fixtures/search_batches.json`

**Interfaces:**

- Consumes: `SearchQuery`, `SearchCandidate`, `Settings`, `RunBudget`, `AgentRunner`。
- Produces: `SearchClient` protocol: `async search(query: SearchQuery, *, limit: int) -> list[SearchCandidate]`
- Produces: `OpenAIWebSearchClient.search(...)`
- Produces: `canonicalize_url(url: str) -> str`

- [ ] **Step 1: 写协议和 URL 规范化失败测试**

  测试 `utm_*`、`gclid`、fragment 被移除；尾部斜杠统一；非 HTTP(S)、localhost、私网 IP 和含凭据 URL 被拒绝；同一 canonical URL 只保留一条。

- [ ] **Step 2: 写搜索行为失败测试**

  fake runner 返回 `SearchBatch`，其中包含官网、新闻页、重复 URL 和无效 URL。断言适配器只返回有效候选，保留 `query_id`、标题、URL、候选来源类型，不把 snippet 写入 `EvidenceClaim`。

- [ ] **Step 3: 运行测试确认红灯**

  Run: `python -m pytest tests/unit/test_search_adapter.py -q`

  Expected: search adapter 不存在。

- [ ] **Step 4: 实现 Hosted WebSearchTool 包装**

  为每个查询创建带 `WebSearchTool(search_context_size="medium")` 的搜索 Agent，并使用 `SearchBatch` 结构化输出。适配器每次调用前执行 `budget.reserve_search()`；SDK 错误被分类为限流、认证、超时或未知错误；认证错误立即致命，限流和瞬时错误最多重试 2 次，退避 1 秒和 2 秒。

- [ ] **Step 5: 加入来源偏好排序但不把排序当证据**

  候选排序键依次为：官方域名提示、查询意图匹配、HTTPS、原始顺序。`pricing` 查询优先 URL 路径含 `/pricing`；排序只决定抓取顺序，最终事实仍必须由页面正文验证。

- [ ] **Step 6: 验证预算与错误分类**

  Run: `python -m pytest tests/unit/test_search_adapter.py -q`

  Expected: 至少 12 个测试通过；第 13 次查询在调用 runner 前失败；限流重试次数精确为 2；认证失败不重试。

- [ ] **Step 7: 提交独立变更**

  ```bash
  git add src/marketpulse/adapters/search.py tests/unit/test_search_adapter.py tests/fixtures/search_batches.json
  git commit -m "feat: add bounded OpenAI web search adapter"
  ```

**Acceptance:** 搜索 SDK 被隔离在一个适配器内；业务层只看规范化候选；12 查询上限、重试策略和 URL 安全规则均有离线测试。

---

### Task 5: robots.txt 检查与安全页面抓取

**Files:**

- Create: `src/marketpulse/adapters/robots.py`
- Create: `src/marketpulse/adapters/fetch.py`
- Create: `tests/unit/test_robots.py`
- Create: `tests/unit/test_fetch.py`
- Create: `tests/fixtures/pages/official_pricing.html`
- Create: `tests/fixtures/pages/article.html`
- Create: `tests/fixtures/pages/empty.html`
- Create: `tests/fixtures/pages/oversized.html`

**Interfaces:**

- Consumes: `SearchCandidate`, `Source`, `Settings`, `RunBudget`, `RunLogger`。
- Produces: `RobotsPolicy.allowed(url: str, user_agent: str) -> bool`
- Produces: `FetchedPage(source: Source, content_type: str, body: bytes, final_url: str, fetched_at: datetime)`
- Produces: `PageFetcher.fetch(candidate: SearchCandidate) -> FetchedPage`

- [ ] **Step 1: 写 robots 缓存和拒绝访问测试**

  用 respx 模拟允许、拒绝、404 和超时。robots 结果按 origin 缓存；明确 `Disallow` 时不请求目标页；robots 404 视为允许；robots 超时采用保守拒绝并记录原因 `robots_unavailable`。

- [ ] **Step 2: 写页面抓取失败测试**

  覆盖 200 HTML、重定向到新域名后二次 robots 检查、429/503 重试、404 不重试、非文本 content type、正文超过 2 MiB、私网重定向阻断和 15 秒超时。

- [ ] **Step 3: 运行测试确认红灯**

  Run: `python -m pytest tests/unit/test_robots.py tests/unit/test_fetch.py -q`

  Expected: 模块不存在。

- [ ] **Step 4: 实现安全访问规则**

  使用 HTTPX async client，`User-Agent` 固定为 `MarketPulseBot/0.1 (+contact: local-cli)`；只接受公开 HTTP(S)；DNS 解析后拒绝 loopback、link-local、private、multicast 和 reserved 地址；最多跟随 5 次重定向，每次重定向重新做 URL 与 robots 校验。

- [ ] **Step 5: 实现抓取和重试策略**

  只接受 `text/html`、`text/plain`、`application/xhtml+xml`；流式读取最多 2 MiB；429、502、503、504 和连接错误最多重试 2 次；404、401、403、robots 拒绝、无效内容类型不重试。每次实际页面尝试都记录状态，但页面预算按候选 URL 计一次。

- [ ] **Step 6: 运行测试并核对请求次数**

  Run: `python -m pytest tests/unit/test_robots.py tests/unit/test_fetch.py -q`

  Expected: 至少 18 个测试通过；任何失败路径都不会超过配置的重试和重定向上限；被拒绝 URL 无正文请求。

- [ ] **Step 7: 提交独立变更**

  ```bash
  git add src/marketpulse/adapters/robots.py src/marketpulse/adapters/fetch.py tests/unit/test_robots.py tests/unit/test_fetch.py tests/fixtures/pages
  git commit -m "feat: add safe public-page fetcher"
  ```

**Acceptance:** 抓取器不访问私网、不绕过 robots、不下载非文本或超大响应；单页失败以结构化原因返回且不会中断其他候选。

---

### Task 6: 页面文本清洗、证据抽取与内存证据仓库

**Files:**

- Create: `src/marketpulse/services/extractor.py`
- Create: `src/marketpulse/services/evidence_store.py`
- Create: `tests/unit/test_extractor.py`
- Create: `tests/unit/test_evidence_store.py`
- Create: `tests/fixtures/evidence_bundle.json`

**Interfaces:**

- Consumes: `FetchedPage`, `PageEvidence`, `EvidenceClaim`, `EvidenceBundle`, `AgentRunner`。
- Produces: `extract_visible_text(page: FetchedPage) -> str`
- Produces: `async extract_page_evidence(page: FetchedPage, topic: str, runner: AgentRunner, settings: Settings) -> PageEvidence`
- Produces: `EvidenceStore.add(page_evidence)`, `bundle() -> EvidenceBundle`, `coverage() -> CoverageSummary`

- [ ] **Step 1: 写确定性 HTML 清洗测试**

  断言 script、style、nav、cookie banner 和重复空白被移除；标题、正文、价格表文字被保留；空页面返回可恢复错误；送入模型的正文上限为 40,000 字符并保留开头、含价格关键词段落和结尾。

- [ ] **Step 2: 写证据约束测试**

  fake runner 返回功能、定价和需求事实。断言每条 claim 都绑定当前页面 `source_id`，含 20–240 字符原文摘录或精确页面片段，`claim_type` 属于允许枚举，搜索 snippet 字段不存在。

- [ ] **Step 3: 写仓库去重与冲突测试**

  相同 canonical URL 合并；近似重复 claim 合并；同一竞品同一定价项出现不同值时保留两条并标记 `conflict_group_id`；官方来源优先级高于第三方，但第三方证据不被静默删除。

- [ ] **Step 4: 运行测试确认红灯**

  Run: `python -m pytest tests/unit/test_extractor.py tests/unit/test_evidence_store.py -q`

  Expected: extractor 和 store 模块不存在。

- [ ] **Step 5: 实现清洗与结构化抽取 Agent**

  Beautiful Soup 只做确定性文本清洗；Agent 的 `output_type` 为 `PageEvidence`。提示词明确：只提取页面直接支持的事实；不得根据品牌常识补全；价格必须保留计费周期、币种、单位和限定条件；找不到时返回空列表而不是猜测。

- [ ] **Step 6: 实现证据覆盖统计**

  `CoverageSummary` 包含 `unique_sources`、`official_sources`、`competitors_with_official_source`、`competitors_with_pricing_source`、`claim_counts_by_type` 和 `conflicts`。该对象决定是否触发一次补搜，不直接决定市场结论。

- [ ] **Step 7: 验证离线可回放性**

  Run: `python -m pytest tests/unit/test_extractor.py tests/unit/test_evidence_store.py -q`

  Expected: 至少 16 个测试通过；固定 HTML + fake runner 输出得到字节级稳定的 `evidence_bundle.json`。

- [ ] **Step 8: 提交独立变更**

  ```bash
  git add src/marketpulse/services/extractor.py src/marketpulse/services/evidence_store.py tests/unit/test_extractor.py tests/unit/test_evidence_store.py tests/fixtures/evidence_bundle.json
  git commit -m "feat: extract and normalize source-backed evidence"
  ```

**Acceptance:** 证据只来自已抓取正文；每个事实都可追溯到来源；重复、冲突、缺失和覆盖率均有确定性表示。

---

### Task 7: 基于证据的市场分析 Agent

**Files:**

- Create: `src/marketpulse/services/analyzer.py`
- Create: `tests/unit/test_analyzer.py`
- Create: `tests/fixtures/market_analysis.json`
- Modify: `src/marketpulse/agents/prompts.py`

**Interfaces:**

- Consumes: `EvidenceBundle`, `CoverageSummary`, `MarketAnalysis`, `AgentRunner`。
- Produces: `async analyze_market(topic: str, evidence: EvidenceBundle, coverage: CoverageSummary, competitor_limit: int, runner: AgentRunner, settings: Settings) -> MarketAnalysis`
- Produces: `validate_analysis_citations(analysis, evidence) -> list[QualityIssue]`

- [ ] **Step 1: 写分析结构与引用完整性失败测试**

  使用固定 `evidence_bundle.json` 和 fake runner。断言输出 3–5 个竞品、推荐枚举合法、置信度 0–1、至少 3 条依据、每个竞品至少 1 个来源、每项公开价格有官方来源 ID。

- [ ] **Step 2: 写幻觉与缺失定价测试**

  fake 输出引用不存在的 `source_id` 时校验失败；证据中无价格时，竞品价格必须为 `未公开/未验证` 且不得出现数字；低于 8 个来源时置信度上限为 0.55，并加入低覆盖限制。

- [ ] **Step 3: 运行测试确认红灯**

  Run: `python -m pytest tests/unit/test_analyzer.py -q`

  Expected: analyzer 模块不存在。

- [ ] **Step 4: 实现证据封闭提示与结构化输出**

  输入只包含主题、覆盖统计和序列化证据，不包含搜索摘要。提示词区分 `fact`、`inference`、`recommendation`；要求所有事实字段携带 `source_ids`；禁止精确 TAM/SAM/SOM，除非证据中存在同口径数据。

- [ ] **Step 5: 实现程序化后校验与一次修复**

  校验所有 source ID、竞品数、定价引用、建议依据数量和置信度上限。首次失败时把机器可读 issue 列表交给同一分析 Agent 修复一次；第二次失败抛出 `FatalResearchError(code=NO_USABLE_EVIDENCE)`，不把不合格分析交给报告层。

- [ ] **Step 6: 验证分析测试与快照**

  Run: `python -m pytest tests/unit/test_analyzer.py -q`

  Expected: 至少 12 个测试通过；固定输入产生字段稳定的 `MarketAnalysis`；不存在来源外价格和事实；无论候选上限为 5 还是 8，核心竞品表始终保留相关性最高的 3–5 个。

- [ ] **Step 7: 提交独立变更**

  ```bash
  git add src/marketpulse/services/analyzer.py src/marketpulse/agents/prompts.py tests/unit/test_analyzer.py tests/fixtures/market_analysis.json
  git commit -m "feat: add evidence-closed market analysis"
  ```

**Acceptance:** 分析结果的每个事实引用均能解析到证据包；低覆盖会确定性降低置信度；无证据价格不会被模型补写。

---

### Task 8: Markdown 报告渲染、质量门禁与原子写入

**Files:**

- Create: `src/marketpulse/templates/report.md.j2`
- Create: `src/marketpulse/services/quality.py`
- Create: `src/marketpulse/services/reporter.py`
- Create: `tests/unit/test_quality.py`
- Create: `tests/unit/test_reporter.py`

**Interfaces:**

- Consumes: `ResearchPlan`, `EvidenceBundle`, `CoverageSummary`, `MarketAnalysis`, `QualityResult`。
- Produces: `evaluate_quality(...) -> QualityResult`
- Produces: `render_report(...) -> str`
- Produces: `write_report_atomic(markdown: str, output_path: Path) -> Path`

- [ ] **Step 1: 写固定章节与 Markdown 引用测试**

  断言报告按规格包含并仅包含一次以下二级标题：执行摘要、研究范围与方法、市场信号、核心竞品对比、定价与商业模式、机会与壁垒、可行性建议、风险与下一步、来源、局限性与未验证信息。

- [ ] **Step 2: 写质量门禁测试**

  致命条件：无可用来源、无有效建议、引用 source ID 不存在。非致命条件：来源少于 8、官方来源少于 3、竞品少于 3、定价覆盖不足、存在冲突。非致命问题必须同时出现在报告开头警示和局限性章节。

- [ ] **Step 3: 写原子写入失败测试**

  在临时目录写入时，先创建同目录临时文件，`fsync` 后 `replace`；模拟 replace 失败时目标文件保持原内容且临时文件被清理；输出统一 UTF-8、LF 换行。

- [ ] **Step 4: 运行测试确认红灯**

  Run: `python -m pytest tests/unit/test_quality.py tests/unit/test_reporter.py -q`

  Expected: quality、reporter 或模板不存在。

- [ ] **Step 5: 实现模板和门禁**

  竞品与定价使用 Markdown 表格；所有来源以 `[S1]` 稳定编号，在事实后用 `[S1](URL)` 形式链接；来源清单列出标题、域名、来源类型和访问日期。模板不执行模型调用，确保结构稳定。

- [ ] **Step 6: 验证快照和文件行为**

  Run: `python -m pytest tests/unit/test_quality.py tests/unit/test_reporter.py -q`

  Expected: 至少 14 个测试通过；固定输入报告快照稳定；所有被引用 source ID 都出现在来源表中且来源表无孤立 ID；写入失败映射为 `OUTPUT_WRITE_FAILED`。

- [ ] **Step 7: 提交独立变更**

  ```bash
  git add src/marketpulse/templates/report.md.j2 src/marketpulse/services/quality.py src/marketpulse/services/reporter.py tests/unit/test_quality.py tests/unit/test_reporter.py
  git commit -m "feat: render quality-gated market reports"
  ```

**Acceptance:** 报告结构完全确定；致命与非致命质量问题区分明确；任何已存在的目标文件都不会因中途写入失败而损坏。

---

### Task 9: 显式阶段工作流与降级策略

**Files:**

- Create: `src/marketpulse/services/collector.py`
- Create: `src/marketpulse/workflow.py`
- Create: `tests/integration/test_workflow.py`
- Create: `tests/integration/test_workflow_failures.py`

**Interfaces:**

- Consumes: Tasks 2–8 的公开接口。
- Produces: `WorkflowDependencies(search, fetcher, runner, clock, logger)`
- Produces: `async run_marketpulse(request: MarketPulseRequest, deps: WorkflowDependencies, settings: Settings) -> MarketPulseResult`
- Produces: `MarketPulseRequest(topic, competitor_limit, output_path)` and `MarketPulseResult(run_id, report_path, quality, stats)`

- [ ] **Step 1: 写完整离线成功路径集成测试**

  注入 fake search、fake fetcher、fake runner 和 fake clock。断言阶段顺序固定为 `PLAN → SEARCH → FETCH → EXTRACT → ANALYZE → QUALITY → WRITE`，生成报告，记录 8+ 来源、3+ 官方来源和 3–5 竞品。

- [ ] **Step 2: 写补搜触发测试**

  首轮结束时若 `unique_sources < 8`、`official_sources < 3` 或 `competitors_with_official_source < 3`，只允许生成一轮最多 4 个定向补充查询；覆盖已达标时不得补搜；查询总数永不超过 12。

- [ ] **Step 3: 写并发抓取与确定性排序测试**

  抓取并发上限为 5；完成顺序可以变化，但进入证据仓库前按候选优先级和 canonical URL 排序，确保固定 fixture 输出稳定。单页失败只增加 warning，并继续处理其余页面。

- [ ] **Step 4: 写失败与预算降级矩阵测试**

  覆盖搜索整体失败、部分页面失败、全部页面失败、结构输出连续失败、总超时、页面预算耗尽、报告写入失败。验证错误码、是否允许生成报告以及局限性披露与规格一致。

- [ ] **Step 5: 运行测试确认红灯**

  Run: `python -m pytest tests/integration/test_workflow.py tests/integration/test_workflow_failures.py -q`

  Expected: workflow 和 collector 不存在。

- [ ] **Step 6: 实现 collector 与阶段编排**

  `collector.py` 只协调查询、候选合并和并发抓取；`workflow.py` 使用显式阶段函数，不写自由循环。每个阶段进入前调用 `ensure_time_remaining()`，退出时写 `StageEvent`。预算耗尽后：已有至少 1 个可用来源则进入低覆盖分析；0 个来源则致命失败。

- [ ] **Step 7: 加入顶层超时和取消清理**

  用 `asyncio.timeout(settings.total_timeout_seconds)` 包裹整个工作流；超时时取消未完成抓取任务并等待清理，禁止后台任务在 CLI 返回后继续写日志或文件。

- [ ] **Step 8: 验证全矩阵**

  Run: `python -m pytest tests/integration/test_workflow.py tests/integration/test_workflow_failures.py -q`

  Expected: 至少 15 个集成测试通过；fake clock 下所有预算分支在 2 秒内完成；无真实网络调用。

- [ ] **Step 9: 提交独立变更**

  ```bash
  git add src/marketpulse/services/collector.py src/marketpulse/workflow.py tests/integration
  git commit -m "feat: orchestrate the bounded research workflow"
  ```

**Acceptance:** 所有阶段和降级规则可离线复现；单页故障不拖垮运行；致命错误不生成伪报告；任务取消后无悬挂协程。

---

### Task 10: CLI、使用文档与端到端验收

**Files:**

- Create: `src/marketpulse/cli.py`
- Create: `README.md`
- Create: `tests/integration/test_cli.py`
- Create: `tests/live/test_live_smoke.py`
- Modify: `.env.example`
- Modify: `pyproject.toml`

**Interfaces:**

- Consumes: `Settings.from_env()`, `run_marketpulse(...)`, `MarketPulseError`。
- Produces: CLI `marketpulse TOPIC [--output PATH] [--competitors 3..8] [--log-file PATH]`
- Produces: 稳定退出码和用户可操作错误信息。

- [ ] **Step 1: 写 CLI 参数与退出码失败测试**

  使用 Typer `CliRunner`。覆盖：合法主题、空字符串、1 字符、超过 200 字符、竞品 2/9、缺失 API Key、自定义输出路径、工作流错误码映射。非法输入必须在 fake workflow 调用前退出。

- [ ] **Step 2: 写成功输出与日志隐私测试**

  fake workflow 成功时终端显示 run ID、阶段摘要、报告绝对路径和总耗时；默认不显示模型 prompt、页面全文或 API Key。报告默认写入 `reports/<slug>-<YYYYMMDD-HHMMSS>.md`。

- [ ] **Step 3: 运行测试确认红灯**

  Run: `python -m pytest tests/integration/test_cli.py -q`

  Expected: `marketpulse.cli` 不存在。

- [ ] **Step 4: 实现 CLI 和依赖组装**

  CLI 是 composition root：创建 HTTP client、SearchClient、PageFetcher、RunLogger 和 SDK runner，然后调用工作流。使用 `asyncio.run` 仅一次；所有资源通过 async context manager 关闭。捕获已知 `MarketPulseError` 并返回稳定退出码，未知异常只显示 run ID 和通用提示，详细堆栈写 debug 日志。

- [ ] **Step 5: 编写 README 与环境示例**

  README 必须包含 Python 版本、安装命令、`OPENAI_API_KEY`、可选 `MARKETPULSE_MODEL`、三个 CLI 示例、输出结构、预算默认值、退出码表、如何运行离线测试、如何显式运行 live 测试、常见失败排查和数据/隐私说明。

- [ ] **Step 6: 添加 opt-in live smoke test**

  `@pytest.mark.live` 且在 `RUN_LIVE_TESTS=1` 与 `OPENAI_API_KEY` 同时存在时才运行。主题使用 `AI meeting notes tools`，竞品数 3；断言 300 秒内结束、报告存在、10 个标题齐全、至少 8 个 HTTP(S) 链接、建议枚举出现且日志无密钥。

- [ ] **Step 7: 运行完整离线验证**

  Run: `python -m pytest -m "not live" -q`

  Expected: 100% 通过，0 个真实网络请求，测试总时长目标小于 30 秒。

  Run: `ruff check src tests && ruff format --check src tests && mypy src`

  Expected: 0 error。

- [ ] **Step 8: 运行 CLI 帮助和打包烟雾检查**

  Run: `marketpulse --help`

  Expected: 显示 TOPIC、`--output`、`--competitors`、`--log-file`，退出码 0。

  Run: `python -m build`

  Expected: 成功生成 wheel 与 sdist；在临时虚拟环境安装 wheel 后 `marketpulse --help` 成功。

- [ ] **Step 9: 在具备授权和 API Key 时运行真实验收**

  Run: `$env:RUN_LIVE_TESTS='1'; python -m pytest tests/live/test_live_smoke.py -m live -v -s`

  Expected: 300 秒内 PASS，并生成符合 10 章节、8 来源、3 官方来源、3 个竞品和明确建议的中文报告。若外部服务不可用，测试必须报告具体分类，而不是断言业务逻辑失败。

- [ ] **Step 10: 提交独立变更**

  ```bash
  git add src/marketpulse/cli.py README.md tests/integration/test_cli.py tests/live/test_live_smoke.py .env.example pyproject.toml
  git commit -m "feat: ship MarketPulse CLI and acceptance suite"
  ```

**Acceptance:** 新环境可按 README 安装；`marketpulse --help` 可用；全部离线测试、lint 和类型检查通过；具备 API Key 时 live smoke 在 5 分钟内生成合格报告。

---

## 3. 总体验收矩阵

| 维度 | 验收方法 | 通过标准 |
|---|---|---|
| CLI | `marketpulse "AI meeting notes tools"` | 退出码 0，输出 UTF-8 Markdown 路径 |
| 报告结构 | 解析生成文件的 H2 标题 | 固定 10 章节，各出现一次且顺序正确 |
| 竞品覆盖 | 读取竞品表 | 3–5 个真实全球竞品 |
| 来源覆盖 | 提取 Markdown 链接与来源表 | ≥8 个去重来源，≥3 个官方来源 |
| 定价可信度 | 对价格行抽样核验 source ID | 有公开价格则引用官方页；缺失则标记未验证 |
| 决策输出 | 解析建议章节 | 三态建议之一、置信度、≥3 条依据、风险和动作 |
| 时间预算 | live smoke 计时 | 正常网络下 ≤300 秒；超时路径受硬限制 |
| 查询预算 | fake search 调用计数 | ≤12 次，首轮 ≤8，补搜 ≤4 且最多一轮 |
| 页面预算 | fake fetcher 调用计数 | ≤24 个候选，抓取并发 ≤5 |
| 故障隔离 | 注入单页 404/503/解析空页 | 其他页面继续，报告披露缺失 |
| 致命故障 | 注入搜索整体失败/0 证据/不可写路径 | 非零退出码，不生成伪报告 |
| 可重复性 | 两次运行同一 fixtures | 领域输出相等，报告快照一致 |
| 隐私 | 扫描 stdout、日志、报告 | 不含 API Key、Authorization 或隐藏推理 |
| 工程质量 | pytest、Ruff、mypy、build | 全部 0 error，离线测试不访问网络 |

## 4. 风险点与调试预案

### 4.1 OpenAI API、Hosted Web Search 或网络整体不可用

- **识别信号：** 搜索调用连续出现认证错误、429、5xx、连接超时或 DNS 错误。
- **记录内容：** run ID、阶段、错误分类、HTTP 状态、attempt、退避时间和已消耗预算；不记录请求密钥或完整 prompt。
- **处理：** 认证错误立即失败；429/瞬时错误最多重试 2 次；若没有任何候选或证据，返回 `SEARCH_UNAVAILABLE`，不生成报告。
- **调试：** 用 fake runner 分别注入 401、429、503 和 timeout；核对调用次数、退避和错误码。真实环境只用最小查询验证服务可达性。

### 4.2 单页抓取失败、动态页面或 robots 拒绝

- **识别信号：** 403/404、正文为空、content type 不支持、HTML 只有脚本壳、robots 明确拒绝。
- **记录内容：** canonical URL、domain、状态码、失败分类、重试数和候补 URL；不写页面全文。
- **处理：** 单页失败为可恢复警告；从候选队列选择下一 URL。动态页不启用浏览器绕过，优先补搜同域帮助中心、文档或静态定价页。
- **调试：** respx 固定返回每类失败；确认单页失败不取消 sibling tasks，被 robots 拒绝的页面没有正文请求。

### 4.3 页面解析失败或正文质量差

- **识别信号：** 清洗后少于 200 字符、主要内容为导航/版权、价格关键词存在于 HTML 但清洗结果缺失。
- **记录内容：** 原始字节数、清洗后字符数、保留段落数和截断标记。
- **处理：** 标记 `empty_content` 或 `low_content_quality`；不让模型从标题和 snippet 补事实；尝试候补页面。
- **调试：** 保存脱敏最小 HTML fixture，分别验证表格、cookie banner、script-heavy 和超大页面；对清洗结果做快照。

### 4.4 模型结构化输出校验失败

- **识别信号：** Pydantic ValidationError、缺失 source ID、枚举越界、查询或竞品数量越界。
- **记录内容：** schema 名、字段路径、错误类型和修复次数；默认不记录原始模型输出。
- **处理：** 将机器可读错误列表交给同一阶段 Agent 修复 1 次；再次失败则按阶段分类为致命错误或低覆盖降级。
- **调试：** fake runner 返回缺字段、错枚举、未知 source ID 和超长数组，确保每个分支有精确断言。

### 4.5 引用存在但不支持断言

- **识别信号：** claim 的摘录与声明主题不匹配，或价格来自非官方页但被标为官方。
- **记录内容：** claim ID、source ID、claim type、来源类型和冲突组。
- **处理：** 证据抽取时保存短摘录；分析后校验 source ID 和来源类型；定价没有官方证据时降级为未验证。
- **调试：** 构造“URL 有效但内容不支持”的 fixture，确保质量门禁不能只检查链接存在性。

### 4.6 总超时或预算提前耗尽

- **识别信号：** `RunBudget` 剩余时间 ≤0、查询数达到 12、页面数达到 24。
- **记录内容：** 被耗尽的预算维度、各阶段耗时、已完成来源数和未完成任务数。
- **处理：** 取消未完成任务；已有证据则生成带低覆盖警告的报告；0 证据时返回 `NO_USABLE_EVIDENCE` 或 `TIMEOUT`。
- **调试：** 使用 fake clock 瞬时推进到边界；断言 300 秒处停止、没有后台任务、没有超预算调用。

### 4.7 来源冲突和价格口径不一致

- **识别信号：** 同一产品/套餐出现不同价格、月付与年付混用、地区币种不同、页面更新时间不明。
- **记录内容：** 两侧 source ID、原始价格字符串、计费周期、币种和访问日期。
- **处理：** 不静默覆盖；官方且日期更新者作为主值，其他值进入冲突说明。无法判断时报告并列信息并降低置信度。
- **调试：** 固定两个互相冲突的官方 fixture，验证 conflict group 和报告披露。

### 4.8 报告写入失败

- **识别信号：** 无权限、路径是目录、磁盘错误、原子 replace 失败。
- **记录内容：** 目标绝对路径、异常类型和 run ID，不记录报告全文。
- **处理：** 返回 `OUTPUT_WRITE_FAILED`；保留原目标文件；清理临时文件；终端不得显示“已生成”。
- **调试：** 临时目录中模拟 replace 失败，核对旧文件哈希不变且无残留 `.tmp`。

## 5. 实施纪律与检查点

- 严格按 Task 1 → Task 10 顺序执行；每个任务先红灯测试，再做最小实现，再运行该任务测试。
- 每个任务完成后单独 review 和 commit；不得把相邻任务合并为一个大提交。
- 默认只运行离线测试；live 测试消耗 API 与联网资源，必须显式获得执行授权。
- 发现接口变化时先更新本计划中的生产者/消费者签名，再修改实现，避免跨任务命名漂移。
- 每个检查点至少运行该任务测试；Task 9 和 Task 10 必须运行全部非 live 测试。
- 完成声明前执行：`python -m pytest -m "not live" -q`、`ruff check src tests`、`ruff format --check src tests`、`mypy src` 和 `python -m build`。

## 6. SDK 实施参考

- OpenAI Agents SDK 的 `Agent.output_type` 可直接使用 Pydantic 类型，适合本计划的阶段数据契约：<https://openai.github.io/openai-agents-python/agents/>
- `WebSearchTool` 是 Responses 模型支持的 hosted tool；搜索 SDK 细节只允许出现在 `adapters/search.py`：<https://openai.github.io/openai-agents-python/tools/>
- SDK tracing 默认启用；本项目必须设置 workflow name、run/group ID 并关闭敏感数据采集：<https://openai.github.io/openai-agents-python/tracing/>
- 锁定版本 `openai-agents==0.22.2`，避免实施期间 API 漂移：<https://pypi.org/project/openai-agents/0.22.2/>
