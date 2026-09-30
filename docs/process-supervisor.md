# 本地进程守护

在项目虚拟环境中启动：

```console
python -m marketpulse.investigation.operations.supervisor
```

默认子进程为当前 Python 解释器运行 `marketpulse.investigation.server`。工作目录和环境变量继承自守护进程；先配置数据库、Blob 路径和模型密钥。守护进程不记录命令参数或环境变量。Windows 子进程使用 `CREATE_NO_WINDOW`。

服务异常退出（包括未经守护进程请求的退出码 0）会重新启动。默认等待时间从 1 秒开始翻倍，上限 60 秒；子进程连续运行 300 秒后，退避重置。用户对守护进程按 Ctrl-C，或向守护进程发送 SIGTERM，则停止其子进程并退出，**不会重新启动**。Windows 的强制终止进程不等价于可捕获的 SIGTERM，应通过 Ctrl-C 或服务管理器的正常停止流程结束守护进程。

默认在启动 60 秒后，每 10 秒探测一次 `http://127.0.0.1:8000/api/health`，单次超时 3 秒，连续失败 3 次才重启。只接受本机 HTTP 地址；不使用代理、不跟随重定向。每次重启前等待原子进程退出，正常终止等待 15 秒，超时后强制结束并等待 5 秒。无法确认结束时返回非零退出码，禁止启动替代进程。操作仅作用于自己创建的子进程，不通过端口或名称结束其他进程。

可调整启动与探活参数：

```console
python -m marketpulse.investigation.operations.supervisor --startup-grace 90 --health-url http://127.0.0.1:8080/api/health --unhealthy-threshold 4
```

端口必须同时通过服务的 `INVESTIGATION_API_PORT` 环境变量配置。其他可用参数为 `--health-interval`、`--health-timeout`、`--terminate-timeout`、`--kill-timeout`、`--backoff-initial`、`--backoff-max` 和 `--backoff-reset-after`，单位均为秒。`--no-health-check` 仅根据进程退出重启。

需要替换子进程时，将完整参数列表放在 `--` 后；不执行 shell 展开：

```console
python -m marketpulse.investigation.operations.supervisor --no-health-check -- python -m marketpulse.investigation.server
```

此守护程序负责重新启动 API 进程，任务是否可以继续由应用的持久化恢复策略判断。无法确定费用的调用仍暂停等待确认，人工取消的调查不会自动恢复，预算也不会自动增加。

同一数据库只部署一套守护进程及 API，应用的数据库所有权检查是最终防线。同一 API 子进程只交给一个守护者。仓库 Compose 让本程序管理 API 子进程和 HTTP 健康重启，Docker restart 只负责整个容器退出后的启动；不要再在宿主机配置另一套 API 拉起循环。若使用 systemd，可让它运行本程序，或自行配置等效的健康监控。需要机器重启后启动时，将上述命令配置为操作系统的开机服务；本程序自身被强杀或机器断电后不能自行启动。数据库与 Blob 必须使用持久目录。

日志事件包括 `supervisor_child_started`、`supervisor_child_exited`、`supervisor_child_unhealthy`、`supervisor_restart_wait` 和 `supervisor_child_cleanup_failed`。探活证明 HTTP 服务能响应，任务是否停滞由应用内部看门狗检查。

本地故障演练测试：

```console
python -m pytest tests/integration/investigation/test_process_supervisor.py --basetemp=.codex-tmp/pytest-supervisor
```

测试运行真实短时子进程，验证强杀后获得新 PID、正常停止后不再拉起、退出码 0/非零重启、连续探活失败、退避中停止，以及清理超时处理。测试不调用模型或访问公网。
