# Task O：P0-E / P0-F 交付与验收记录

日期：2026-10-04。依据：Task L 第12、14.1、15章、Task N交付及开发日志。本批仅增量接线，未提交Git、未进入P1、未新增付费模型调用。

## 1. 结论与边界

已实现量化HTTP入口、冻结窗口选择、后台有界计算、最新验证链与计算引用、报告内三个证据展品。网页调查仍默认选中；旧网页枚举、响应与v1报告语义不改。量化计算不由模型生成数字，前端只做绘图坐标和展示转换，不计算核心指标。

本批真实验收使用三标的**历史冻结数据**，不是当前行情：2024-05-20—2024-06-14，共19个交易日，研究时点2024-06-15T00:00:00Z。三份报告均部分完整，每份17条观察、17条计算引用，全部UNVERIFIED。接口可用和复算一致不表示来源/PIT/授权门禁已满足，也不表示三年数据覆盖已经验收。

P0的本地可复现“数据→计算→证据→HTTP→报告图表”链路已接通；严格历史PIT、普通股权益分配口径、生产数据授权、长窗口及跨OS复算仍有缺口。建议先完成这些P0数据质量工作，再批准P1因子/回测。

## 2. HTTP接口与契约

| 接口 | 行为 |
|---|---|
| `GET /api/quant/instruments?q=&limit=` | 仅已注册主数据；ins_ ID、代码、中文名、市场、交易所、板块、上市/退市状态。limit默认20、最大100 |
| `GET /api/quant/instruments/{id}/windows` | 补充的显式冻结窗口；日期/asof/快照集合及真实样本数，不把旧快照伪装latest；歧义窗口不推荐 |
| `POST /api/quant/runs` | 202；返回run_id/investigation_id/status，复用现有卷宗、RunBudget、depth与审计；创建响应CREATED不是最终状态 |
| `GET /api/quant/runs?limit=&offset=&status=` | 默认20、最大100；数组式run DTO、状态过滤和offset分页，沿用现有响应风格 |
| `GET /api/quant/runs/{id}` | run、服务端phase、report_id、只读values/charts、计数、缺口、asof、输入ID、manifest/output hash、methodology |
| `POST /api/runs/{id}/cancel` | 沿用既有取消；终态取消409。停止取数/worker后收尾，报告持久化成功才COMPLETED |
| `DELETE /api/investigations/{id}` | 沿用卷宗删除归档流程；活跃任务409，历史量化卷宗可删除，不直接删除共享snapshot |
| `GET /api/reports/{id}`、`/citations`、`/export?format=markdown` | 原报告接口；v2增量呈现量化正文与计算引用 |
| `GET /api/citations/{id}` | COMPUTATION_CELL分支：真实冻结计算、定位与最新验证；不虚构网页来源/引文/归档URL |

新增路由沿用现有本地可信操作员HTTP边界与`detail:{code,message}`错误风格，不宣称新建了互联网多租户认证。unknown instrument、未来asof、未完整session、冻结输入歧义返回422；无依赖503/QUANT_NOT_CONFIGURED；最新链/哈希漂移409且不返回数字。旧网页HTTP分支不受可选库缺失影响。

请求示意（真实快照ID需从对应windows取得，不能复制占位ID）：

```json
{
  "instrument": "000001",
  "date_start": "2024-05-20",
  "date_end": "2024-06-14",
  "asof": "2024-06-15T00:00:00Z",
  "adjustment": "raw",
  "depth": "quick",
  "frozen_snapshot_ids": ["从windows选定的完整输入集合"]
}
```

不指定日期时可用`window:1y/3y`；date_start/end必须成对、范围不超过1096日。默认adjustment=raw、depth=standard。qfq/hfq的anchor由结束日冻结，原anchor校验未放松。benchmark/rf缺失产生解释性缺口；rf="zero"只作为用户明确假设。P0尚无对外标准化基准/利率快照输入契约，非空benchmark及其他rf文本明确422，而不是模拟接入或静默写零。

## 3. 后端实现与安全边界

