# Task N：P0-C / P0-D 交付与验收记录

日期：2026-10-04。实现依据：`v8-taskL-quant-evolution-plan.md` 第8、10、11、13、14.1章、已批准的量化P0实施计划及 `quant-dev-journal.md`。

## 1. 结论与边界

本批已落盘确定性计算、有界执行、计算证据、验证门禁和内部报告集成，没有进入 P0-E/F，没有增加前端图表、对外HTTP接口、自动交易、选股、目标价、预测或实时处理。未新增付费报告调用，未重启现有服务，未迁移现有业务数据库，未提交Git。

额度恢复后已修复hfq测试anchor，并通过BaoStock/AkShare录制适配器补取三标的真实财务、历史总/流通股本。独立PE/PB、平均归母总权益ROE和可比财务趋势不再为null；均从新冻结快照确定性算出。旧`.phase3-quant-m/live-04`未覆盖。这里的独立指公式不使用供应商PE/PB倒推，不表示已有独立来源族或STRICT PIT。

算法正确性另由明确标识的合成冻结财务、手算值和篡改测试证明；这些测试没有用于填补真实财务。三份真实报告仍“部分完整”，所有数值观察UNVERIFIED，没有自动PROBABLE或VERIFIED。免费数据由当前接口回溯，含2025年的历史重述；股本无公告日期；授权、独立来源族和市场规则尚未齐备。**尚不能宣布严格历史可知性或对外发布验收完成。**

## 2. 本批文件

以下是Task N工作范围，不是当前脏工作区全部Git diff；既有A–M前端/业务改动被保留。

### 新增

| 工作包 | 文件（相对项目根） |
|---|---|
| 纯计算 | `src/marketpulse/quant/compute/__init__.py`、`metrics.py`、`valuation.py`、`financials.py`、`indicators.py`、`engine.py` |
| 执行 | `src/marketpulse/quant/execution/__init__.py`、`worker.py`、`limits.py`、`environment.py`、`service.py`、`recording.py` |
| 证据/验证/呈现 | `src/marketpulse/quant/evidence.py`、`validation.py`、`reporting.py`、`citations.py` |
| 迁移 | `migrations/versions/20261004_09_quant_compute.py` |
| 单测 | `tests/unit/quant/test_compute_n.py`、`test_financial_indicators_n.py`、`test_reproduction_n.py` |
| 集成 | `tests/integration/quant/test_compute_report_n.py` |
| 离线证据生成 | `scripts/verify_quant_compute_n.py` |
| 财务规范化 | `src/marketpulse/quant/data/financial_normalize.py` |
| 真实补取/录制重放 | `scripts/supplement_quant_financial_n.py`、`scripts/finalize_quant_financial_n.py` |
| 财务同口径专项 | `tests/unit/quant/test_parent_financial_n.py`（5项） |
| 交付 | 本文档 |

### 增量修改

- `quant/domain.py`、`contracts.py`：补全计算契约及导出；`quant/storage/models.py`：计算job/产物/录制/报告材料/引用ORM。
- `investigation/validation/profiles.py`：新增计算证据静态评估入口，原网页评估不变。
- `investigation/reporting/models.py`、`assembler.py`、`citations.py`、`validation.py`：可选v2量化语义、计算引用与数值只读校验。
- `investigation/reporting/writer.py`、`chinese_writer.py`、`pipeline.py`、`renderer.py`、`persistence.py`：确定性追加投研块、量化v2哈希/落库/折叠附录。
- `investigation/feedback/orchestrator.py`、`live_runtime.py`：内部显式量化路线、恢复/取消/收尾。
- `docs/quant-dev-journal.md`：按P0-C/P0-D持续追加真实问题记录。
- `quant/data/worker.py`、`base.py`、`normalize.py`：显式Eastmoney财报请求、原生字段审计与版本化归母总额规范化；v2不改。`compute/financials.py`允许同口径合并收入同比，但归母TTM仍要求parent，不混同两者。

