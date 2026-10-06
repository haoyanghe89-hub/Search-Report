# Task J 最终交付与验收记录

日期：2026-10-02。前端两处功能已实现；收尾、depth、删除后端已实现。**真实 quick 首跑未达到“最终报告在 5 分钟内生成”的验收目标，不能判为全项通过。** 已修复发现的问题并恢复同一运行报告；没有再次发起付费调查。

## 1. 三项功能

### 保证收尾 / 优雅终止

- 主执行路径任意阶段异常、时间到点、用户停止、服务关闭、watchdog 停滞都进入本地 report finalizer。只有报告持久化之后才置 COMPLETED；实际停止原因不抹掉。
- 研究时间末尾预留 30s 收尾。不新增付费报告调用；报告由现有确定性 writer 按已归档材料生成。证据、引用、独立性与发布门禁不改。
- 正常报告标注完整度、未评估声明、缺口与进一步调查建议；支持的发现仍按 VERIFIED / PROBABLE 区分，不把 PENDING、UNVERIFIED 或 DISPUTED 提升为确认事实。完整档还要求问题覆盖与无未解决冲突，不能只凭已确认比例宣称完整。
- 正常报告重试最多 3 次（0.1s、0.2s 退避）；失败后独立应急模板最多 3 次。应急模板不调用正常 writer/projection，不作任何事实结论，保留原材料，仅产出受限说明。
- 若连报告持久化也不可用，保留 REPORT/BLOCKED/未完成检查点，不假称 COMPLETED；重启后只重试本地收尾，无新增模型计费。磁盘/数据库永久故障、进程掉电期间不能保证立即落盘。
- 历史未完成运行的显式恢复测试仍保留；测试夹具模拟“收尾前掉电”，生产没有禁用 finalizer 的开关。已完成的运行不再作为未完成检查点恢复，可另起新运行。

### 时长三选一

新建调查弹窗在标题下提供原生 radio 卡，默认标准。创建 depth 写入调查审计事件；启动时省略字段继承，显式字段可覆盖，每次运行持久化固定 preset，互不干扰。

| 配置上限 | quick | standard | deep |
|---|---:|---:|---:|
| 总时间 / 研究截止 | 300s / 270s | 600s / 570s | 1800s / 1770s |
| 采集轮次 | 1 | 3 | 6 |
| search / fetch / 来源 | 12 / 32 / 16 | 48 / 80 / 40 | 120 / 160 / 80 |
| model calls / tokens | 40 / 300,000 | 120 / 1,000,000 | 240 / 2,000,000 |
| 每次分析来源 / 摘录 / 字符 | 4 / 8 / 12,000 | 8 / 16 / 24,000 | 12 / 24 / 40,000 |
| 研究并发 / 每研究员 queries | 2 / 2 | 4 / 3 | 4 / 3 |
| 验证 batches / model calls | 1 / 12 | 12 / 32 | 24 / 64 |

上述是档位上限，运维配置更低时取更低值；深度不会突破总量与墙钟上限。token/call 阶段预留复用既有 StageBudgetPolicy，确认标准与模型角色路由未降低。界面的“约”时长是目标，不保证网络/模型响应或确认结果数量。

### 删除历史卷宗

- 列表选择与删除分离为原生按钮，先打开告知永久级联删除的对话框，再勾选确认后方可提交；忙碌时不重复提交/关闭。错误保留卷宗，成功移除列表并播报轻提示。
- DELETE /api/investigations/{id}：活跃运行或报告收尾中返回 409，须先停止并等待收尾；已删除重复请求返回 already_deleted=true。
- 单事务按 investigation/run 所有权与外键清理：runs、budget、steps、research tasks、sources、snapshots、artifacts、evidence、claims/relations、validation、semantic judgments、families、conflicts、gaps、timeline、recorded calls/intents、audit、报告快照/版本/章节/引用/校验/发布评估、审核请求与决定。无所有权 FK 的历史人工录签按报告哈希匹配，仅删除无其他卷宗引用者。
- 迁移 20261002_07 为目标行提供事务内精确 DELETE 许可，完成后许可移除；普通 DELETE 与 UPDATE 仍被 append-only 触发器拒绝。没有关闭全库防护。
- 内容寻址 blob 在行删除提交后核对全库引用，只删除无引用文件；共享文件保留。其他活跃写入时延后 GC；非 SQLite 没有同等 writer lock 时保守延后文件清理。未删除任何用户真实卷宗，删除验收使用隔离数据库。

## 2. 前端验收

- 沿用 Digital Folio、现有 token 与 GSAP 对话框方案；新组件没有硬编码颜色，73 个引用 token 均有定义。原生表单、键盘焦点、44px 可点击卡区域、错误播报、reduced-motion 的内容可见与清理保留。
- Playwright 使用项目 Python 环境与隔离工具依赖、已安装 Edge；仅 mock /api/，不写真实数据。
- 1440×900、1366×768、1024×768、768×1024、390×844、360×640、844×390；双主题 × 两种 motion 偏好，共 28/28 场景通过，84 次三档提交，28 次删除确认/409 保护/成功删除，113 张截图。
- DOM 检查：无页面/弹窗横向溢出、弹窗不越视口、短屏可滚动；减少动画时 opacity=1。控制台无非预期错误，模拟 409 单独记录。截图抽查手机浅色及横屏深色，未见裁切；不是独立视觉评奖或性能压测。
- 证据：reports/taskj/ui/acceptance.json 及同目录截图。

