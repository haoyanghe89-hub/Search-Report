# Search-Report — 多智能体事件调查与证据验证报告系统

> 本项目已完成 **Phase 5 报告治理**，完整实现了从多智能体调查、证据验证到报告生成、审核发布的全链路。当前部署目标为 **local trusted single-operator demo**，不适合直接暴露到 LAN/公网。

Search-Report 是一个 Python 3.11+ 的多智能体事件调查系统：**Planner** 规划调查，**Researcher** 检索取证，**Analyst** 形成声明，**Verifier** 验证证据。四个角色通过持久化黑板协作，Verifier 可触发有限轮次的反馈循环补查。最终由报告治理模块生成带声明级引用的调查报告，并通过审核工作流决定是否发布。

完整架构设计见 [ARCHITECTURE.md](ARCHITECTURE.md)，各阶段验收记录见 [docs/](docs/)。

## 核心特性

- **四智能体协作**：Planner → Researcher → Analyst → Verifier，带研究缺口反馈循环
- **证据验证引擎**：15 阶段验证策略，覆盖完整性、语义蕴含、来源独立性、冲突检测等
- **报告治理**：确定性报告生成、声明级引用绑定、15 阶段发布门禁
- **审核工作流**：审核员认证、会话管理、批准/驳回/要求补充研究
- **回放模式**：基于录制的外部调用确定性重放，无需网络或模型密钥
- **East Palestine 案例**：内置 2023 年东巴勒斯坦列车脱轨事故完整调查案例

## 技术栈

- **后端**：FastAPI + SQLAlchemy + Alembic，SQLite（开发）/ PostgreSQL（生产）
- **智能体**：OpenAI Agents SDK，DeepSeek OpenAI 兼容 API
- **前端**：原生 HTML/CSS/JS 静态控制台（`frontend/`）+ React/Vite 旧版市场前端（`web/`）
- **容器化**：Docker + Docker Compose
- **搜索**：DuckDuckGo 优先，依次回退 Bing、Yahoo 与 `ddgs` 元搜索
- **抓取**：HTTPX，遵守 robots.txt，拒绝私网目标

## 安装

```powershell
uv sync --extra dev
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# 编辑 .env 设置 DEEPSEEK_API_KEY
```

## 快速开始

### 运行内置案例回放（无需网络/密钥）

```powershell
uv run python scripts/export_east_palestine_delivery.py
```

### 启动调查 API 服务

```powershell
uv run marketpulse-api
# 服务运行在 http://127.0.0.1:8000
```

### 启动前端控制台

直接用浏览器打开 `frontend/index.html`，或通过 Docker Compose 启动完整栈：

```powershell
docker compose up --build
# 前端: http://localhost:8080
# API:  http://localhost:8000
```

## 前端控制台

`frontend/` 目录提供调查控制台静态界面，功能包括：

- 调查列表与新建调查
- 内置 East Palestine 案例一键回放
- 八视图浏览：概览、智能体流程、来源、证据、声明、冲突与缺口、报告、审核
- 声明级引用溯源抽屉
- 审核员登录与发布决策

界面文本已全部中文化。

## 测试

离线测试不读取真实密钥，也不访问网络：

```powershell
uv run pytest tests/unit tests/integration -q
uv run ruff check src tests
uv run mypy src
```

联网冒烟测试必须显式启用（会调用 DeepSeek 并产生费用）：

```powershell
$env:RUN_LIVE_TESTS = "1"
uv run pytest tests/live -m live -v -s
```

## 数据库迁移

```powershell
# SQLite 本地开发
$env:MARKETPULSE_DATABASE_URL = "sqlite:///data/blackboard.db"
uv run alembic upgrade head

# PostgreSQL
$env:MARKETPULSE_DATABASE_URL = "postgresql+psycopg://marketpulse:<password>@127.0.0.1:55432/marketpulse"
uv run alembic upgrade head
```

## 项目结构

```
src/marketpulse/investigation/
├── agents/          # Planner/Researcher/Analyst/Verifier 定义
├── domain/          # 声明、证据、来源等领域模型
├── harness/         # 运行时状态机、调用绑定、事务
├── feedback/        # 研究缺口反馈循环
├── validation/      # 15 阶段证据验证引擎
├── reporting/       # 报告装配、写作、引用、发布策略
├── review/          # 审核认证、会话、服务、API
├── ingestion/       # HTML/PDF/纯文本解析
├── recording/       # 外部调用录制与回放
└── server.py        # FastAPI 应用入口

frontend/            # 调查控制台（静态）
web/                 # 旧版市场研究前端（React）
case_data/           # East Palestine 案例数据
migrations/          # Alembic 数据库迁移
tests/               # 单元 + 集成测试
docs/                # 设计文档与验收记录
```

## 已知限制

- 单审核员模式，暂不支持多人协作审核
- 无 OCR 能力，PDF 需包含可提取文本层
- 回放模式不触发真实网络调用
- `frontend/` 为静态控制台，`web/` 为旧版市场前端

完整的已知问题与局限性说明见 [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)。

## 交付物清单

详细的 11 项交付物清单与验证方法见 [docs/16-FINAL-DELIVERY-MANIFEST.md](docs/16-FINAL-DELIVERY-MANIFEST.md)。
