# Phase 1a Blob Storage 验收 — 2026-09-21

本轮完成 Phase 0 和 Phase 1a，不代表全部 Phase 1、Legacy Removal Gate 或完整 Investigation Platform 完成。基线见 `9aa8ae1` 和 [Phase 0 记录](08-phase0-baseline.md)。源码仍在同一工程/包内，没有第二套项目。

## 已交付

- `infrastructure/storage/models.py`：不可变 BlobRef、StoredBlob 及 BLOB_NOT_FOUND/BLOB_INTEGRITY_ERROR/BLOB_IO_ERROR；逻辑引用拒绝路径输入。
- `ports.py`：BlobStoragePort，同步二进制 I/O，可注入未来应用服务。
- `local.py`：SHA-256 内容寻址、stream 分块写入、fsync/重读校验、同卷 no-clobber 原子发布、并发去重；读取先验证 hash；没有覆盖/删除接口。
- `test_blob_storage.py`：持久化重开、同/不同/空内容、stream、逻辑引用、篡改/缺失/非文件对象、写入/同步/发布失败、并发、目录迁移、子进程中途退出与 Windows 路径回归。
- `test_infrastructure_boundary.py`：AST 检查通用基础设施不引用 market-specific domain/services/config/errors。
- `ARCHITECTURE.md`、迁移分类/门禁、执行计划、基线及本记录；README 标明当前能力与目标部署边界。

## 新鲜验证结果

| 验证 | 结果 |
| --- | --- |
| 新增存储/边界用例 | 27 passed，1 skipped |
| 全量 Python 离线回归 | 70 passed，3 skipped，2 live deselected |
| Ruff src/tests | passed |
| Strict mypy src | 37 files passed |
| uv build | wheel + sdist passed |
| wheel 内容检查 | 5 个 infrastructure Python 模块均存在 |
| 前端 baseline | 2 tests passed、build passed；lint 0 errors/3 既有 warnings；本轮未改前端 |

运行命令：

```powershell
.venv\Scripts\python.exe -m pytest -m "not live" -q -p no:cacheprovider --basetemp=.codex-tmp/phase1-full
.venv\Scripts\ruff.exe check src tests
.venv\Scripts\mypy.exe src
uv build
```

3 个 skipped：未配置专用 PostgreSQL/Redis 测试服务，以及 Windows 当前不假定非特权符号链接创建能力。Live 本轮未执行，未调用模型。结果为本机 Windows 验证；Linux/容器与断电耐久性尚未实测。

## 调试证据

先加入契约测试，确认新增模块未实现时 ModuleNotFoundError；实现后通过故障注入发现 Windows 并发 mkdir 时 `Path.resolve()` 会偶发保留 `\\?\` 前缀，造成相同路径误判为越界。记录原始解析值确认原因后，对 DOS/UNC 等价路径统一表示；保留显式 extended-path 回归测试和 12 次/6 线程并发重复写入测试。

子进程测试在 stream 只写完一段时以 `os._exit(77)` 退出。重开 store 后没有可正常读取的 partial final blob；同一内容随后完整写入可读。异常写入/同步/发布失败均不返回成功引用。已存在 hash 若内容被篡改，重复 put 会报错，不修补/覆盖它。

## 明确未完成与限制

PostgreSQL Snapshot/recording 元数据、事务失败后引用约束、DocumentParser、Evidence/Claim、case fixture、Replay、ReportReleasePolicy、Reviewer auth、RunExecutor、恢复及 Investigation Console 尚未接入。BlobPort 的独立测试不能代替这些集成验收。

适配器要求可信本地 volume 及硬链接能力；不支持时显式失败，不使用非原子降级。目录可移植，BlobRef 不依赖机器路径；不声称防御拥有本机文件系统写权限的恶意并发修改者。Windows 不使用不可移植的目录 fsync，不承诺断电/磁盘损坏恢复；后续 Linux Docker 实测需验证目录同步路径。无自动 orphan/temp GC，磁盘配额与 ingest 体积限制由后续受控采集层设置。

后续优先级：通用调用录制与 provider ports -> PostgreSQL 领域 migrations/repositories + Snapshot/parser/locator -> 五角色/Harness/ValidationPolicy，再完成 Live/Replay/Console 的 Legacy Removal Gate。
