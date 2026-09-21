# MarketPulse Agent

> 当前处于 Investigation Platform 原地迁移的 Phase 4.1。旧市场流程暂作回归基线；新调查领域已有外部调用录制/重放、Source Acquisition，以及独立 Harness 的持久化 Step、Unit of Work、调用绑定、预算和五角色类型契约。假 Agent 主链止于 READY_FOR_REPORT；真实调查 Agent、ValidationPolicy、报告生成/发布、审核和新前端尚未接入。目标部署为 **local trusted single-operator demo**，不适合直接暴露到 LAN/公网。已确认合同见 [ARCHITECTURE.md](ARCHITECTURE.md)，阶段边界见 [迁移计划](docs/07-investigation-migration.md)。

MarketPulse 是一个 Python 3.11+ 四智能体市场研究应用：主 Agent 规划与复核，搜索 Agent 检索取证，分析 Agent 形成结论，报告 Agent 撰写中文报告。四个角色通过持久化黑板协作，主 Agent 可要求有限轮次的补查。

完整协作设计、接口和部署说明见 [四智能体架构](docs/05-multiagent-architecture.md)。

## 技术边界

- LLM：DeepSeek OpenAI 兼容 Chat Completions API，`https://api.deepseek.com`
- Agent 编排：OpenAI Agents SDK；每次运行独立 DeepSeek client、独立角色提示词及结构化输出，关闭 tracing
- 状态：SQLAlchemy 黑板，本地 SQLite，服务端可切换 PostgreSQL；可选 Redis 进度通知
- 搜索：自定义 `PublicSearchClient`，DuckDuckGo 优先，依次回退 Bing、Yahoo 与无密钥 `ddgs` 元搜索
- 抓取：HTTPX，遵守 robots.txt，拒绝私网目标、非文本和超过 2 MiB 的页面
- 输出：固定 10 章节的中文 Markdown

## 安装

```powershell
uv sync --extra dev
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env and set DEEPSEEK_API_KEY; do not overwrite an existing configured .env.
```

启动时读取当前工作目录的 `.env`，或 `MARKETPULSE_ENV_FILE` 指定的文件。进程环境变量优先，不扫描父目录。`.env`、数据文件和报告均被 Git 忽略；密钥不进入模型上下文或任务黑板。

## 使用

```powershell
uv run marketpulse "AI meeting notes tools"
uv run marketpulse --competitors 5 "AI contract review for small businesses"
uv run marketpulse --output reports/carbon.md --log-file logs/carbon.jsonl "carbon accounting software for SMBs"
```

`--competitors`、`--output`、`--log-file` 等全局选项需放在关键词之前。

默认总时限 300 秒（可通过 `.env` 配置为 600 秒）、最多 12 个搜索查询、24 个页面、并发抓取 5。默认最多两轮研究；预留一部分预算给补查。搜索摘要只用于发现 URL；进入分析的证据来自成功读取的正文。

## 可视化前端

前端位于 `web/`，使用 Vite、React、TypeScript 与 shadcn/ui。它通过本地 FastAPI 适配层直接复用同一套 `run_marketpulse` Python 工作流，不会在 Node 进程中复制 Agent 逻辑。

先启动 API：

```powershell
uv sync --extra dev --extra web
uv run marketpulse-api
```

再打开另一个终端启动前端：

```powershell
cd web
npm install
npm run dev
```

访问 `http://localhost:5173`。开发服务器会把 `/api` 请求代理到 `http://127.0.0.1:8000`；生成的 Markdown 仍写入 `reports/`，页面同时展示结构化的结论、市场信号、竞品、定价与来源。

前端校验命令：

```powershell
cd web
npm test
npm run lint
npm run build
```

## 测试

离线测试不读取真实密钥，也不访问网络：

```powershell
uv run pytest -m "not live" -q
uv run ruff check src tests
uv run mypy src
```

联网冒烟测试必须显式启用，会调用 DeepSeek 并产生费用：

```powershell
$env:RUN_LIVE_TESTS = "1"
uv run pytest tests/live -m live -v -s
```

## 退出码

| 退出码 | 含义 |
|---:|---|
| 0 | 成功 |
| 2 | 输入无效 |
| 3 | 配置或密钥缺失 |
| 10 | 搜索服务不可用 |
| 11 | 没有可用证据或分析结构无效 |
| 12 | 超时或预算耗尽 |
| 13 | 报告写入失败 |
| 20 | 未预期内部错误 |

## 调试

- 使用 `--log-file logs/run.jsonl` 保存阶段、计数和错误分类。
- 429、502、503、504、连接错误和超时最多重试两次。
- 单页失败不会终止整次运行；所有页面失败才会返回退出码 11。
- 低于 8 个来源或 3 个官方来源时仍可生成报告，但会显示覆盖警告并把置信度上限降为 55%。
- `GET /api/runs/{run_id}` 查看已提交黑板；`GET /api/runs/{run_id}/events?after_version=0` 查看事件。接口仅用于本机开发，未增加认证。
- 状态及事件用于审计，不会在进程崩溃后自动恢复执行。四个逻辑 Agent 当前由单进程调度，不是四个独立 worker。
- 日志、报告和终端均不会输出 API Key 或模型隐藏推理。
- 若可信本地代理把公网 DNS 映射到 `198.18.0.0/15`，可显式设置 `MARKETPULSE_ALLOW_PROXY_DNS=true`；其他私网和 localhost 仍会被拒绝。