少量相邻文件经过Ruff机械格式化；没有以重构名义修改旧HTTP默认响应、枚举或网页验证政策。

## 3. 计算契约和口径

`MetricSpec / PricePoint / PriceSeries / FinancialFact / MetricValue / ComputeInput / ArtifactBundle` 均frozen、extra=forbid。Decimal用规范定点字符串编码，不依赖调用者的Decimal上下文，不在计算阶段使用展示舍入值。`value=null`必须带`missing_reason`，非空值不能带缺值原因。schema hash锁定输入、输出及嵌套契约。

| 项目 | 实际实现 |
|---|---|
| 日收益 | `P[t]/P[t-1]-1`；首日null并注明first_observation，坐标含交易日 |
| 区间收益 | `last/first-1`；缺日传播，不删坏日；raw价格收益不含现金分红 |
| CAGR | 按实际日历历时与显式365.2425天/年折算；短窗口年化不代表预测 |
| 波动率 | 日收益样本标准差ddof=1乘sqrt(annual_sessions)，默认252写入spec/定义 |
| 回撤 | running peak计算；固定峰、谷及首次恢复日期；未恢复保持null |
| 停牌 | 显式carry_forward或reject；缺少首个可用价不补0 |
| PE/PB | 只用raw价格×当时总股数；同share_basis；TTM归母利润/归母权益；单位、版本、期末、总市值口径进入定义/manifest；亏损PE不适用 |
| ROE | TTM归母利润/平均期初期末归母权益；校验利润与权益期间、单位及股本口径；披露ROE独立标记 |
| TTM | 明确TTM、四个连续离散季度，或前年度+本年YTD−上年同期YTD；不累加累计季度，不静默选歧义修订 |
| 财务趋势 | 同口径同报告期间同比；缺历史/基期非正/口径冲突返回null和原因 |
| SMA/EMA | 固定全窗口；EMA用SMA种子，alpha=2/(n+1)，缺值重置 |
| RSI14/MACD | Wilder RSI按n次变化初始化，平价全零变动返回有原因的null；MACD采用12/26/9，柱值不乘2；均仅辅助分析 |

当日15:00（上海时区）前的bar、provisional、重复交易日、混合证券或多份歧义日历拒绝。单期披露值绑定自己的财报期末或最后一个交易日，不借整段价格样本数冒充财报统计支持。没有为金融股套用EBITDA/毛利指标。

## 4. 执行、冻结与重放

调用链：

```text
内部编排 → QuantService.submit → CAS冻结ComputeInput → job租约
        → 固定Python worker → 纯计算 → output + manifest + ArtifactBundle
        → 租约fencing事务提交 + 调用录制 → 独立离线重算
        → ComputationEvidence / Validation → Claim → 报告v2
```

内部接口（需要真实run、证券及快照owner；不是新HTTP接口）：

```python
job_id = await service.submit(
    run_id=run_id, spec=MetricSpec(), inputs=tuple(snapshot_ids),
    instrument_id=instrument_id, asof=aware_datetime,
    idempotency_key="frozen-metrics", budget_seconds=30,
)
bundle = service.bundle_for(job_id)
reproduced = await service.reproduce(job_id=job_id)  # 禁止重新取数
```

- 唯一`(run_id, idempotency_key)`；同键换spec/输入/标的/asof拒绝。恢复沿用原input_ref，不使用runtime latest；attempt递增，已完成job复用完整产物。
- SQLite BEGIN IMMEDIATE串行领取/完成；lease_token防止过期worker提交。job输入意图不可更新；半产物不会成为COMPLETED。
- 固定子进程入口，无SDK/模型/SQL数值计算，禁止socket；不传播模型与供应商密钥。实际worker Python/依赖/平台必须与manifest一致。
- 输入24MiB、stdout8MiB、stderr64KiB，64KiB分块读取；超时上限120秒，默认30秒；取消/超时kill后wait，active_pids清空。
- 内存768MiB：Windows Job Object限制单进程与内存；POSIX RLIMIT_AS/CPU。限额不能建立则拒绝运行。
- 输入读取与环境捕获由线程承担；数值重算在子进程；量化报告最后的完整性核对与事务落库在工作线程。

