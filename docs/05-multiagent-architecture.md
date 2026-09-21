# MarketPulse 四智能体协作架构

## 实际采用的方案

采用主 Agent 调度的共享黑板，四个逻辑 Agent 在同一 Python 进程运行。
角色之间通过结构化结果及已提交的黑板状态交接，没有彼此发送聊天消息，
也没有四套独立的 HTTP 服务。每个角色拥有自己的指令、输入上下文和输出契约，
并真实调用 DeepSeek。主 Agent 的复核决定是否继续补查；执行器负责落实和限制决定。

| 角色 | 模型的工作 | Harness 负责的工作 | 写回黑板 |
|---|---|---|---|
| Master | 制订研究计划；判断证据缺口；选择补查或交付 | 分配任务、限制路由与轮数 | plan、reviews |
| Search | 根据计划或缺口选择新查询 | 调用搜索、抓取、正文抽取；去重与预算 | search_tasks、evidence、coverage |
| Analyst | 基于带来源证据分析市场、竞品与定价 | 验证引用 ID；覆盖不足时限制置信度 | analysis |
| Reporter | 撰写摘要、理由和下一步行动 | 校验引用；保留结构化事实、建议和置信度；原子写报告 | draft、report_path |

流程：Master 规划 → Search 取证 → Analyst 分析 → Master 复核。
Master 选择 research 时带 gaps 回到 Search；选择 report 时进入质量检查和 Reporter。
默认最多两轮研究。超过轮数、搜索、页面或时间限制，即使模型要求补查也不能继续；
未解决问题进入报告局限性。各角色的网络工具不由模型直接执行，执行器按经过验证的
结构化请求调用既有适配器。这是受约束的多智能体工作流，而不是任意自由对话的集群。

## 黑板数据与交接协议

`BlackboardState` 包括：

- `run_id`：隔离不同研究任务；`version`：乐观并发版本；`schema_version`：数据格式版本。
- `status`：running/completed/failed/cancelled；`active_agent` 和 `phase`：当前职责与阶段。
- `plan`、`search_tasks`、`evidence`、`coverage`、`analysis`、`reviews`、`draft`。
- `executed_queries`、`attempted_urls`：避免轮次之间重复工作。
- `budget`：查询和页面消耗、上次提交时的剩余时间；`warnings`：覆盖缺口。
- `report_path`、`error_category`、`updated_at`：产物、失败类别和时间。

调用角色之前，执行器从已提交黑板中抽取所需字段组装 JSON。不会把所有历史对话、
环境变量、数据库连接串或 API key 发送给角色。网络材料被明确标记为证据，不是指令。

角色返回后：Pydantic 验证结构 → 业务层验证引用/预算等条件 → 一个 SQL 事务更新快照
并插入事件 → 提交 → 可选 Redis 通知 → 重新加载黑板 → 派发下一个角色。

`mp_runs` 保存每个任务的当前 JSON 快照与版本。
`mp_events` 保存带 run_id、version、actor、event、phase、created_at 的事件元数据。
它是可追溯的执行时间线，不是保存每次完整快照的事件溯源系统。

版本更新使用条件 `run_id = expected_run AND version = expected_version`。
如果另一个写入者已经更新版本，当前写入失败，不能覆盖较新的结果。
快照更新与事件插入处于同一个事务，一起提交或一起回滚。

## PostgreSQL + Redis，还是消息总线 + DB + 对象存储？

| 组件 | 本次实现 | 用途与边界 |
|---|---|---|
| SQLite | 本机默认、实际验证 | 无需额外服务的持久化黑板 |
| PostgreSQL | 已实现 SQLAlchemy 后端及部署配置 | 服务端共享黑板和事务；需要启动服务并配置 DSN |
| Redis | 已实现可选 Pub/Sub 通知 | 只传提交后的事件元数据；不是任务队列 |
| Kafka / Pulsar / NATS | 未引入 | 目前无需独立 worker 的跨进程任务传输 |
| Object Storage | 未引入 | 当前保存文本证据片段和本地 Markdown，没有大图像/视频资产需求 |