## 3. 唯一真实 quick E2E 与缺陷修复

运行 RUN-LIVE-9cb0d5d450b14093，话题“谷歌 Gemini 4 Argon 实际能力与官方宣称是否相符”，隔离 reports/taskj/quick-live-20261002/live.db。

| 指标 | 实际结果 |
|---|---|
| 研究预算截止 | 约 270s（记录消耗 269.155s） |
| 创建至实际收尾完成 | 371.042s，约 6 分 11 秒 |
| search / fetch / model | 4 / 4 / 8 |
| token | 45,592 / 300,000 |
| 来源 / 证据 / 候选声明 | 4 / 4 / 9 |
| 验证状态 | PENDING 9；VERIFIED / PROBABLE / 其他已评估状态均 0 |
| 最终运行 | COMPLETED，停止原因 RUN_TIMEOUT |
| 最新报告 | RPT-fd6795697839，INVESTIGATION_STATUS / RESTRICTED |
| 完整度 | 资料不足；明确没有可确认发现，保留缺口和重试建议 |

真实发现：本轮摘要文案的字符串连接遗漏 `+`，引发 TypeError，使正常与当时共用 writer 的 fallback 都失败。补齐连接符并把 fallback 隔离为直接构造七节、仅治理披露的应急模板；新增“writer 永久抛 TypeError / 有材料或零材料仍生成受限报告”回归。

同一运行仅离线恢复，没有再搜/抓/调用模型；保存两个报告版本，首次诊断成功写入的版本与最终收尾版本均保留，不篡改历史。原始 final.json 保留失败检查点，offline-recovery.json 与 audit-final.json 记录最终完成状态，report-diagnostic.txt 保留真实根因，RPT-*.md 为持久化报告导出。

**判定：材料与报告最终保存、无未受控 FAILED；但首跑未在 5 分钟内生成报告、没有形成已确认结论，因此时间与结论性报告目标没有由本次 E2E 证明。没有为凑 VERIFIED/PROBABLE 而降门槛，也没有重复付费重跑。**

## 4. 本轮改动文件

前端：frontend/src/App.vue；components/NewInvestigationModal.vue、DepthSelector.vue（新）、DeleteInvestigationModal.vue（新）、Sidebar.vue；styles/tokens.css。

后端：src/marketpulse/config.py；infrastructure/storage/local.py；investigation/depth.py（新）、deletion.py（新）、api.py、server.py、live_runtime.py、recovery.py、persistence/models.py、reporting/writer.py、reporting/pipeline.py、reporting/chinese_writer.py；migrations/versions/20261002_07_archive_deletion.py（新）。

测试：tests/integration/investigation/test_taskj_delivery.py（新）、conftest.py、test_live_runtime.py、test_live_resume.py、test_auto_recovery.py、test_supervised_crash.py、test_source_fetch_tolerance.py。旧 FAILED/BLOCKED 期待只在 Task J 收尾语义改变处同步，历史恢复夹具显式隔离。

工具/记录：scripts/verify_taskj_ui.py（新）、finalize_taskj_quick.py（新）；verify_live_token_budget.py 仅增加 --depth 选项；docs/taskj-progress.md、本报告。现有 A–I 及 UI v3 的其他未提交变更保留，未混作本轮新增。

## 5. 最终检查

- 前端 npm run build：退出码 0；npm test：30/30。
- Playwright：28/28；非预期错误 0。
- 新增应急模板定向测试：2 passed（有/无材料）；Task J 基础 24 项先前通过。
- 后端最终全量：558 passed、10 skipped、0 failed，退出码 0，266.48s；使用独立 reports/taskj/pytest-full-7、-p no:cacheprovider，XML 证据 reports/taskj/backend-full-final.xml。包含全部 26 项 Task J 回归。
- Ruff src/tests/新迁移/本轮工具：通过；compileall 与服务/运行/删除模块导入：通过；git diff --check：退出码 0，只有已有 LF/CRLF 提示。

## 6. 使用边界

后端重启会自动升级至迁移 20261002_07；未重启用户现有后端。既有 HTTP 字段/路径兼容，depth、DELETE 为增量，cancel 完成后的状态按 Task J 收尾语义返回 COMPLETED。PostgreSQL/Redis/真实网络 live 套件及 Windows 特定系统用例仍有环境跳过，不能声称已覆盖。永久数据库/磁盘不可写时只能保留待收尾检查点，无法绝对保证当场报告落盘。真实 quick 时限与可发布结论仍需在修复后的干净进程中再次验收。
