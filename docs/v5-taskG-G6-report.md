# 任务 G 补验与 G6 真实重跑

## 两个测试文件的核对

当前工作区收到本轮请求时，writer 测试已断言 `report-writer-zh-v3`，
原子性测试已断言 `validation-policy-v2`。实跑两个完整文件为
**15 passed，1.21 秒，退出 0**，未复现新的原子性失败。
此前 v2 writer / v1 policy 断言与已升级内部版本不同步；
本次不能据未提供的旧失败日志推断仍有持久化代码故障。

writer v3 改动经过代码核对：优先 VERIFIED、再用 PROBABLE 补结论摘要，
显式标注“很可能成立（仍有明确保留项，不等同于已验证）”；
不修改原 Claim、置信度与引用内容，不绕过引用或发布审核。
保持 v3 合理，而不是回退版本去迎合旧断言。

本轮仅增强测试，没有修改生产代码：

- `tests/unit/investigation/test_phase5_writer_validation.py`：
  新增只有 PROBABLE/UNVERIFIED 时的 Answer-first 测试；
  确认 v3、不变快照、明确保留项、不把未验证声明放成摘要结论，
  缺引用仍触发 `CITATION_INCOMPLETE`。
- `tests/integration/investigation/test_phase42_validation_persistence.py`：
  明确检查两条历史的 policy v2/profile v2；非法更新被 append-only 拦截后，
  仍保留两条历史、最新投影指向第二条。既有 FK、指纹稳定、族/冲突记录
  与不可改写断言均未删除。没有修改生产事务或数据库触发器。

增强后两个完整文件：**16 passed，1.20 秒，退出 0**。
独立 basetemp：`reports/taskg/pytest-user-fixed`，`-p no:cacheprovider`。

## 全量验收

本轮最终全量：**487 passed / 3 skipped / 7 deselected / 1 warning，
188.53 秒，退出 0**。
命令：`.venv/Scripts/python.exe -m pytest -m 'not live and not infrastructure'
--basetemp=reports/taskg/pytest-g6-release -p no:cacheprovider -q --tb=short`。
3 项为 Windows 符号链接/POSIX 条件跳过，7 项依赖外部 live/infrastructure；
保留既有 Starlette/AnyIO 弃用警告，不将跳过项冒充通过。
Ruff（src tests scripts）、本轮两文件格式检查、编译/导入与
`git diff --check` 退出 0。既有 LF→CRLF 提示不是空白错误。

OpenAPI 指纹仍为
`8a7ac4bb65c741aa7c54002ec9c12a1f75963da552e04e709547928429bdaf9e`，
请求/响应字段、路由、状态枚举、前端没有本轮变化。

## G6 执行安排及结果

用户本轮明确授权一次真实付费重跑，取代上一轮不自行发起的安排。
[授权边界](D:/deepsearch/reports/taskg/g6-authorization.md)已落盘。

回归通过后使用最新 G 代码、只读复制同话题定义、全新独立数据库与归档目录，
不复用旧 Sources/检查点、不接管现有后端。不自动恢复旧未知调用，
不为了目标数量修改分级门或发布门。

真实运行于 2026-10-02 10:30:17 UTC 开始：`RUN-LIVE-031c3198d5e84b6c`。
独立目录：[G6 运行归档](D:/deepsearch/reports/taskg/g6-live-20261002)。
该运行于 10:37:47 UTC 结束，进程退出 0，业务终态为
**BLOCKED / REPORT / VERIFICATION_LIMIT_REACHED**。
**G6 已执行，但业务目标未通过，不能宣布任务 G 已达成真实可发布结论。**

| 实际结果 | 数量/状态 |
|---|---:|
| 已持久化 Source / Snapshot / Evidence | 35 / 42 / 60 |
| Claim | 55 |
| VERIFIED / PROBABLE / UNVERIFIED / PENDING / DISPUTED | 0 / 0 / 52 / 3 / 0 |
| 验证历史记录 | 290 |
| 搜索 / 抓取 / 全部模型调用 | 164 / 48 / 143 |
| token 使用 / 上限 | 735,045 / 2,000,000 |
| 完成的验证批次 / verifier 调用 | 24 / 54 |
| 保守计量的 verifier token / 上限 | 194,545 / 700,000 |
| report ID | RPT-3f4260cf7c68 |
| report_type / release_status | INVESTIGATION_STATUS / REVIEW_REQUIRED |
| 持久化报告 Citation | 0 |