manifest冻结：输入snapshot ID/semantic hash/CAS manifest/Parquet分区、请求/标准化版本/单位/许可/PIT/stale/上游/谱系/质量；证券规则与日历；完整spec与采样边界；基准/rf/fx引用（如有，必须在冻结输入中）；Git SHA+脏源码树hash、Python/平台/实际依赖+uv.lock hash；seed、schema hash与完整output hash。

输出排除job ID、提交时刻等运行噪声。同环境要求output bytes SHA256完全一致；跨环境先要求输入、定义、单位、日期、源码树及lock一致，再按spec检查：收益/回撤等绝对容差≤1e-10，PE/PB相对容差≤1e-8，不能通过spec放宽上限。当前跨环境误差检查有合成产物测试，尚未宣称完成真实跨操作系统复算。

录制保留logical_key、ordinal、attempt、input_hash、artifact或错误；回放必须匹配冻结调用与完整产物。源码树hash被记录，但本批不自动归档完整脏源码；以后要重现此环境须保留相应源码/lock，缺失时明确拒绝。

## 5. 数据库迁移与证据链

实际迁移为 `20261004_09`，`down_revision=20261004_08`（非猜测head）。新增：

| 表 | 职责 |
|---|---|
| inv_quant_compute_job | 幂等意图、输入CAS引用、状态、attempt与租约 |
| inv_quant_compute_artifact | 完整manifest/output/bundle CAS引用，内容不可变 |
| inv_quant_compute_record | 不可变调用录制CAS引用 |
| inv_quant_report_material | run绑定、v2语义hash、量化报告材料与最新验证 |
| inv_quant_citation | report绑定的计算引用payload，保留旧文本Citation表约束 |

产物全局内容寻址，可被多个job共享，不随一个job删除而误删。不可变表仍兼容既有归档删除的限定permit。迁移仅应用于pytest私有数据库及离线验收副本，未应用于正在使用的业务DB。首发验收路径是SQLite；PostgreSQL专项环境未配置，不能把跳过记成通过。

`ComputationEvidence`绑定artifact/output/manifest/input hash、`/values/N`、row_keys、value、unit、definition、标的、时间与asof。cell_hash覆盖完整MetricValue和所有关联语义，不是只对展示数字哈希。

```text
真实Claim → latest ValidationResult → 冻结报告材料
    → 完整Artifact/CAS输入 → metric_path / cell_hash → v2计算Citation
```

报告引用时再次校验最新Claim/Validation、run/job/owner、产物bytes及输入CAS，不能只信历史验证缓存。改变输入/输出hash、单位、时间、producer包装或只读正文被拒；验证之后破坏输入也产生HARD引用完整性问题。

QuantitativeProfile新增计算分支。样本、手算校验、独立原始来源族、质量、重要性门槛、许可、STRICT PIT、冲突、stale、日历与市场规则任一不足：UNVERIFIED，不自动PROBABLE。高重要性价格/财务分别满足来源门槛，不能把不同数据类型的供应商数量相加。镜像/SDK包装不成为新独立来源。

## 6. v1兼容与报告集成

