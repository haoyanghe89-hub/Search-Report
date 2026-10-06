# 任务 I 第 3–5 项续交付：532 项回归通过，真实 E2E 被余额不足阻断

**结论：第 3–5 项代码与回归已落地，最终后端 532 passed，Ruff/编译/导入/diff 全绿；一次新真实 E2E 在首次模型调用返回 HTTP 402 余额不足，PLAN/BLOCKED。结论性可发布报告目标未验收通过，不能用单测 PROBABLE 正例替代真实确认结果。**

本文件记录本次继续实施，不覆盖 `v5-taskI-final-report.md` 中上一轮真实记录。本次未改前端、HTTP schema、历史库或原始档案，也未降低证据质量门。

## 3. 有依据的限定补全与官方文档校准

- `agents/contracts.py` / `agents/supplements.py`：在原 time/definition/methodology/provenance 基础上增加 value/unit/scope/speaker。逐字值必须出现在本声明关联 Evidence 的 quote 中；同 Evidence 必须对完整限定后的声明给出 ENTAILS。禁止覆盖旧字段、选择竞争值、根据发布日期猜测评测日期。entity/time/scope 保留，验证与补全继续原子提交并审计。
- `services/source_acquisition.py`：归档官方一手 HTML 中明确标注发布者或 “our report/evaluation” 的 PDF 链接，保留 anchor/publication_statement。普通外部引用不能证明 PDF 的官方一手身份。官方重定向链继续保留。
- `services/publisher_provenance.py`：分析/验证使用可重建、同次运行的出版元数据视图。双方原始归档 hash 必须有效；重定向必须同 URL、同 PDF hash；HTML 必须有明确发布声明且先于 PDF 抓取。相互竞争的出版者拒绝校准。只按云存储 host、跨 run、不同版本 PDF、普通外链或二手页面都不能校准。
- 校准依据写入 snapshot.provenance 的归档发布边；推导 proof 写入持久化 validation_basis_payload.special_checks，含发布者 source/snapshot ID、hash、URL、关系。原始 Source 与档案不改写，不能把推导视图误称为数据库 Source 标记修改。
- 质量仍按原组件计算，没有全局评分保底。出版页与 PDF 按同 issuer 合并家族，不制造额外独立来源。裸 cloud PDF 无证据链仍不认定官方。

## 4. PROBABLE 与结构字段对齐

- `validation/profiles.py` 修复根字段读取与持久化分组不一致：数量/单位/时间/范围/定义/方法、speaker、归属边界、reasoning_basis/uncertainty 都读取明确存储的分组或一致的根投影；两处竞争值当作不可确定，不任选一项。
- VERIFIED 仍满足完整 profile、精确语义、独立来源及冲突条件；PROBABLE 要求完整 ENTAILS、至少两个独立家族、至少两项可信来源（≥0.5）、无强反证或未解冲突，仅接受各类型明列的次要缺口。量化核心 value/unit/time/scope/definition 不能豁免，不能平均竞争数字。分析推断最高 PROBABLE。
- QUANTITATIVE / STATEMENT / ATTRIBUTION / ANALYTIC_INFERENCE 同时覆盖平铺与实际持久化分组；PARTIAL-only、单族和竞争数值仍不能获得确认。
- `agents/prompts.py` v8 明确补全字段、分组与证据边界；没有将 reasoning_content 当成答案或引入推测事实。

## 5. 网络韧性核对

- 复用任务 H 的 harness 有界重试：只读推理最多 3 次重试、总 4 次 dispatch，默认退避 1/2/4 秒；未知结果重新 durable prepare/dispatch 并标记 ALLOW_POSSIBLE_DUPLICATE_CHARGE。持久化重试上限与阶段/总 token 预算仍有效。
- 超时、连接重置/中断、未知结果、429/5xx 可重试；400/402 不重试；402 明确余额不足。有界耗尽受控 BLOCKED，保留材料。连接 15 秒、读取 120 秒，客户端复用，SDK 隐式重试关闭。
- 搜索和抓取已有多后端退避/冷却、源级错误跳过，未重复添加额外重试层。没有修改业务 HTTP 状态机或质量门。

## 已执行的检查与修复