- lifespan只检查可选库是否存在，启动时装配QuantService并在恢复中断任务前注入runner；3.11不安装quant extra仍能启动。不存在依赖时量化503，网页health200。
- 有显式冻结ID时校验标的、日期、asof、raw/所选复权、覆盖日历和唯一性，读取CAS并绑定ownership，不替换为latest。
- 无显式ID时，FrozenDataService优先缓存；录制端口调用隔离SDK进程。价格BaoStock→AkShare腾讯→AkShare东方财富，财报/股本补充走东方财富归母规范化3-parent-2；错误与重试保留。每调用45秒预算并受depth总期限约束，缺可选财务产生null和报告局限。
- 计算、复算仍走P0-C有界子进程；输入、配置、代码树、锁文件、schema、输出均受manifest/hash约束。绘图数值在worker内进入同一ArtifactBundle，而非HTTP或浏览器临时算出。
- 返回值先核验material/job绑定、输入ownership与CAS、完整输入manifest、output/manifest hash、持久化最新Claim/Validation和cell定位。只有完整性及REPRODUCIBLE成立才返回数字；统计/PIT/来源门槛不足仍显式UNVERIFIED。图表统一保守标UNVERIFIED，展示不是发布批准。
- 阶段为取数→冻结快照→确定性计算→证据核验→成稿；取消/失败走已有partial_finalize。恢复重用计算租约/录制；成稿失败不能提前COMPLETED。成稿前的READY_FOR_REPORT/BLOCKED仅在量化前端继续轮询，旧网页终态语义不变。
- 未改迁移：启动通过现有Alembic升至`20261004_09`，在独立测试库验证；未对用户业务库进行迁移或替换。

## 4. 前端入口、报告与口径

入口：侧栏“新建调查”→默认“网页调查”/可切“量化投研”→证券联想选择→显式冻结或自定义窗口→raw/qfq/hfq→既有quick/standard/deep→启动。

| 文件 | 职责 |
|---|---|
| `components/quant/QuantResearchForm.vue` | 注册标的联想、日期/冻结窗口、复权/档位与提交防重；历史asof明确显示 |
| `components/quant/QuantChart.vue` | Canvas图表壳，主题/resize/dispose/reduced-motion、键盘原值表、定位按钮 |
| `components/quant/QuantReportSection.vue` | 报告流内≤3展品、完整只读cell/口径/日期/manifest/输入定位 |
| `utils/quantChartOptions.js` | 只投影已给定值，保留null，不连接缺口；richText tooltip避免来源内容作为HTML |
| `utils/quantEcharts.js` | ECharts6.1.0 core+Line/Bar/Grid/Legend/Tooltip/Canvas按需异步导入 |

展品插入量化分析SECTION正文之后，不堆在报告顶端；沿用720px阅读流、数字卷宗token、单accent、EXHIBIT-Q·N、现有编排动效。折叠方法/技术附录、空章裁剪与局限聚合沿用既有报告组装。报告成稿标签与VERIFIED独立，头部显示冻结快照数而非“0网页来源”。

| 展品 | 数值/单位与约束 |
|---|---|
| EXHIBIT-Q·1 价格与回撤 | raw/qfq/hfq冻定价格CNY/share，回撤fraction；切换只选后端序列。标最大回撤峰/谷/恢复，不虚构恢复日。不是策略净值，raw收益不含现金分红 |
| EXHIBIT-Q·2 估值口径对照 | 独立PE/PB ratio和BaoStock、AkShare/东方财富披露值分列；独立值raw价格×同日总发行股数/TTM归母净利或归母总权益，不平均、不排名 |
| EXHIBIT-Q·3 财务报告期趋势 | 归母净利同比、合并营收同比fraction；年报对年报、同累计季度对上年同期，由worker计算，缺前期null+原因，不年化 |

图表每点携带`metric_path/cell_hash`；表格保留后端完整Decimal字符串，图形只作浮点投影。点击定位显示artifact、cell、定义、单位、采样日期和row_keys；有报告引用的标量可以继续打开最新计算引用。绘图扩展点无逐点报告引用时，仍由完整artifact/hash与可定位cell支持，状态不提升。