- 无量化材料时，可选字段在序列化中完全省略，旧v1 payload/hash、文本引用与旧网页15阶段政策保持不变；原fixture和全量回归覆盖此路径。
- 有量化材料时使用`quant-report-input-v2`、`quant-report-writer-v2`、`quant-report-v2`、`computation-citation-v2`及独立哈希域。job运行ID不进入量化语义hash。
- 数值声明由冻结单元格的确定性模板产生。模型writer投影排除量化声明，不接收数值重写任务；报告校验要求整句等于只读模板，不能追加虚构99%后靠原句子串通过。
- 旧probable/disputed结论速览检查和确定性发布policy继续执行；unknown rights需要审核，含未证实量化材料的完整发布被拦截。
- 量化纯报告保留answer-first，空章不渲染，局限与建议按语义合并，事实仅出现一次；技术诊断与方法默认折叠。混合报告保留已有网页事实。
- `AgentFeedbackOrchestrator.run_quant`与`LiveInvestigationService.start_quant`为内部显式入口；服务器默认不注入quant_service，没有对外API或新付费调用。quant-v1恢复读取原冻结job，不误入网页Agent。
- 量化取消使用同一报告优先收尾；只有报告事务持久化后run才COMPLETED。报告与最小收尾都失败时保留BLOCKED/REPORT checkpoint，不能只因计算job结束就宣布完成。

原离线价格验收报告的结构为6个非空结构化章节，Markdown另有引用索引；以下旧计数作为补财务前对照，最终计数见第7节新证据：

| 章节 | 平安银行条目 | 美的/茅台条目 |
|---|---:|---:|
| 结论速览 | 1 | 1 |
| 证据基础/口径 | 2 | 2 |
| 量化发现与统计口径 | 8 | 6 |
| 局限与后续建议 | 4 | 3 |
| 调查问题与方法（折叠） | 2 | 2 |
| 技术诊断与方法说明（折叠） | 1 | 1 |

## 7. 真实离线复算

源：`.phase3-quant-m/live-04`；只读SQLite backup及CAS复制到 `.phase3-quant-n/offline-04` 后迁移副本。主验收禁止外部连接，worker禁止socket。没有实时SDK补数或伪造财务。

以下为最初价格验收。2026-10-04补财务后的最终验收改用`.phase3-quant-n/financial-frozen-02`，网络只用于采集阶段；离线复算阶段仍禁止连接。

窗口2024-05-20至2024-06-14，共19个完整交易日，raw价格。包含平安银行分红窗口，故下表不代表含分红总回报或策略收益。

| 标的 | 价格收益 | 年化波动（252） | 最大回撤 | 未恢复 | 声明状态/引用 |
|---|---:|---:|---:|---|---|
| 平安银行000001 | -10.5448% | 25.5710% | -11.9377% | recovery=null | 8 UNVERIFIED / 8 |
| 美的集团000333 | -1.4421% | 22.4212% | -5.4298% | recovery=null | 6 UNVERIFIED / 6 |
| 贵州茅台600519 | -9.0111% | 13.7873% | -9.0111% | recovery=null | 6 UNVERIFIED / 6 |

三个输出同环境独立重算bytes hash一致，单元格单位篡改拒绝。完整Decimal、采样、峰谷/恢复、manifest/output hash与每条缺值原因见机器证据，不以表格的展示舍入值参与计算。

证据路径（均本机私有数据，不表示获准外部分享）：

- `.phase3-quant-n/offline-04/summary.json`：三标的输出摘要、状态、章节、引用、缺值。
- 同目录`artifact-0/1/2.json`：完整产物，包含manifest_json/output_json/MetricValue。
- 同目录`report-0/1/2.md`与`.json`：真实渲染报告及引用cell坐标。
- 同目录`metadata.sqlite`及`blobs/`：副本数据库和冻结输入/输出CAS。

### 7.1 新的真实财务冻结与独立复算