模型归档包含 141 SUCCESS、2 INVALID_RESPONSE；没有未知调用自动重试。
分角色调用为 planner 5、researcher 64、analyst 20、verifier 54。
归档请求/响应 SHA 核对后，按 G 准入规则汇总的实际或缺失时保守估计 token 为：
planner 43,587、researcher 277,024、analyst 251,235、verifier 194,545。
合计保守值不等同于预算账本的实际 735,045，不能混作实际收费 token。

这次触发的是 **24 批次上限**，不是 64 次调用或 700,000 verifier token 上限。
总 token 剩余 1,264,955，报告确定性生成并落库；
证明上限/预算保护生效，但不能证明声明生成质量或结论目标已经修复。
Source 35 是实际表记录；budget.sources_used=39 是预算记账值，不能冒充 39 个不同来源。

原始结果：[final.json](D:/deepsearch/reports/taskg/g6-live-20261002/final.json)；
缺口明细：[final-validation.json](D:/deepsearch/reports/taskg/g6-live-20261002/final-validation.json)；
期间进度、配置、数据库、模型请求/响应和材料 Blob 全部保留在独立目录。

## 未达标原因与报告核对

对 52 条已有最新验证的声明，36 条至少有一项 ENTAILS，
最新 basis 共含 40 项 ENTAILS；来源评分有 0.52 / 0.64 两档，
没有未解决冲突。**不能笼统把这次失败归为网络不可达或完全无支持证据。**

| 最终 Profile 缺项（可重叠，3 条 PENDING 不计入） | 声明数 |
|---|---:|
| time / definition / value / unit | 10 / 13 / 1 / 1 |
| 两个足够质量支持来源 / 一个足够质量来源 | 17 / 3 |
| 两个独立来源族 / 一个独立来源族 | 14 / 1 |
| 完整声明的 ENTAILS 缺失 | 14 |
| 权威原始发言记录 / 发言 ENTAILS 缺失 | 12 / 2 |
| 推断的 reasoning_basis / uncertainty | 各 11 |
| 推断多来源族 / 多条支持证据 / 来源质量档 | 8 / 6 / 11 |
| 归因类型 / 利害方边界 / 独立佐证 / 质量 / 直接认定 | 各 9 |

本次 Claim 类型为 QUANTITATIVE 22、STATEMENT 13、ANALYTIC_INFERENCE 11、
ATTRIBUTION 9。存在真实的生成/对齐残留：

- 5 条已有声明给了 `benchmark_definition`，未规范为 canonical `definition`；
  其中 4 条数值声明仍因 definition 缺失被挡，但它们同时也缺 time，
  部分还缺独立佐证/完整 ENTAILS，不能只补别名就声称能通过。
- 11 条推断均未给齐 reasoning_basis/uncertainty，9 条归因未给齐对应核心条件。
  原 v6 提示重点约束数值声明，尚未让实际模型输出对齐所有 Profile 的条件。
- 有 ENTAILS 不等于整个 Profile 充分；低质量档、单来源族、部分支持、
  引用范围或核心限定欠缺，仍不能升级为 VERIFIED/PROBABLE。
- 只凭保存引文无法确定其余缺项在完整原文中是否存在，不从网页日期猜测测量时间。

报告首节为 EXECUTIVE_STATUS，明确“尚无通过验证的关键发现”，
展示 52 条已验证过但 UNVERIFIED 的声明与 144 项当前报告缺口；
3 条 PENDING 仍保留在 run 中，并未当作已验证纳入报告投影。
报告共 377 个 GOVERNANCE_DISCLOSURE 单元、5 个 PRESENTATIONAL 单元，
没有可发布事实单元、没有 Citation；所以**不是 Answer-first 结论性报告**。
660 个 run 历史缺口与报告的 144 项当前缺口是不同口径，不能混算。

本轮不手改历史 Claim/验证状态、不把空引用或未验证陈述包装为结论，
也不提升 release_status 或扩大上限掩盖失败。

## 最终交接

两处测试版本同步及行为核对通过；487 项非外部回归全绿；G6 确实完成一次真实运行，
但 VERIFIED/PROBABLE 与结论性可发布报告目标未达到。
本轮未新增生产补丁，仅完成测试增强、真实运行与只读诊断，
没有把重跑前后的代码混作不同版本的成功证明。

后续需基于同一归档输出修正 Profile 生成字段/语义类型与明确别名的对齐，
并离线验证；不能通过随意放宽引用、独立性或数值限定去“凑”结果。
如要再次真实付费验收，需用户决定是否授权另一运行；本轮没有自动追加。
独立 runner 已退出，无需用户额外停止验收服务，现有后端未被重启或接管。

G1–G5 的详细规则与原归档诊断见
[任务 G 基础报告](D:/deepsearch/docs/v5-taskG-final-report.md)。