## 5. 文件范围

这是O批工作范围，不是当前含A—N变更的全部脏工作区diff。

新增后端：`quant/api.py`、`acquisition.py`、`charts.py`、`windows.py`、`compute/exhibits.py`。

增量修改：`quant/domain.py`、`compute/engine.py`、`validation.py`、`reporting.py`、`citations.py`、`data/worker.py`；`investigation/api.py`、`server.py`、`feedback/orchestrator.py`。旧report v1分支不变，量化spec新增显式price_adjustment与include_exhibits。

新增前端为上节五文件及`tests/quantReport.test.js`；修改`NewInvestigationModal.vue`、`ReportDetail.vue`、`RunProgress.vue`、`views/InvestigationView.vue`、`composables/useInvestigation.js`、`tests/runPolling.test.js`、`package.json/package-lock.json`、`vite.config.js`。

新增测试：`tests/unit/quant/test_exhibits_o.py`、`tests/integration/quant/test_api_o.py`。新增验收辅助：`scripts/verify_quant_o.py`、`serve_quant_o.py`、`verify_quant_ui_o.py`。文档：本文、`quant-dev-journal.md`及`superpowers/plans/2026-10-04-task-o-implementation.md`。

## 6. 验证结果

后端最终实现之后、前端轮询修复之前执行的后端回归（之后未修改后端源码）：

```powershell
.phase3-quant-m/venv313/Scripts/python.exe -m pytest tests/unit/quant tests/integration/quant -q -p no:cacheprovider --basetemp .phase3-quant-o/quant-final-01
# 83 passed, 1 warning / 125.18s，exit0
.phase3-quant-m/venv313/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp .phase3-quant-o/backend-final-01
# 642 passed, 10 skipped, 1 warning / 502.11s，exit0
```

跳过：3项PostgreSQL/Redis未配置、2项Windows symlink权限、1项POSIX SIGTERM、4项未启用live网络/付费模型。没有将这些计为通过。Starlette旧BlockingPortal弃用警告保留。新API覆盖缺依赖503、已注册搜索/非法pins、启动/查询/分页、UNVERIFIED、引用打开、计算期间health响应、取消部分报告、活跃删除409与历史归档。

```powershell
cd frontend
npm test        # 36/36，exit0，包括量化成稿轮询和终态并发列表竞态回归
npm run build   # exit0，无错误，无>500KB chunk警告
cd ..
.phase3-quant-m/venv313/Scripts/ruff.exe check src tests scripts/verify_quant_o.py scripts/serve_quant_o.py scripts/verify_quant_ui_o.py
git diff --check
```

Ruff与diff均exit0（git只提示既有CRLF转换）。3.13导入42个quant模块与旧server成功；3.11无7个quant库，真实TestClient启动新私有SQLite库、health200、quant503，检查scientific模块未导入。未运行3.11全量或跨OS复算，不能冒称覆盖。

构建：主JS337.36KB/gzip131.34KB，ECharts359.81KB/gzip124.17KB，renderer176.77KB/gzip59.23KB；后两者在量化报告需要时异步载入。npm audit发现现有Vite5.4.21/esbuild的2项开发依赖漏洞，本批不自动跨大版本升级，公网部署前需安全升级。

真实服务器Playwright（非mock）最终命令：

```powershell
.phase3-quant-m/venv313/Scripts/python.exe scripts/verify_quant_ui_o.py --source .phase3-quant-o/http-real-02 --output .phase3-quant-o/ui-real-02
.phase3-quant-m/venv313/Scripts/python.exe scripts/verify_quant_ui_o.py --source .phase3-quant-o/http-real-02 --output .phase3-quant-o/lineage-final-01 --lineage-only
```

