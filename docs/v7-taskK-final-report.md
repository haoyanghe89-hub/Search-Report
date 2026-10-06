# 任务 K 最终交付报告

日期：2026-10-03

## 结论

任务 K 已完成。改动只涉及报告组装、叙述与渲染，没有改写声明、证据、引用、来源独立性或 `VERIFIED / PROBABLE / UNVERIFIED` 判定标准。新报告按“结论速览 → 核心发现（有内容时）→ 证据基础 → 局限与后续建议 → 折叠附录”组织；空章节不再生成或渲染。

## 组装与渲染改动

- Writer 新增紧凑章节合同，同时继续接受旧章节键，保证现有 HTTP 响应与历史报告可读取。
- 结论速览采用 answer-first：先说明当前可确认和不能确认的范围，再给出声明状态、开放缺口与冲突数量。
- 已验证或很可能成立的声明按主题合成连续叙述；已在速览中出现的声明不再在核心发现重复。
- 研究缺口按 `gap_type` 全局聚合。同类缺口只生成一条“局限 + 影响范围 + 后续建议”，并保留所影响声明的引用关系。
- 原 `BLOCKING_GAPS_AND_LIMITATIONS` 与 `NEXT_STEPS` 的重复内容合并为单一用户章节“局限与后续建议”。
- 未证实声明在速览中只做主题级概括，具体声明只在对应局限项出现一次。
- `SearchUnavailableError`、`PDF_IMAGE_CONTENT_NOT_EXTRACTED`、`RUN_TIMEOUT`、Profile/ENTAILS 内部话术等技术诊断只进入技术附录；正文使用可读的影响说明。
- 调查问题、方法和技术诊断被标记为附录，前端默认折叠；旧报告中的范围、问题和方法章节也会归入折叠附录。
- 后端在哈希、验证、持久化和 Markdown/JSON 导出前移除空章节；前端仍做一次防御性过滤，不显示空标题或占位块。
- 新“结论速览”继续参与原发布策略的 probable/disputed 检查，没有因章节改名绕过治理判定。

## 去重与聚合规则

1. 叙述单元先做规范化文本去重，再按稳定语义键去重。
2. 已在结论速览完整陈述的 supported claim 不再进入核心发现。
3. 核心发现按 `claim_type` 聚合，不按底层对象逐条铺开。
4. 开放缺口按 `gap_type` 聚合；严重度取同组最高值，影响声明合并列出，建议紧跟该局限。
5. 目标明确的未证实声明只随对应缺口出现；没有目标缺口的未证实声明合并为一个局限项。
6. 技术诊断按错误标识去重并移入技术附录；正文不暴露机器错误码。
7. 所有章节只在存在非空叙述单元时持久化和渲染。

## 重构前后对比

| 指标 | RPT-641f951f80d4（基线） | 最终真实重跑报告 |
| --- | ---: | ---: |
| 实际渲染章节 | 7 | 5（3 个正文 + 2 个折叠附录） |
| `BLOCKING_GAPS_AND_LIMITATIONS` | 27 条 | 3 条聚合局限 |
| `NEXT_STEPS` | 16 条 | 0 个独立章节；建议与局限同行 |
| 上述两个重复区合计 | 43 条 | 3 条 |
| 空 `AVAILABLE_FINDINGS` | 1 个空章节 | 0 |
| 正文内部错误码 | 存在 | 0 |
| 最终叙述单元 | 基线其余章节数未改变性统计 | 16（正文 10，附录 6） |

## 同话题 quick 真实重跑

- 话题：谷歌 Gemini 4 Argon 实际能力与官方宣称是否相符
- 档位：quick
- Run：`RUN-LIVE-b2d124935bd54393`
- 最终报告：`RPT-44cbb173ba66`（对同一不可变快照应用最终 Writer 后生成的报告版本）
- 用时：270 秒
- 运行结果：`COMPLETED`，因 quick 档研究时间上限收尾
- 完整度：资料不足
- 来源 6、证据 5、声明 4、研究缺口 1
- 声明状态：VERIFIED 0、PROBABLE 0、DISPUTED 0、UNVERIFIED 4
- 报告没有把厂商表格升级为确认结论；速览明确说明目前不能确认，局限章节说明缺少可读取内容及第三方独立验证路径。

最终章节：

| 顺序 | 章节键 | 条目 | 展示层级 |
| ---: | --- | ---: | --- |
| 1 | `EXECUTIVE_STATUS` | 5 | 正文 |
| 2 | `EVIDENCE_BASE` | 2 | 正文 |
| 3 | `BLOCKING_GAPS_AND_LIMITATIONS` | 3 | 正文 |
| 4 | `RESEARCH_APPENDIX` | 3 | 折叠附录 |
| 5 | `TECHNICAL_APPENDIX` | 3 | 折叠附录 |

机器验收结果保存在 `frontend/test-results/task-k/live-rerun-regenerated.json` 和 `frontend/test-results/task-k/live-report-acceptance.json`。其中正文诊断码检查为 `false`（即未发现内部诊断码），最终 UI 验收为 `passed: true`。

## 截图证据

- `frontend/test-results/task-k/live-report-1440x900-closed.png`：同话题真实重跑报告，附录默认折叠。
- `frontend/test-results/task-k/live-report-1440x900-open.png`：同一报告展开调查方法与技术诊断附录。
- `frontend/test-results/task-k/report-1440x900-motion-closed.png`：桌面离线回放报告。
- `frontend/test-results/task-k/report-390x844-reduced-open.png`：390 × 844、reduced-motion、附录展开。

浏览器验收共 20 项，0 失败：覆盖空章节、重复标题、默认折叠、正文诊断隔离、桌面/移动端横向溢出、reduced-motion、控制台错误和页面错误。

## 测试结果

- 聚焦后端回归：51 passed，1 个第三方库弃用警告。
- 完整后端：559 passed，10 skipped，0 failed，用时 247.97 秒；跳过项为未配置的 PostgreSQL/Redis/live key、Windows symlink 和 POSIX-only 条件。
- Ruff：`All checks passed!`
- Python 编译与导入：通过，`imports-ok`。
- 前端单元测试：32 passed，0 failed。
- 前端生产构建：Vite 成功，退出码 0。
- Playwright：20/20 通过；真实重跑报告额外验收 `passed: true`。
- `git diff --check`：通过；只有工作树既有的 LF/CRLF 提示，没有空白错误。

## 仍存限制

- quick 重跑在 270 秒达到档位时间上限，4 条量化声明仍是 UNVERIFIED；这是真实调查结果，不由本次呈现重构更改。
- 报告只能说明目前材料不足以确认厂商基准、第三方复测和性价比外推，不能据此得出产品能力真伪结论。
- 外部 PostgreSQL、Redis 与需要密钥的 live pytest 按环境条件跳过；本任务另行完成了一次真实 quick 调查作为外部链路证据。
- 浏览器与真实重跑产生的临时 SQLite、blob 和 Playwright 运行时已清理；JSON 结果与截图证据已保留。

设计说明和实施清单分别保存在 `docs/superpowers/specs/2026-10-03-task-k-report-presentation-design.md` 与 `docs/superpowers/plans/2026-10-03-task-k-report-presentation.md`。brainstorming、writing-plans、webapp-testing 与 verification-before-completion 技能分别用于固化结构合同、分步落盘、浏览器验收和最终证据复核。