- 定向限定/质量/采集/原子性/重试：74 passed（补充发布 HTML UoW 用例后采集组 16 passed；计数相互重叠，不相加）。
- 首次完整运行 530 passed / 2 failed / 3 skipped / 7 deselected。两处均是离线回放指纹回归：新增模型出处用了 run-local snapshot_id。已改稳定 SNAP-rawhash，并从模型出版 proof 投影去除运行内 ID；审计仍保留真实 ID。两个失败用例单独重新通过。
- 修复后的全量 **532 passed / 3 skipped / 7 deselected，退出码 0，206.85 秒**；JUnit 路径 `reports/taski/i4-full-fixed.xml`。3 skipped 是 Windows 符号链接/POSIX SIGTERM 能力限制；7 deselected 为 live/infrastructure 标记，不能计为通过。真实 E2E 单独执行。
- Ruff 全仓 src/tests 与审计/E2E 脚本、compileall、核心导入、git diff --check 通过。
- OpenAPI SHA256 仍为 `8a7ac4bb65c741aa7c54002ec9c12a1f75963da552e04e709547928429bdaf9e`，与基线相同；未改前端。

## 本次改动文件

`src/marketpulse/investigation/agents/contracts.py`、`agents/supplements.py`、`agents/prompts.py`、`services/source_acquisition.py`、新增 `services/publisher_provenance.py`、`feedback/context.py`、`feedback/orchestrator.py`、`validation/profiles.py`、`validation/quality.py`、`validation/policy.py`；`tests/unit/investigation/test_qualifier_supplements.py`、`test_validation_core.py`；`tests/integration/investigation/test_source_acquisition.py`；本报告及 `docs/taski/progress.md`。

工作区中的其他前端/历史后端改动保留，未重置、提交或覆盖。

## 同题目真实 E2E 结果与交付边界

- 仅新建一次：`RUN-LIVE-b178a218f9e84f09`，原问题复制自 `RUN-LIVE-434153bec43c405f`；隔离库 `reports/taski/i4-live-20261002/live.db`，配置/进度/最终结果同目录，历史库只读。
- UTC 2026-10-02 13:08:16.896 启动，13:08:18.323 记录终态 **PLAN / BLOCKED**。错误录签 `provider_diagnostics={category:http_error,http_status:402}`；原因 `MODEL_INSUFFICIENT_BALANCE：模型服务余额不足，请充值后重试。`。
- 常规模型实际路由 `deepseek-flash`，prompt `investigation-prompts-zh-v8:planner.plan`；1 次模型 dispatch、0 token 已计用量、0 search、0 fetch、0 来源/证据/声明、0 VERIFIED/PROBABLE。没有进入关键推理或验证阶段，不能宣称 v4-pro 或分级已在本轮真实数据上完成验收。
- 未对 402 重试，未知结果自动重试 intent 为 0；没有第二次付费调查、没有充值、没有增加预算。运行进程已正常退出（退出码 0 表示受控结束，不表示调查成功）。
- 状态报告 `RPT-3e63ed7f3794` / `INVESTIGATION_STATUS` / `RESTRICTED`，不是可发布结论报告。
- 完整只读终态审计：`docs/taski/i4-terminal-audit.json`；原始终态：`reports/taski/i4-live-20261002/final.json`。报告如实保留余额限制，旧轮材料仍在原隔离目录，不因新轮缺材料删除旧材料。

## 最终命令与仍存限制

完整回归命令：

```text
.venv/Scripts/python.exe -m pytest -m "not live and not infrastructure" -q --basetemp reports/taski/i4-full-fixed-20261002 -p no:cacheprovider --junitxml=reports/taski/i4-full-fixed.xml
.venv/Scripts/python.exe -m ruff check src tests scripts/audit_taski_e2e.py scripts/verify_live_token_budget.py
.venv/Scripts/python.exe -m compileall -q src
git diff --check
```

均退出码 0；核心导入与 OpenAPI 哈希核对也通过。1 条 Starlette/AnyIO deprecated alias 警告未做无关依赖升级；既有 LF/CRLF 提示不是 diff 空白错误。

- 余额恢复前无法继续真实模型验收；不能声称现已出现真实 VERIFIED/PROBABLE 或 report 可发布。
- PDF 图像表格仍不做 OCR，缺文本保持显式缺口；官方发布身份不证明客观能力独立成立，同发行方只有一个独立家族。
- 无明确日期/定义、只有 PARTIAL、没有独立支撑的声明仍会 UNVERIFIED，这是质量边界而非为了确认数应放松的条件。
- 官方发布链接必须明确表示自有文档；仅普通外部引用、裸云存储地址、跨 run 或不同哈希版本不能校准。
- 网络重试可能重复 provider token 计费，但有界、每次预算计量且不会重复业务写入。此次没有触发可重试网络异常，真实自动恢复仅由定向回归证明，未虚称在本次 LIVE 中触发。
