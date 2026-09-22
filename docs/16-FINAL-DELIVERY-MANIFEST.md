# 最终交付清单 (Final Delivery Manifest)

> 项目: Search-Report — 多 Agent 事件调查与证据验证报告系统
> 分支: `main` (已合并 `feat/investigation-foundation`)
> 日期: 2026-09-22
> 仓库: https://github.com/haoyanghe89-hub/Search-Report.git

本清单按笔试题要求的 **11 项必需交付产物**组织，每项给出路径与验证方式。

---

## 必需产物 1: 系统源代码 — 多 Agent 调查管线

**路径**: `src/marketpulse/investigation/`

- `agents/` — Planner / Researcher / Analyst / Verifier 四角色 Agent 定义（Pydantic 强类型契约，结构化 JSON 通信）
- `harness/` — 运行时状态机、调用绑定、事务单元
- `feedback/` — 研究缺口反馈循环编排（有限轮次补查）
- `domain/` — 声明、证据、来源、定位器等领域模型
- `recording/` — 外部调用录制与回放
- `api.py` / `server.py` / `web_api.py` — FastAPI 应用入口

**验证**: `uv run pytest tests/unit/investigation tests/integration/investigation`

---

## 必需产物 2: 容器化部署文件

**路径**: 仓库根目录

- `Dockerfile` — 后端镜像
- `frontend/Dockerfile` — 前端镜像（nginx）
- `docker-compose.yml` — 后端 + 前端 + PostgreSQL 三服务编排（含健康检查）

**验证**: `docker compose up --build`（前端 http://localhost:8080，API http://localhost:8000）

---

## 必需产物 3: 前端交互界面

**路径**: `frontend/`

- `index.html` / `app.js` / `styles.css` — 全中文静态调查控制台
- 功能：调查列表/新建/编辑、一键开始调查（异步轮询+阶段进度）、八视图浏览（概览/智能体流程/来源/证据/声明/冲突与缺口/报告/审核）、声明级引用溯源、PDF 导出、审核员登录与发布决策

**验证**: 浏览器打开 `frontend/index.html`，或 `docker compose up frontend`

---

## 必需产物 4: 内置完整案例

**路径**: `case_data/east_palestine_2023/`

- 2023 年东巴勒斯坦列车脱轨事故（ hazardous-material train derailment）
- `cleaned/` — 10 份清洗后的来源文本（EPA / NTSB / PMC）
- `manifest.json` — 来源统计（10 来源，7 官方/一手）

**验证**: 启动服务后在控制台点击内置案例回放，或 `uv run python scripts/export_east_palestine_delivery.py`

---

## 必需产物 5: 数据快照与来源清单

**路径**: `case_data/east_palestine_2023/`

- `snapshots/` — 原始来源快照
- `manifest.json` — 来源清单与统计
- `source-metadata.json`（`outputs/`）— 导出时生成的来源元数据

**验证**: 直接阅读 JSON 文件；回放时按 `request_fingerprint` 匹配快照

---

## 必需产物 6: 运行轨迹 Trace

**路径**: `case_data/east_palestine_2023/outputs/`

- 运行轨迹文件（导出脚本生成），记录各 Agent 的阶段流转、任务派发与决策链

**验证**: `uv run python scripts/export_east_palestine_delivery.py` 后查看 `outputs/`

---

## 必需产物 7: 调查报告样例

**路径**: `case_data/east_palestine_2023/outputs/east-palestine-full-investigation-report.md`

- **17 章节完整报告**，覆盖笔试题要求的 15 项必需章节：执行摘要、调查范围、调查问题、方法论、来源覆盖、时间线、已验证事实、高概率判断、争议信息、无法验证事项、定量发现、**影响范围与影响分析**、原因与机制分析、**修复措施与后续进展**、冲突分析、结论、局限与引用附录
- 声明级引用绑定（display_ordinal），全部 8 条声明 VERIFIED

**验证**: 阅读报告文件；或运行导出脚本重新生成

---

## 必需产物 8: 系统架构说明

**路径**: `ARCHITECTURE.md`

- 四角色 Agent 协作拓扑与通信契约
- 15 阶段验证策略按声明类型（ClaimType）分 profile 的责任表
- 报告治理（装配→写作→引用→验证→发布门禁）链路
- 审核工作流与回放语义

**验证**: 直接阅读；与 `src/` 源码对照

---

## 必需产物 9: 一键启动说明

**路径**: `README.md`

- 安装（`uv sync --extra dev` + `.env`）
- 快速开始：回放模式（无需网络/密钥）、API 服务、前端控制台、Docker Compose 完整栈
- 数据库迁移（SQLite / PostgreSQL）

**验证**: 按 README 步骤从零执行

---

## 必需产物 10: 测试代码

**路径**: `tests/`

- `unit/investigation/` — 单元测试模块
- `integration/investigation/` — 集成测试模块
- `live/` — 线上冒烟测试（需显式 `RUN_LIVE_TESTS=1`）
- 总计 220+ 测试用例，全部通过；另有 `.github/workflows/postgres-integration.yml` CI 工作流

**验证**: `uv run pytest tests -q`

---

## 必需产物 11: 已知问题与局限性说明

**路径**: `KNOWN_LIMITATIONS.md`

- 涵盖：单审核员演示模式、三位数字演示密码、回放模式限制、搜索引擎外部依赖、单运行锁、SQLite 部署边界、大模型不确定性约束、报告语言混合现状、验证引擎能力边界

**验证**: 直接阅读，与 `.env.example` 中 `REVIEW_*` 配置对照

---

## 快速验证命令

```bash
# 环境准备
uv sync

# 运行全部测试
uv run pytest tests/ -q

# 数据库迁移
uv run alembic upgrade head

# 启动服务（一键）
docker compose up --build

# 案例回放（无需网络/密钥）
uv run python scripts/export_east_palestine_delivery.py
```