如果一定在题目中的两套方案中选择，服务端配置接近 PostgreSQL + Redis，
但 Redis 在此是可有可无的进度通知层。真正的角色派发仍由进程内执行器完成。
切换数据库不会自动把应用变成分布式系统。

Redis channel：`marketpulse:runs:{run_id}`，消息只含事件元数据。
订阅者收到后按 run_id/version 查询 SQL。通知超时或 Redis 故障不会撤销已经提交的结果。
Pub/Sub 断线期间会丢消息；这里没有 outbox、消费组、消息重放、任务租约或 exactly-once 保证。
完整黑板与事件查询接口用于重新同步。因此 Redis 丢通知不会导致数据库丢任务状态。

## 运行方式

在项目根目录运行：

```powershell
uv sync --extra dev --extra web
uv run marketpulse --competitors 3 "AI meeting notes tools"
uv run marketpulse-api
```

本机 `.env` 保存 DeepSeek key，默认黑板为 `sqlite:///data/blackboard.db`。
报告保留在 `reports/`。进程环境变量优先于 `.env`，因此已有旧的
`DEEPSEEK_API_KEY` 进程变量需要移除或更新，才能使用文件中的新值。

服务端数据库模式：

1. 安装 Docker，并在 `.env` 设置 `MARKETPULSE_PG_PASSWORD`。
2. `docker compose up -d`，启动 PostgreSQL 和 Redis；端口仅绑定本机。
3. `uv sync --extra dev --extra web --extra server`。
4. 设置数据库与 Redis 配置，重启 API：

```dotenv
MARKETPULSE_DATABASE_URL=postgresql+psycopg://marketpulse:URL_ENCODED_PASSWORD@127.0.0.1:55432/marketpulse
MARKETPULSE_REDIS_URL=redis://127.0.0.1:56379/0
```

`URL_ENCODED_PASSWORD` 必须替换成实际密码的 URL 编码形式。
这是本机开发用 Compose，不是已经配置认证、TLS、备份和迁移管理的生产部署。
不要将无认证的开发 API 或 Redis 直接暴露到公网。

## 观察与验证

`POST /api/reports` 保持原有输入结构，返回中新增 agent_events、state_version、storage_backend。
`GET /api/runs/{run_id}` 读取快照；
`GET /api/runs/{run_id}/events?after_version=N` 读取 N 之后的事件。
这些读取接口不需要调用大模型。现有前端继续使用原有报告响应字段。

```powershell
uv run pytest -m "not live" -q
uv run ruff check src tests
uv run mypy src
```

需要专用测试服务的验证（使用唯一测试 run_id，结束时仅清理本次测试行）：

```powershell
$env:MARKETPULSE_TEST_POSTGRES_URL = "postgresql+psycopg://user:password@localhost:55432/test_db"
$env:MARKETPULSE_TEST_REDIS_URL = "redis://localhost:56379/0"
uv run pytest tests/integration/test_infrastructure.py -m infrastructure -q
```

未配置时基础设施测试明确跳过，不能用 SQLite 测试通过来宣称已经完成 PostgreSQL/Redis 联调。

## 当前可靠性边界

失败和取消会保存最后已提交状态及错误类别。强制终止进程可能留下 running 状态；
尚未实现跨进程恢复、失败任务自动重派、长任务租约或后台分布式消费。
模型调用可能因为校验失败重试，无法保证外部 API 只收费一次。
当前单次模型输出最多尝试两次；错误不会把 provider 的原始异常正文写入黑板。

引用存在性和结构可验证，引用是否真的支持语义仍需要评测或人工复核。
模型生成的摘要仍可能出错；本次没有宣称解决幻觉或实现概率校准。
原有 source_type 分类启发式、正文提取和检索相关性也保留其原有局限。
这次改造维持市场调研范围，不增加军事目标定位或多模态识别功能。

代码定位：`agents/team.py` 定义四个角色，`agents/prompts.py` 定义角色指令，
`services/coordinator.py` 是 harness，`services/blackboard.py` 是事务黑板，
`services/notifications.py` 是可选通知，`workflow.py` 管理生命周期。
