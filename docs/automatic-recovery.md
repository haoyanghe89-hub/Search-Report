# 运行守护与自动恢复

本版本继续面向可信本地/内网的单 worker 部署，不新增登录或租户系统。
普通服务中断后，原数据库和 Blob 完整保留时，可以自动继续原运行。

## 默认行为

- 每 15 秒检查一次；自动恢复仅限 INTERRUPTED 和可重试 FAILED 的 LIVE v4 运行。
- 复用已有恢复检查：版本、执行配置、输入/输出检查点、预算、步骤重试性、无有效执行器占用。
- 未知模型调用必须由用户逐项确认；自动恢复不会批准未知结果、增加预算、启动回放联网，或重启人工取消的运行。
- 自动恢复初次等待 15 秒，随后退避翻倍、最高 3600 秒；每个运行最多 3 次自动恢复，次数保存在审计记录中，重启不清零。
- 每次自动恢复记录 `RUN_RESUMED`，actor 为 SYSTEM，`automatic=true`。手动恢复仍为 HUMAN 类型，未新增身份认证。
- 连续 90 秒没有步骤心跳，或单步骤超过 900 秒，记录停滞告警并尝试取消。只有确认本地执行任务停止后才允许后续恢复；取消无法完成则 readiness 失败，交由进程守护重启。
- 心跳在工作中刷新，因此“模型思考中”不因缺少页面文字更新被当成故障。步骤总时限提供额外的进度检查。
- 旧备份恢复到新卷时默认隔离历史续跑，详见[配套备份说明](paired-backup.md)。

配置见 `.env.example`：`INVESTIGATION_AUTO_RESUME`、`INVESTIGATION_RECOVERY_SCAN_SECONDS`、
`INVESTIGATION_AUTO_RESUME_MAX_ATTEMPTS`、`INVESTIGATION_AUTO_RESUME_BACKOFF_SECONDS`、
`INVESTIGATION_STALL_HEARTBEAT_SECONDS` 和 `INVESTIGATION_STALL_STEP_SECONDS`。设置改变后重启服务。
自动恢复使用原预算；被 BUDGET_EXHAUSTED 阻止的运行仍需手动追加额度。

## 启动与守护

本机：`python -m marketpulse.investigation.operations.supervisor`。
配置和停止方式见[进程守护说明](process-supervisor.md)。

Compose：`docker compose up --build -d`。数据库、前端和后端配置 `restart: unless-stopped`；
后端内部的守护进程只管理自己的 API 子进程，监测 `/api/health`，不按名称或端口杀进程。
Docker 管理容器退出；健康检查不健康本身不会触发 Docker restart，所以 HTTP 故障由子进程守护处理。
人工 `docker compose stop` 后保持停止；机器重启还需要 Docker 引擎自身的开机启动配置。

同一 SQLite 数据库使用操作系统文件锁，PostgreSQL 使用会话 advisory lock，在数据库迁移和启动时
标记中断之前获得独占权。第二个实例拒绝启动，进程退出释放所有权。不要删除或替换在线数据库旁的
`.server.lock` 文件。该限制是单实例保护，不是分布式 fencing 或多节点高可用；共享文件系统的锁语义
以及 PostgreSQL 网络分区场景没有作为多 worker 环境验收。

## 告警与健康

`GET /api/ops/status` 返回当前告警、自动恢复配置状态和守护健康。页面顶部展示需要处理的运行，
可跳转到调查；每 15 秒刷新一次。相同运行/状态版本/告警码仅写一次 `OPS_ALERT`，重启不重复写，
运行进入新状态后旧告警退出当前列表，审计历史保留。日志只打印运行 ID、错误分类与状态版本。
当前查看的失败/中断 LIVE 运行会轻量轮询状态，发现自动恢复后重新跟进进度，无需手动刷新；
等待期间不会反复加载报告或清空费用确认表单。

`GET /api/health` 在数据库、所有权和恢复循环可用时成功；循环停止、检查失败或执行器无法停止时
返回 503。失联或整机断电时应用无法自行发通知，应由外部监控探测这个端点并接入运维通知渠道。
本轮没有配置或发送邮件、Webhook、钉钉通知；告警出口是控制台、持久化审计、日志和状态 API。

## 验证与边界

故障测试使用离线端口：真实 API 进程在模型响应落盘后立即退出，守护拉起新 API，原任务自动继续，
已保存的规划调用只发生一次。另有取消、未知结果、重试上限持久化、退避、停滞、第二实例拒绝、
守护健康失败和备份恢复测试。不调用付费模型，不等同于供应商端 exactly-once 或长期 SLA 验收。

自动恢复提升“有记录可用时”的可用性。供应商已计费但本地结果不明时仍暂停；这是有意保留的费用边界。
Docker/Linux/PostgreSQL 部署需按所提供命令在目标环境演练；本机验证覆盖 Windows、SQLite 和真实子进程。
CI 已加入离线案例入库后的 PostgreSQL/Blob 备份、校验和隔离恢复，并保存恢复报告；以 CI 实际结果为准。

2026-09-30 本地验收：离线 pytest 361 passed、3 skipped、7 deselected；前端 30 项通过；
Ruff、mypy（148 个源文件）及前端生产构建通过。3 项跳过是 Windows 符号链接权限和 POSIX 信号测试，
未运行项为真实联网/基础设施测试。Windows 仓库路径较长时使用短的 pytest 临时目录，避免 MAX_PATH 限制。

参考：[Docker 自动启动与 restart 策略](https://docs.docker.com/engine/containers/start-containers-automatically/)。