Eastmoney利润表实际字段`PARENT_NETPROFIT / OPERATE_INCOME / CURRENCY / REPORT_DATE / NOTICE_DATE / UPDATE_DATE`，资产负债表`TOTAL_PARENT_EQUITY / OTHER_EQUITY_TOOL`，历史估值`总股本 / 流通股本 / PE(TTM) / 市净率`。报表金额使用原生CNY元，股数为share；不使用资产负债表金额科目SHARE_CAPITAL充当股数。接口与字段审计参照[AKShare官方文档](https://akshare.akfamily.xyz/data/stock/stock.html)。

每家公司新规范化2份财报各9期（2022Q1至2024Q1），股本/估值19日。`financial-frozen-02`保留53份快照：旧v2及补取26、原生v3 9、第一版规范化9、最终3-parent-2 9。计算只选最后9份新财务/股本、一个扩展日历和原M raw价格，不混入旧财务重复版本。

| 标的 | 独立PE（倍） | 独立PB（倍） | TTM平均归母总权益ROE | 2024Q1归母净利同比 | 合并营业收入同比 |
|---|---:|---:|---:|---:|---:|
| 平安银行000001 | 4.22255525 | 0.40684104 | 10.0362% | 2.2600% | -14.0317% |
| 美的集团000333 | 13.19711194 | 2.65306697 | 21.3501% | 11.9146% | 10.2206% |
| 贵州茅台600519 | 25.04200145 | 8.14822103 | 34.0625% | 15.7268% | 18.1127% |

估值价格/股数时点为2024-06-14；权益报告期2024-03-31；TTM为2023-04-01至2024-03-31：2023全年+2024Q1累计−2023Q1累计。平均权益用真实2023Q1/2024Q1归母权益；同比使用相同累计期间。所有展示舍入值不参与计算。

股本口径明确为`total_issued_shares_parent_aggregate_not_ordinary_eps`：原始价格×当日总发行股数 / 归母总利润或总权益。银行2024Q1其他权益工具699.44亿元，独立PB的分母包含它；供应商PB约0.47530567，相对差约-14.4043%，不是价格抓取差异。优先/永续分配调整尚无输入，未伪造扣减；本口径不是普通股EPS或普通股股东ROE，不用于跨公司估值排名。美的/茅台独立PE/PB与披露值差异接近展示精度，仍分别保留，不视为供应商核验已通过。

财报PARTIAL PIT、股本UNAVAILABLE PIT；NOTICE_DATE映射下一已核对交易日的保守可用标签，不能证明当时已知修订。利润表2024Q1存在2025年UPDATE_DATE，结果是冻结的回溯观察，不是假装2024年原版。股本没有公告日期，保留null及quality标记，不伪造日期。

新证据：`financial-live-03/fetch-summary.json`和calls（实际成功/失败SDK录制）；`financial-frozen-01/financial-summary.json`（缺失项重试）；`financial-frozen-02/financial-summary.json`和calls（离线raw重放、原快照绑定）。最终复算、报告、cell引用索引在`offline-financial-02/`，含summary、artifact、report、citations以及副本DB/CAS。

最终三标的收益/回撤绝对复算差均0，PE/PB相对复算差均0；同环境output bytes hash一致，单位篡改均拒绝。没有用跨环境容差掩盖同环境差异。真实跨OS/跨环境验收仍未执行，容差规则由单测覆盖。

三份最终报告各6个非空章节：结论速览1、证据基础2、量化观察17、局限与后续3、方法折叠附录2、技术折叠附录1，17条COMPUTATION_CELL引用、17条UNVERIFIED。相较补财务前，数值观察从8/6/6增加至17/17/17，局限从4/3/3聚合为3/3/3；不增加独立来源族。BaoStock与东方财富披露值和相对差异以来源名称区分，其完整精度/日期/cell hash分别保留，不把两个包装来源当成独立财务证明。

## 8. 验证命令与结果

最终quant 79 passed / 130.61s；最终全量638 passed / 6 skipped / 4 deselected / 1 warning / 545.64s，exit 0。证据分别为`final-parent-quant-02.xml`、`final-parent-all313-02.xml`。首轮全量也638 passed /585.09s，不替代最终一轮。下面命令使用不同basetemp，禁pytest缓存，不复用既有数据库。

```powershell
.phase3-quant-m/venv313/Scripts/python.exe -m pytest tests/unit/quant tests/integration/quant -q --basetemp .phase3-quant-n/final-parent-quant-02 -p no:cacheprovider --junitxml=.phase3-quant-n/final-parent-quant-02.xml
.phase3-quant-m/venv313/Scripts/python.exe -m pytest tests -q -m "not live" --basetemp .phase3-quant-n/final-parent-all313-02 -p no:cacheprovider --junitxml=.phase3-quant-n/final-parent-all313-02.xml
.phase3-quant-m/venv313/Scripts/ruff.exe check src tests migrations scripts/verify_quant_compute_n.py scripts/supplement_quant_financial_n.py scripts/finalize_quant_financial_n.py
git diff --check
.phase3-quant-m/venv313/Scripts/python.exe scripts/verify_quant_compute_n.py --source .phase3-quant-n/financial-frozen-02 --output .phase3-quant-n/offline-financial-02
```

4个live测试需要真实网络/模型密钥且可能产生费用，本批不运行；3个PostgreSQL/Redis测试因未配置专用测试服务跳过；Windows用户无symlink权限的2项、POSIX SIGTERM的1项跳过。不会把这些未执行用例称为通过。

Python3.13导入全部37个quant子模块及旧server；Python3.11不安装任何7个quant可选依赖，旧server与quant核心仍可导入。Ruff和git diff --check为exit 0；Git有既有文件LF→CRLF警告，不是空白错误。M已记录的3.11旧TestClient取消挂起未在本批修复，本批不声称3.11全量异步行为全部通过。

## 9. Journal主要坑与剩余验收

即时日志详见 `quant-dev-journal.md` 的P0-C/P0-D：序列name覆盖row_keys；Decimal编码依赖上下文；财报PIT/share_basis不足；job与run终态区别；sidecar Claim外键；validation hash未绑定cell导致主键冲突；Windows精简环境丢架构字段；财报日期误继承价格窗口；空网页方法模板；验证到引用之间CAS再检查。

仍待用户检查/补充的真实验收条件：

1. 三标的同口径归母总额独立计算已完成；普通股EPS/扣优先永续分配、股本公告和当时原版修订档案仍缺，不能冒称全部已补齐。供应商披露值未用于倒推财务。
2. 真实授权、STRICT PIT、已核实来源族/quality、有效市场规则仍不足，不能升级VERIFIED或自动对外发布。
3. 原M窗口不是三年，本批未额外拉长历史。基准/rf/fx标准化接线、Beta/相关性没有提前扩展；缺项保留null，只有用户显式零rf假设可用于对应纯计算。
4. PostgreSQL/Redis、真实跨环境/跨OS复算、可移植源码归档尚未完成专项验收；非本批前端/API范围。

停在P0-C/D交付检查点，不继续P0-E/F。

## 10. 收尾结论

本次要求的两件事均已落实：hfq测试补合法冻结anchor而不修改校验；真实三标的新增冻结财报与股本，确定性独立归母总额PE/PB、ROE、财务同比完成，并与两家供应商披露值逐项分列。旧M 20份描述原样保留。最终三份产物绑定当前源码/lock/runtime；环境source_tree_hash为`2de961f0994b7b94dc47a0cfa1730a90f03377b47af30bea3ad198ea39e96469`。无新增迁移；本批计算迁移仍为09（08之后），仅对私有副本执行，未迁移业务数据库。

严谨边界：此处“完成”指计算、证据、报告和回归的工程收尾，不意味着补齐STRICT PIT、普通股分配调整或对外授权。历史股本无公告日期/首见版本，利润表有后期重述、银行归母总权益含其他权益工具，全部如实写入局限。未用模型或测试数值补真实数据，未放松VERIFIED，也没有把重复包装来源算作独立支持。等待用户检查，不推进后续批次。
