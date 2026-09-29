# Search-Report：事件调查与证据验证

Python 3.11–3.13 / FastAPI 后端，Vue 3 / Vite 调查控制台。Planner、Researcher、Analyst、Verifier 通过持久化调查状态协作；报告把声明、经过验证的证据关系与原文定位关联起来。当前交付面向**本机可信单操作员笔试演示**。

## 两种运行方式

- **离线案例回放**：左侧“运行案例回放”使用仓库中的东巴勒斯坦事故归档来源和人工整理的声明—证据映射。无需模型密钥或外网；用于复现验证、门禁和报告。它不代表模型对陌生事件的调查质量。
- **联网调查**：首页输入主题，点击“开始调查”或按 Enter，自动创建档案并启动搜索、抓取、模型分析与验证。左侧保留历史调查，详情顶部也可输入新主题。需要配置 `DEEPSEEK_API_KEY`，可能产生调用费用。未配置时返回明确的 503 提示，不使用案例数据替代。

来源不足、验证失败或研究缺口会保留在结果中；运行结束并不意味着报告获准发布。前端读取实际运行状态和步骤，不生成模拟进度或预置结论。

LIVE 现支持四个互补研究员并行检索、并行抓取和分组语义验证。新运行默认预算为 240 次逻辑搜索、600 次抓取、480 次模型调用、200 万 Token、6 轮、60 分钟；这是上限，任务可因证据充分、无新增信息或其他预算先耗尽而提前停止。已有 `.env` 的显式值与历史运行预算不会自动改变。配置、代理适配和覆盖边界见 [并行调查说明](docs/PARALLEL_RESEARCH.md)。

新 LIVE 使用可复现的 BM25 分段召回；旧回放保留原版本策略，缺失记录明确失败。相同归档与上下文预算的比较命令、10 个事件的试点清单和 LIVE 指标导出见 [两层评测说明](docs/evaluation.md)。调用恢复与结果不明时的重试/费用边界见 [恢复说明](docs/model-call-recovery.md)。

## Docker 一键启动

需要 Docker Engine/Desktop 与 Compose v2。首次构建需要网络下载镜像和依赖。

```powershell
Copy-Item .env.example .env
# 已有 .env 时不要覆盖；离线回放可保持模型密钥为空。
docker compose up --build --wait
```

- 控制台：[http://localhost:3000](http://localhost:3000)
- API / OpenAPI：[http://localhost:8000/docs](http://localhost:8000/docs)
- 健康检查：[http://localhost:3000/api/health](http://localhost:3000/api/health)

Compose 启动 PostgreSQL、调查 API 和 Nginx 前端；Nginx 将 `/api` 代理到后端。数据库和归档正文分别保存在 `postgres-data`、`blob-data` 卷中。仅绑定本机回环地址；不要直接修改成公网监听。

```powershell
docker compose logs -f backend
docker compose down
# down 不删除数据卷。
```

联网研究：编辑 `.env` 填入模型密钥后执行 `docker compose up -d --force-recreate backend`。数据库密码应使用 URL 安全字符；修改已有数据卷的密码需要同步更新数据库角色密码，不能只改 `.env`。

## 本地开发启动

```powershell
uv sync --extra dev --extra web --extra server
Copy-Item .env.example .env
uv run search-report-api
```

在另一个终端：

```powershell
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

打开 [http://localhost:5173](http://localhost:5173)。Vite 将 `/api` 代理到 `127.0.0.1:8000`。不能直接双击 `frontend/index.html`；生产资源需要 `npm run build`。`marketpulse-api` 和 `web/` 是保留的旧市场研究入口，不是本交付的调查入口。

## 演示与验收路径

1. 打开控制台，点击“运行案例回放”。等待后端返回后查看实际步骤、预算、来源数量和模式标记。
2. 在“来源”检查发布时间、采集时间、可取证状态，点击归档正文。在“证据”检查摘录和精确定位。
3. 在“声明”检查验证状态、依据、支持证据与反证。在“冲突与缺口”检查未解决事项。
4. 打开“报告与审核”，点击 `[n]` 引用查看声明、摘录、来源和归档正文；导出 Markdown。导出不会绕过发布门禁。
5. 首页输入主题并点击“开始调查”：无密钥时应明确报错并保留输入；有密钥时自动进入 LIVE 运行。运行中可取消，刷新后可从左侧历史档案继续查看。启动请求失败时重试会检查已创建档案中的运行，避免同一页面内重复创建或重复启动。

核心 API：`POST /api/investigations` 创建，`POST /api/investigations/{id}/runs` 返回 202 和 `{run_id,status}`，`GET /api/runs/{id}` 与 `/steps` 读取进度。离线回放独立使用 `POST /api/cases/east-palestine-2023/replay`。全部接口以 `/docs` 为准。

## 中文阅读与详版报告

控制台的状态、来源类型、证据关系和审核标签使用中文；新联网调查要求模型用简体中文撰写声明、解释与后续建议，原文摘录、网址、标识及结构枚举保持不变。内置案例提供经核对的中文陈述与标题；未知的历史英文文本保留原文，不以未经核对的译文替换证据。

“报告”页可点击“生成新版报告”，从所选运行的既有证据生成新的中文详版，无需重新联网。旧报告、原文和哈希不覆盖。完整调查报告保留 17 节，增加关键发现摘要、来源与证据基础、分类验证边界、冲突及后续调查建议；失败、中断或受阻运行只能生成调查进展报告。新版重新执行引用和发布门禁，不继承旧版审核批准。

报告正文、目录和 Markdown 导出统一使用中文标题；引用附录保留来源原文。详版仍是受证据约束的规则写作，不额外调用模型扩写未知事实。规则评分在详细验证记录中保留，并明确不是事实成立的概率。

## 审核员配置

审核使用服务端配置的 Argon2id 密码哈希和 HttpOnly 会话 Cookie。未配置时仍可浏览调查，登录不可用。生成哈希与随机指纹密钥：

```powershell
uv run python -c "from argon2 import PasswordHasher; from getpass import getpass; print(PasswordHasher().hash(getpass('Reviewer password: ')))"
uv run python -c "import secrets; print(secrets.token_hex(32))"
```

将结果写入 `.env` 的 `REVIEWER_PASSWORD_HASH` 和 `REVIEW_RATE_LIMIT_FINGERPRINT_SECRET`。Compose `.env` 中哈希请用单引号包裹，避免 `$` 被插值；设置审核员 ID、显示名后重启后端。仅当报告有开放审核请求时才可提交决定；硬门禁不可由审核批准绕过。

## 检查

```powershell
uv run pytest tests/unit tests/integration -q
uv run ruff check src tests
uv run mypy src
cd frontend
npm test
npm run build
```

`.github/workflows/frontend-delivery.yml` 在干净检出后安装依赖、测试、构建，并启动 Compose 检查前端和 API 代理。联网模型质量需另行进行真实事件评测；离线测试通过不能替代该评测。

完整边界见 [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)，设计记录见 [ARCHITECTURE.md](ARCHITECTURE.md) 和 [docs/](docs/)。旧阶段文档属于历史记录，启动方式与当前能力以本 README 和实际测试为准。
