# 配套备份与恢复演练

备份命令先获得一致的数据库快照，再复制该快照实际引用的不可变 Blob。完成前逐个校验 SHA-256，
最后原子写入 `manifest.json`。没有完整清单的目录是未完成备份，不能恢复；失败目录保留供检查。
SQLite 使用在线 backup API，不复制正在写入的主文件或遗漏 WAL。PostgreSQL 使用导出的同一事务
快照执行 `pg_dump` 和引用扫描。备份期间不得删除或改写已有 Blob。

## SQLite 本机示例

在仓库目录、已安装依赖的虚拟环境中运行。数据库地址通过环境变量提供，工具不会自动读取 `.env`。
PowerShell 示例使用独立的新目录名，重复执行请换名字：

```powershell
$env:MARKETPULSE_DATABASE_URL = 'sqlite:///data/blackboard.db'
python -m marketpulse.investigation.operations.backup_cli backup --blob-root data/investigation-blobs --destination backups/backup-20260930-01
python -m marketpulse.investigation.operations.backup_cli verify --archive backups/backup-20260930-01
python -m marketpulse.investigation.operations.backup_cli drill --archive backups/backup-20260930-01 --destination restore-drills/drill-20260930-01
```

`drill` 真正恢复到全新目录，检查数据库完整性、外键和 Blob 引用闭合；不启动 API、搜索或模型。
成功后产生 `restore-report.json`，其中 `executor_started` 为 false。`restore` 使用同样的安全恢复流程。
恢复拒绝已有目标目录，不能覆盖生产库、原备份或生产 Blob；拒绝路径穿越、符号链接、额外文件、
缺失 Blob 和哈希不匹配。归档校验是完整性检查，不是签名认证，只恢复自己控制的可信备份。

## PostgreSQL / Compose

本机需要与数据库匹配的 `pg_dump` / `pg_restore` 版本，或使用仓库 `Dockerfile.ops`（PostgreSQL 17
客户端）。凭据通过进程环境传入，不出现在工具参数或备份清单中。

```console
docker compose --profile ops build ops
docker compose --profile ops run --rm ops backup --blob-root /data/blobs --destination /backups/backup-20260930-01
docker compose --profile ops run --rm ops verify --archive /backups/backup-20260930-01
docker compose --profile ops run --rm ops drill --archive /backups/backup-20260930-01 --destination /restore-drills/drill-20260930-01 --postgres-admin-url-env MARKETPULSE_DATABASE_URL
```

PostgreSQL 演练需要创建数据库权限，会创建全新随机命名 `sr_restore_<随机串>` 数据库，绝不覆盖
环境变量指定的数据库。`restore-target.json` 记录目标名称；失败时也保留新库和目录供检查，不自动删除。
`verify` 可检查 PostgreSQL 转储文件和 Blob 的哈希，但数据库引用及约束必须经实际 `drill` 验证。
`--timeout 600` 限制 SQLite 快照和 PostgreSQL 外部命令；不是整个大型 Blob 复制过程的总时限。

## 恢复后先核对，再恢复执行

恢复产生 `blobs/.restore-quarantine.json`。API 看到这个标记会拒绝继续历史运行，避免旧备份缺失
之后已经计费的调用而自动重复执行。演练不会移除标记，也不自动打开线上恢复。
清单 `created_at` 记录快照开始前的时间，作为保守的对账起点，覆盖快照和 Blob 复制期间发生的调用。

真正切换时：停止原服务，核对备份时间之后的运行及供应商调用/账单，确认缺失记录和重试策略；
不能核对的历史运行保持停止。仅在完成核对后，由运维对这份恢复卷解除隔离标记，再将数据库和
Blob 配套切换并重启。未经核对的恢复卷也不允许重新备份，避免丢失这一隔离信息。
历史缺失意图不能靠模型调用去重凭空补齐，不能把恢复成功视为费用恰好一次执行的保证。

## 定期执行与保留

上面的备份和演练命令可交给 Windows 任务计划程序或 Linux timer，使用每次唯一的目标目录。
备份频率根据可接受的数据损失窗口决定；演练定期跑到独立目标，记录退出码和 `restore-report.json`。
生产备份应复制到与服务数据不同的存储故障域。此版本不会自动删除旧备份或演练数据库；保留与清理
由部署方配置，也没有替你安装主机计划任务或修改已有数据库。

本轮已实测 SQLite 真实快照、CLI 恢复演练、调用意图/检查点/预算保留、损坏与不完整备份拒绝。
Windows 不承诺目录 fsync，断电/存储损坏仍需基础设施保障。Docker/PostgreSQL 本机不可用，
提供实现与演练入口，但未宣称已完成 PostgreSQL 或容器运行验收。