两命令exit0。375/768/1440×light/dark×reduce/no-preference共12场景：每页3图、4正文SECTION、附录默认折叠、页面无横向溢出；真实ECharts animation按媒体偏好为false/true；hfq切换、原值cell定位、最新计算引用对话框可用；pageerror=[]。另从真实新建表单选择冻结窗口启动任务，未经刷新成功成稿并出3图：RUN-QUANT-6799d1d1cd6f4d32 / RPT-204caa679519。三标的各138个图表点（合计414）逐一核对value、unit、artifact_id、metric_path和cell_hash与HTTP只读values一致，没有浏览器重算指标。

截图/记录：`.phase3-quant-o/ui-real-02/summary.json`、`report-{375,768,1440}-{light,dark}-{reduce,no-preference}.png`、`entry-real-frozen-run.png`；逐点链记录`.phase3-quant-o/lineage-final-01/summary.json`。失败截图`ui-debug-01`保留用于说明真实修复过程，不当作通过证明。

## 7. 真实三标的HTTP/复算证据

命令：

```powershell
.phase3-quant-m/venv313/Scripts/python.exe scripts/verify_quant_o.py --source .phase3-quant-n/financial-frozen-02 --output .phase3-quant-o/http-real-02
```

来源库只读backup，复制CAS到O私有目录；N旧live/财务证据不覆盖。通过实际HTTP创建quick任务、等待持久化、读取报告/图表/引用、冻结输入复算，没有mock供应商数据或新增SDK/模型调用。计算child禁止联网；这里不声称对整个操作系统做物理断网。API初始化确有市场依赖，指标与报告没有付费调用。

| 标的 | run / report | 独立PE / PB / ROE（展示舍入） |
|---|---|---|
| 平安银行000001 | RUN-QUANT-9309906a89054228 / RPT-ad7d259b01a6 | 4.22255525 / 0.40684104 / 10.03624288% |
| 美的集团000333 | RUN-QUANT-d6ff7e9a69494c39 / RPT-3ad2dd0caf8e | 13.19711194 / 2.65306697 / 21.35014773% |
| 贵州茅台600519 | RUN-QUANT-8837ee1e019749df / RPT-75e98f48322b | 25.04200145 / 8.14822103 / 34.06252302% |

每份7个输入快照、3图、17观察/17引用、0VERIFIED/0PROBABLE/0DISPUTED/17UNVERIFIED；登记provider/upstream组合2个，已确认独立来源族0个；合计51观察/51引用。每份累计收益/回撤绝对差0，PE/PB相对差0，满足1e-10/1e-8；同环境output bytes hash一致。注意summary的status来自POST的CREATED回执，最终COMPLETED见run-N.json，不将创建回执冒充终态。

三个完整输出hash：

```text
bank   dbdd1a07efaf2889cb706c5a632fdaaa24f8015f76205ac7cef943204b9f6c88
midea  25e7bce53967221f444cadaefc5b916c200bf63ee56e442f07c421f4cb897466
maotai fc734002a2f8bb4f92f0639612df5bc3c86c7b1831cdeafdbde10ac134238c39
```

每份章节：结论速览1条→证据基础2条→量化发现17条+3展品→局限与后续5条→折叠调查问题/方法3条→折叠技术说明1条。4个正文SECTION、2个附录节，无空节。

证据目录：`.phase3-quant-o/http-real-02/`，含`summary.json`、`run-{0,1,2}.json`、`request-{0,1,2}.json`、`report-{0,1,2}.json/md`、`citations-{0,1,2}.json`、`artifact-{0,1,2}.json`、独立`metadata.sqlite/blobs`。manifest在artifact的manifest_json中，输入与schema/代码/锁文件绑定可查。

## 8. 启动与演示

普通开发（启动前备份需要保留的业务库，server会按现有流程自动升级到09）：

```powershell
# 项目根，使用已有3.13量化环境
.phase3-quant-m/venv313/Scripts/python.exe -m marketpulse.investigation.server
# 另一终端
cd frontend
npm run dev -- --host 127.0.0.1
```

默认API8000，Vite5173，现有代理默认不变。可用`INVESTIGATION_PROXY_TARGET`在启动前显式指定其它回环API。不装quant extra的3.11环境仍可启动网页服务，但量化503。一般新库没有证券主数据；不能把任意六位代码当已注册标的，本批没有新增自动全市场注册。

