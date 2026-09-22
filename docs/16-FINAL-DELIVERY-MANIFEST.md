# 最终交付清单 (Final Delivery Manifest)

> 项目: Search-Report — 多 Agent 事件调查与证据验证报告系统
> 分支: `main` (已合并 `feat/investigation-foundation`)
> 日期: 2026-09-22
> 仓库: https://github.com/haoyanghe89-hub/Search-Report.git

---

## 11 项交付物

### 1. 后端核心源码 — 多 Agent 调查管线
**路径**: `src/marketpulse/investigation/`

- `agents/` — Planner / Researcher / Analyst / Verifier 四角色 Agent 定义
- `harness/` — 运行时状态机、调用绑定、事务单元
- `feedback/` — 研究缺口反馈循环编排
- `domain/` — 声明、证据、来源、定位器等领域模型
- `api.py` / `server.py` — FastAPI 应用入口

**验证**: `uv run pytest tests/unit/investigation tests/integration/investigation`

---

### 2. 报告治理模块
**路径**: `src/marketpulse/investigation/reporting/`

- `assembler.py` — 报告输入装配（确定性排序）
- `writer.py` — 确定性报告起草
- `citations.py` — 引用生成与校验
- `validation.py` — 报告级验证
- `pipeline.py` — 端到端报告流水线
- `renderer.py` — Markdown 渲染
- `release.py` — 发布策略（15 阶段门禁）

**验证**: `uv run pytest tests/integration/investigation/test_phase5_* tests/unit/investigation/test_phase5_*`

---

### 3. 审核工作流
**路径**: `src/marketpulse/investigation/review/`

- `auth.py` — 审核员认证
- `sessions.py` — 会话管理（安全不变量）
- `service.py` — 审核服务（批准/驳回/重审）
- `api.py` — 审核 REST API
- `replay.py` — 回放模式审核

**验证**: `uv run pytest tests/integration/investigation/test_phase5_review_lifecycle.py`

---

### 4. 证据验证引擎
**路径**: `src/marketpulse/investigation/validation/`

- `policy.py` — 15 阶段验证策略
- `integrity.py` — 证据完整性校验
- `entailment.py` — 语义蕴含检查
- `independence.py` — 来源独立性判定
- `conflicts.py` — 冲突检测
- `lineage.py` — 血缘追踪
- `quality.py` / `profiles.py` — 质量画像

**验证**: `uv run pytest tests/unit/investigation/test_validation_core.py`

---

### 5. 前端控制台
**路径**: `frontend/`

- `index.html` — 静态控制台界面
- `app.js` / `styles.css` — 交互逻辑与样式
- `Dockerfile` / `nginx.conf` — 容器化部署

**验证**: 浏览器打开 `frontend/index.html` 或运行 `docker compose up frontend`

---

### 6. East Palestine 案例数据
**路径**: `case_data/east_palestine_2023/`

- `cleaned/` — 10 份清洗后的来源文本（EPA / NTSB / PMC）
- `outputs/` — 生成产物：调查报告、元数据、运行轨迹
- `manifest.json` — 来源统计（10 来源，7 官方/一手）
- `snapshots/` — 原始快照

**验证**: `uv run python scripts/export_east_palestine_delivery.py`

---

### 7. 容器化部署
**路径**: 仓库根目录

- `Dockerfile` — 后端镜像
- `frontend/Dockerfile` — 前端镜像
- `compose.yaml` — 后端 + 前端 + PostgreSQL 编排

**验证**: `docker compose up --build`

---

### 8. 数据库迁移
**路径**: `migrations/versions/`

- `20260921_01` — 调查数据基础
- `20260921_02` — 外部调用录制
- `20260921_03` — 运行时 Harness
- `20260922_04` — 验证核心
- `20260922_05` — Agent 反馈循环
- `20260922_06` — 报告治理

**验证**: `uv run alembic upgrade head`

---

### 9. 测试套件
**路径**: `tests/`

- `unit/investigation/` — 18 个单元测试模块
- `integration/investigation/` — 16 个集成测试模块
- `live/` — 线上冒烟测试
- 总计 220+ 测试用例，全部通过

**验证**: `uv run pytest tests/ -v`

---

### 10. CI/CD 配置
**路径**: `.github/workflows/postgres-integration.yml`

- PostgreSQL 集成测试工作流
- 验证迁移与持久化层在真实数据库下的行为

**验证**: 推送至 GitHub 后自动触发

---

### 11. 项目文档
**路径**: 仓库根目录 + `docs/`

- `README.md` — 项目说明、安装、架构概览
- `ARCHITECTURE.md` — 架构设计文档
- `docs/01` ~ `docs/15` — 各阶段验收文档
- `docs/superpowers/plans/` + `specs/` — 设计规格与实施计划

**验证**: 直接阅读对应 Markdown 文件

---

## 快速验证命令

```bash
# 环境准备
uv sync

# 运行全部测试
uv run pytest tests/ -v

# 数据库迁移
uv run alembic upgrade head

# 启动服务
docker compose up --build

# 案例回放
uv run python scripts/export_east_palestine_delivery.py
```

---

## 已知限制 (Known Limitations)

- 单审核员模式（无多人协作审核）
- 无 OCR 能力（PDF 需可提取文本）
- 回放模式不触发真实网络调用
- 前端为静态控制台，非完整 SPA
