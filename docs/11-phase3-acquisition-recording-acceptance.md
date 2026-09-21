# Phase 3 — Acquisition / Recording Foundation 验收

日期：2026-09-21。范围仅为通用外部调用、逐调用录制与重放、文档摄取、Source Acquisition；不代表完整事件调查系统已交付。

## A–Q 对照

| 范围 | 实现与核验 |
| --- | --- |
| A Generic Ports | `SearchPort`、`FetchPort`、泛型 `ModelPort` 及冻结 typed request/result；Investigation 代码不导入旧市场领域。 |
| B Recording | `RecordingSearchAdapter`、`RecordingFetchAdapter`、`RecordingModelAdapter` 在 Port 边界保存规范化请求、完整响应及元数据；payload 进入内容寻址 Blob，调用元数据进入 `inv_recorded_*_calls`。 |
| C Replay | 三种 Replay adapter 按 operation + canonical fingerprint + schema/prompt/config 精确匹配；重复调用按录制顺序消费；无命中 `REPLAY_CACHE_MISS`，损坏 Blob `BLOB_INTEGRITY_ERROR`，无 Live fallback。 |
| D Failure | SUCCESS、TIMEOUT、PROVIDER_ERROR、RATE_LIMITED、INVALID_RESPONSE、SECURITY_BLOCKED、CANCELLED；失败可观察但不 replayable。 |
| E Parser Port | `DocumentParserPort` + registry，内容签名优先、MIME 辅助、URL 扩展名仅作 hint。 |
| F–G HTML/TXT | 稳定 UTF-8 归一化 artifact，精确字符定位符与持久化字节往返验证。 |
| H PDF | raw Snapshot 与逐页文本 artifact 分离，`PDF_TEXT_RANGE` 锚定特定可靠页。 |
| I–J PDF 可用性 | 全文、部分、扫描、无足够文本、损坏、加密、空内容等确定性分类；扫描 PDF 保留 raw、产生 `UNREADABLE_SOURCE` gap、不计有效来源；部分 PDF 只保留可靠页。 |
| K 外部内容边界 | HTML/TXT/PDF 一律 `UNTRUSTED`；基础可疑指令检测结果随 Snapshot provenance 持久化，官方来源不豁免。 |
| L–M Source Acquisition | 非 Agent 服务打通 Search → Source → Fetch → Snapshot → Artifact/Gap；`discovered/fetched/parsed/evidence_eligible/valid_for_statistics` 分离，未生成 Claim/Report。 |
| N PostgreSQL | GitHub Actions PostgreSQL 17 临时服务实跑 Alembic upgrade、repository roundtrip、JSONB/FK/index/status、append-only trigger、downgrade/re-upgrade/check；[运行 35606947209](https://github.com/haoyanghe89-hub/Search-Report/actions/runs/35606947209) 的结论为 success。 |
| O–P 纵向与测试 | Live fixture 产生真实 RecordedToolCall/BlobRef/Snapshot/Artifact/精确 locator；新 Replay Run 在没有 Live adapter 的组合中重新摄取，不复制 Live Snapshot；缺失及损坏录制的负测存在。 |
| Q 案例准备 | `case_data/east_palestine_2023/manifest.json` 与目录骨架。NTSB RIR-24-05 corrected PDF 经只读 HTTP/文本层探测：200、PDF、216 页、首面可提取文字；尚未存为不可变案例 fixture，也没有写死报告/结论。 |

## 验证记录

| 检查 | 结果 |
| --- | --- |
| Investigation 定向测试 | `49 passed, 1 deselected`（PostgreSQL 需 CI 服务） |
| 全量离线测试 | `119 passed, 1 skipped, 5 deselected`；跳过项为 Windows 无特权 symlink 假设 |
| Ruff | `All checks passed!`，覆盖 `src tests migrations` |
| mypy strict | `Success: no issues found in 73 source files` |
| `uv build` | wheel 与 sdist 成功；复查归档包含新 migration，不包含 `.uv-cache`/临时测试目录 |
| 真实 PostgreSQL | 上述 GitHub Actions 临时 PostgreSQL 集成 job 为 success；本机未声明运行 PostgreSQL |

测试命令：

```powershell
.venv\Scripts\python.exe -m pytest -q -m "not live and not infrastructure" -p no:cacheprovider --basetemp=.phase3-pytest-final
.venv\Scripts\python.exe -m ruff check src tests migrations
.venv\Scripts\python.exe -m mypy src/marketpulse --strict
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'; uv build
```

## 本阶段修复与限制

- HTTP Fetch 改为流式读取并在实际下载过程中执行大小上限，暂时性 HTTP/传输故障限次退避重试；每次重定向重新校验目标。
- 发现本地构建缓存曾误入 sdist，已显式排除并重新构建验证。
- 当前只有 call-level Replay 和 acquisition 纵向 Replay；完整 Harness 状态流转、Evidence/Claim/Validation/Report 重新执行留待后续阶段。
- 案例 manifest 目前只有官方 PDF 候选元数据，录制计数为零；East Palestine Live/Replay 案例验收尚未开始。
- V1 PDF 不做 OCR，扫描件不能取证。外部内容注入检测是基础边界，不等同于完整 Agent 提示词防护。
- DNS 公网地址检查与 HTTP 客户端连接解析之间仍可能出现 DNS rebinding 竞态；公开网络部署前需采用固定解析/出口代理等强化措施。当前产品边界仍是本地可信单操作者 Demo。
- 旧 MarketPulse CLI/API/前端继续作为回归基线，尚未达到 Legacy Removal Gate，不能把它误认为调查产品入口。