本批可复查的隔离演示（不替换业务库，不需要模型密钥）：

```powershell
.phase3-quant-m/venv313/Scripts/python.exe scripts/serve_quant_o.py --data .phase3-quant-o/http-real-02 --port 8830
# 浏览器 http://127.0.0.1:8830
# 重新生成UI证据须使用不存在的新output目录
.phase3-quant-m/venv313/Scripts/python.exe scripts/verify_quant_ui_o.py --source .phase3-quant-o/http-real-02 --output .phase3-quant-o/ui-recheck-01
```

打开三标的卷宗报告，展开原值表→点`/values/N`看cell；点正文引用看COMPUTATION_CELL/最新Validation；切raw/qfq/hfq；查看折叠附录。新建量化选择平安银行、显式历史冻结窗口后启动，等待服务器成稿再阅读，避免把短历史样本当实时行情。

本批专用8830验收服务已在结束时正常停止；以上命令可重新启动。其它用户服务未停止，所有证据目录保留。

## 9. 前端自检（参考Awwwards/Webby/FWA维度，不宣称获奖）

| 维度 | 已做 | 后续可提升 |
|---|---|---|
| 排版 | 延用folio标题、正文与mono坐标分工，720px叙事宽度 | 17条观察较长，需用户评审后精简分组密度 |
| 留白 | SECTION内嵌EXHIBIT，稳定节奏，不顶部堆图 | 长财务原值表可提供报告期筛选 |
| 层级 | answer-first、正文/技术附录分层、成稿/验证区别 | 量化概览目前仍借用旧协作/时间线壳，可后续专项优化 |
| 色彩 | 单accent、继承暗色token、无红绿涨跌暗示 | 增加正式对比度与色觉辅助审计 |
| 动效 | 既有卷宗编排；图表独立进入，reduced-motion关动画 | 真正慢网络下阶段空态与加载提示可优化 |
| 微交互 | 联想、显式窗口、aria-pressed复权、原值定位、引用对话框 | 统一供应商口径差异的就地注释 |
| 响应式 | ResizeObserver、窄屏图高缩减、原值表内部滚动 | 更多浏览器/触屏键盘专项验收 |
| 原创性 | 图表作为证据展品和cell验证链，不是行情仪表盘 | 以真实研究问题评审叙事可读性，不靠更多动画堆砌 |

## 10. 已知限制与P1建议

1. 三标的数据只有19个交易日；三年窗口接口能力不等于三年真实样本验收。新接线实时取数路径仍需独立验证当前免费源稳定性与长窗口预算。
2. 回溯财报可能在2025年重述，财务PARTIAL PIT，股本无公告日期为UNAVAILABLE PIT；未知授权默认禁止raw对外分享/导出。无确认独立来源族，不能凑VERIFIED。
3. share basis为`total_issued_shares_parent_aggregate_not_ordinary_eps`。银行归母总权益含699.44亿元其他权益工具，缺优先/永续分配，不冒称普通股EPS/可比普通股估值；供应商口径差异分列而非平均。
4. 无冻结基准/利率输入，不静默写零；不能保证新闻/公告语义研究闭环，也未做策略回测、选股、预测、目标价、交易、实时。
5. 本批没有新增公网鉴权体系/商业数据权益；当前Vite/esbuild安全警报需部署前修复。受控演示仅回环地址。
6. 同环境3.13 bytes复现已验；跨OS未做。3.11只验无量化依赖启动，旧cancel挂起历史限制不据此宣称已解决。
7. 初次http-real-01因执行中编辑代码触发代码树锁拒绝，初次UI入口因成稿轮询缺失失败；均保留证据，不覆盖或拿失败包作最终包。

建议保持P0数据门禁整改优先；只有长窗口、PIT/授权、普通股财务口径与生产部署基线获确认后，才进入P1单因子/回测。本批停止在E/F，等待用户检查。