## Phase 1 通用 Blob Storage

本地内容寻址存储无额外依赖，接收二进制输入、返回可持久化的逻辑引用。实际文件路径仅在 adapter 内使用。读取会重新校验 SHA-256；缺失/损坏分别抛出 `BLOB_NOT_FOUND` / `BLOB_INTEGRITY_ERROR`，不会重新联网补齐。

```python
from pathlib import Path
from marketpulse.infrastructure.storage import BlobRef, BlobStoragePort
from marketpulse.infrastructure.storage import LocalContentAddressedBlobStorage

storage: BlobStoragePort = LocalContentAddressedBlobStorage(Path("data/blobs"))
saved = storage.put_bytes(b"immutable source snapshot")
portable_ref = saved.ref.uri  # blob://sha256/<hash>; can be stored as DB metadata
assert storage.get_bytes(BlobRef.from_uri(portable_ref)) == b"immutable source snapshot"
```

Blob 先完整落盘，再由未来 repository 提交数据库引用。相同内容去重；适配器不提供覆盖和删除操作。需要支持同卷硬链接的本地文件系统（Windows NTFS / Linux 本地 Docker volume）。崩溃可能留下未引用完整 Blob 或 staging 临时文件，当前无自动 GC。该同步 Port 应由异步应用在线程执行器中调用，避免阻塞 API event loop。

```powershell
uv run pytest tests/unit/test_blob_storage.py tests/unit/test_infrastructure_boundary.py -q
```

## Phase 2 Investigation Data Foundation

新调查领域位于 `src/marketpulse/investigation/`，与旧市场领域单向隔离。它包含 Investigation/Run/Step、Source/Snapshot/Artifact/Evidence、Claim/Relation/Conflict/Validation、Gap/Timeline、Report/Review/Audit 以及逐调用录制的数据合同。Evidence 与 Claim 是不同类型和不同表。

Investigation schema 使用 `inv_` 表前缀并由 Alembic 管理；旧 `mp_runs` / `mp_events` 不会被首个 migration 删除：

```powershell
# SQLite local development
$env:MARKETPULSE_DATABASE_URL = "sqlite:///data/blackboard.db"
uv run alembic upgrade head

# PostgreSQL Compose target (password must be URL encoded)
$env:MARKETPULSE_DATABASE_URL = "postgresql+psycopg://marketpulse:<password>@127.0.0.1:55432/marketpulse"
uv run alembic upgrade head
```

`SourceSnapshotPersistence` 先把 raw/cleaned 内容写入 `BlobStoragePort` 并验证 hash，再提交数据库 metadata。数据库回滚最多留下完整 orphan blob，不会提交指向 partial/missing blob 的行。读取从 Source ID/Snapshot metadata 解析逻辑 BlobRef，重新校验内容，不返回 OS 路径。

```powershell
uv run pytest tests/unit/investigation tests/integration/investigation -q
```

## Phase 3 Acquisition / Recording Foundation

调查代码通过 `SearchPort`、`FetchPort`、`ModelPort` 调用外部能力。Live 组合为具体 provider → Recording adapter → Port；Replay 组合为 Replay adapter → 同一 Port。逐次请求和成功响应以 BlobRef 保存，fingerprint 包含 operation、规范化输入及 schema/prompt/config 版本；失败也记录分类，但没有完整响应的调用不可重放。Replay 只查精确匹配的成功录制，缺失返回 `REPLAY_CACHE_MISS`，损坏 Blob 返回 `BLOB_INTEGRITY_ERROR`，不联网补齐。

`SourceAcquisitionService` 将 Search → Source → Fetch → 原始 SourceSnapshot → 解析后的 DocumentArtifact 连通，不生成 Claim 或报告。解析器依据内容签名和 MIME 选择 HTML、纯文本或带文本层 PDF；扩展名只是提示。定位符引用持久化文本的精确字符区间，PDF 按可靠页面分别保存。扫描 PDF 保留 raw Snapshot、生成 `UNREADABLE_SOURCE` gap，不计入有效来源；部分 PDF 只让可靠页面参与取证。外部内容（包括官方来源）始终标记为不可信数据。

本阶段的 Live/Replay 纵向测试使用确定性 fixture，不依赖模型或真实网络；这不是完整 Investigation Replay，也不是 East Palestine 案例验收。PostgreSQL 集成测试由 [临时数据库 CI](.github/workflows/postgres-integration.yml) 实际运行，详见 [Phase 3 验收记录](docs/11-phase3-acquisition-recording-acceptance.md)。

```powershell
uv sync --extra dev --extra server
uv run pytest tests/unit/investigation tests/integration/investigation -m "not infrastructure" -q
# 真实 PostgreSQL 测试需要 MARKETPULSE_TEST_POSTGRES_URL；CI 自动提供临时数据库。
uv run pytest tests/integration/investigation/test_postgres_persistence.py -m infrastructure -q
```

当前已实现 Phase 4.1 Harness 运行骨架和五角色类型契约；真实五 Agent、Claim-Type-Aware ValidationPolicy、Report Writer、完整调查 Replay、Reviewer 认证及调查前端尚未实现。Phase 4.1 的假 Agent 测试不代表完整系统达到 Legacy Removal Gate。当前本地验证与 PostgreSQL CI 未运行的状态见 [Phase 4.1 独立验收记录](docs/12-phase4-1-harness-runtime-acceptance.md)。上面的市场 CLI/前端仅为迁移期回归基线，不是新调查系统入口。
