# Phase 0 regression baseline — 2026-09-21

原目录无 Git 提交。选取源码、测试、web、依赖锁、示例配置和既有文档建立首次基线 `9aa8ae1`，分支 main。随后在同一目录切换 `feat/investigation-foundation`。远程为用户指定的 Search-Report 空仓库。

未跟踪本机 `.env`、运行 DB、日志、报告、缓存、技能目录、根目录个人调试脚本与操作记录。未覆盖或删除它们。Git 没有已配置作者，因此本次自动化提交使用命令级 `Codex <codex@localhost>`，不改全局 Git 配置。

## 修改前执行结果

| 检查 | 实际结果 |
| --- | --- |
| Python pytest `-m "not live"` | 43 passed，2 skipped，2 deselected |
| Ruff `check src tests` | passed |
| Mypy `src` | 32 source files passed |
| 前端 `npm test` | 2 passed |
| 前端 `npm run lint` | 0 errors；原有 3 条 UI Fast Refresh 导出 warnings |
| 前端 `npm run build` | passed |
| CLI `python -m marketpulse.cli --help` | exit 0 |
| `uv build` | wheel + sdist passed |
| PostgreSQL/Redis 实际服务 | 未配置专用测试服务，测试明确 skipped |
| Live DeepSeek/search | 本轮未执行，未花费真实模型调用预算 |

Python 可复现命令（避免本机旧缓存 ACL）：

```powershell
.venv\Scripts\python.exe -m pytest -m "not live" -q -p no:cacheprovider --basetemp=.codex-tmp/phase0-baseline
.venv\Scripts\ruff.exe check src tests
.venv\Scripts\mypy.exe src
uv build
```

第一次 pytest 在 tmp_path setup 的 `.pytest-work` 遇 WinError 5，全部测试尚未进入业务执行。检查目录 ACL 后，改用 `.codex-tmp/phase0-baseline` 并禁用旧 cacheprovider，43 项通过；未为这个环境问题改业务代码。

第一次 uv build 因 sandbox 无法访问用户 uv cache 失败；无隔离尝试因 venv 未安装 hatchling 失败。正常 `uv build` 在允许访问缓存/声明的隔离构建依赖后成功。pyproject 已正确声明 hatchling，无需改依赖配置。不能将两次环境失败或旧验收文档当成当前源码失败/通过的证据。

## 基线保护

后续每个可交付单元重跑 Python 离线测试与静态检查。仅前端/构建契约变化时重复前端检查；打包变更需 wheel 检查。现有市场端到端测试在 Legacy Removal Gate 前保留。通用基础设施新增 dependency-boundary 测试，防止导入旧 market 领域。
