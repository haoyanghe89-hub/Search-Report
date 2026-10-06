# Task M：P0-A / P0-B 数据底座交付

日期：2026-10-04。依据 Task L 第7、8、14.1、16、17章及 Task M 原始要求。本批没有指标计算、回测、图表、交易、选股、目标价、预测、实时功能；没有进入 P0-C。

## 1. 交付结论与验收边界

P0-A/B 实现已落盘：不可变契约与权益策略、有效期证券主数据/市场规则、可录制重放数据端口、隔离 SDK 适配器、单位与 PIT 标记、源间核对、冻结 Parquet/manifest、SQLite 元数据与共享所有权、独立 DuckDB 只读查询、可选 quant 依赖、双 Python CI。

三个普通沪深标的完成真实网络取数与冻结：平安银行000001、贵州茅台600519、美的集团000333。最终得到20份快照、48个Parquet分区，独立断网审计全部读回且标 stale。未知数据授权禁止 raw_export / external_share。

验收没有全部冒称绿色：Python3.13全量591通过；Python3.11无quant启动、25个量化无依赖单测与1个迁移测试通过，但额外完整旧业务回归在旧取消恢复用例挂起。授权环境与单例均复现；已保存完整线程栈并停止测试进程，未越过本批范围改旧取消逻辑。深层根因仍未证实。CI两条已配置但未推送运行，尤其不能据本地导入检查宣称3.11完整异步行为兼容。

未对运行中的数据库执行迁移，未重启现有前后端，未提交或覆盖已有未提交改动。检查通过后是否应用新迁移由用户决定。

## 2. 本批文件清单

以下路径均相对 `D:/deepsearch/`，只列本批，不把之前任务的脏工作树变更算入本次。

|类别|文件|
|---|---|
|契约|`src/marketpulse/quant/__init__.py`, `domain.py`, `contracts.py`|
|主数据/日历|`src/marketpulse/quant/data/__init__.py`, `instruments.py`, `calendar.py`|
|数据接入|`src/marketpulse/quant/data/base.py`, `worker.py`, `baostock_adapter.py`, `akshare_adapter.py`, `tushare_adapter.py`|
|口径与质量|`src/marketpulse/quant/data/normalize.py`, `quality.py`, `pit.py`, `adjustments.py`|
|录制/回放/降级|`src/marketpulse/quant/data/recording.py`, `service.py`|
|冻结存储|`src/marketpulse/quant/storage/__init__.py`, `models.py`, `snapshots.py`, `reader.py`|
|迁移|`migrations/versions/20261004_08_quant_data.py`；增量修改 `migrations/env.py` 注册轻量元数据|
|旧存储集成|增量修改 `src/marketpulse/investigation/persistence/models.py`：注册量化表；`investigation/deletion.py`：无量化记录不增加零计数响应字段|
|依赖/CI|`pyproject.toml` 新 quant extra，`uv.lock` 锁定新增依赖；`.github/workflows/quant-data.yml` 两条独立环境全量任务及15分钟超时|
|单测|`tests/unit/quant/test_contracts_data.py`, `test_adapters_recording.py`|
|集成测试|`tests/integration/quant/test_snapshots.py`|
|实测/离线审计|`scripts/verify_quant_data.py`, `scripts/audit_quant_snapshot.py`|
|文档/派生证据|`docs/quant-dev-journal.md`, `docs/quant-task-m-evidence.json`, 本文|

前端与既有HTTP默认响应/枚举/错误结构未改变；旧结论、引用、来源独立性、验证 profile 与报告组装未改动。

## 3. 契约与证券主数据

`FrozenModel` 统一 Pydantic `frozen=True, extra='forbid'`。集合为 tuple，记录与元数据为 canonical JSON字符串，避免浅冻结对象中的可变 dict/list。主要模型：

- `DataRequest`：内部 `ins_*` IDs、dataset、start/end、时区感知asof、raw/qfq/hfq、明确复权anchor、fields、rights scope、schema/normalizer版本、complete_sessions_only、可选明确snapshot_id。日期有序、范围≤1096天、end不超过中国时区asof；复权anchor不得早于end或晚于asof。
- `Instrument`：稳定内部实体ID；有效期 exchange+code 别名；上市/退市、板块、状态有效期、规则有效期、生命周期来源与PIT。别名重叠冲突拒绝，代码重用应分配另一个实体ID及不重叠生命周期，不以六位代码作唯一键。
- `TradingRule`：version、exchange、board、status、effective_from/to、settlement_days（A股T+1）、source。规则/状态必须按指定日期解析，缺失状态不自动当 normal；没有明确版本规则则拒绝。不会据此发出交易指令。
- `DataRights`：policy_id、provider/upstream、entitlement、attribution、scope、expires_at、license_reference、raw_export/external_share。`DataRightsPolicy.allows` 检查未知授权、scope、到期与明确许可；默认全拒绝导出/分享。当前没有新增公网下载或分享接口。
- `DataResult`：请求、供应商/上游、family/lineage、原始与标准化行、单位、质量标志、PIT、权益、因子hash、核对记录、日历/证券/因子口径证据。
- `DatasetSnapshot`：snapshot_id、semantic/request hash、冻结result、分区引用、manifest_ref、行数、冻结时间及读取时stale。`MetricSpec`仅预留，无计算实现。

证券定义的SQLite初始记录不可修改；新观察/版本应以追加的instrument_master等快照保留，不覆盖老卷宗的定义。证券状态历史模型已具备，但本批没有自动构建全市场ST/停牌状态宇宙。

日历以实际录制的 BaoStock `query_trade_dates` 区间为依据，再与 exchange_calendars XSHG候选比对。实测区间未发现差异；这不是未来节假日权威性证明。任何超出显式验证范围的session都拒绝。当前未收盘bar标provisional，默认过滤；complete-only快照再次拒绝provisional行。

## 4. 可插拔端口、录制与降级

```text
DataRequest + CallContext(logical_key, ordinal, attempt, budget_seconds)
  -> 明确/唯一冻结快照（校验manifest与全部blob）
  -> RecordingQuantDataPort
       -> BaoStock隔离SDK进程
       -> AkShare Tencent隔离进程
       -> AkShare Eastmoney隔离进程
  -> 源切换轨迹 + 重叠OHLC/volume核对（冲突不平均）
  -> SnapshotStore.freeze -> SQLite metadata + Parquet CAS + manifest
```

`QuantDataPort`/`QuantAdapter` 为 Protocol，适配器无需依赖 investigation 编排。`recorded_chain` 规定P0优先序；`FrozenDataService`只接收录制端口。SDK适配器拒绝裸调fetch；worker是SDK唯一边界，一进程一个BaoStock会话，查询串行、finally logout，硬预算取消/超时杀进程并等待退出。stdout16MiB、stderr1MiB分块限额。

`MemoryCallJournal`用于单测，`FileCallJournal`用于跨进程回放：身份hash路径、不可覆盖hard-link发布、fsync、内容SHA256；录制成功与失败类型，文件IO在线程中。`ReplayQuantDataPort`必须同logical identity且request hash相同；记录失败重放为失败，不重新调用供应商。

降级/核对轨迹保存provider/upstream/asof/adjustment/units。主源不可用后下一源成为主源，随后仍对另一可用源做重叠核对；冲突或无重叠标claims_paused，不生成平均行情、不升级来源独立性。两家API核对一致仍为 `independence=UNVERIFIED` / unknown_market_feed，现有独立性与VERIFIED/PROBABLE/UNVERIFIED标准不变。

冻结优先不会每次抓“最新”。同一请求只有一份冻结内容才能自动命中；多份时必须明确snapshot_id。指定快照与完整请求不符则拒绝，不回退到别的latest。offline=True不调用SDK；内容损坏时不把损坏快照当缓存命中。

BaoStock支持日线raw、锚定qfq/hfq、交易/ST字段、PE TTM/PB MRQ、季度利润财务pubDate/statDate、复权因子、日历及基础证券信息。AkShare腾讯用于日线核对、东财日线降级及估值补充、新浪摘要可插拔。Tushare仅预留接口，未装SDK、未接账号。

## 5. 单位、复权和PIT口径

- BaoStock空串→null；金融股毛利率/主营收入不填0。日期统一ISO，normalized Parquet的date/period_end/published_at为date32；证券代码保留字符串。
- 成交量统一股、成交金额人民币元、换手率/涨跌幅比例。东财日线手→股、百分数→比例。锁定版AkShare腾讯内部对部分symbol已经换算股、但排除sz000/sh688等前缀：worker给出明确source_units，禁止再统一乘100。实测三标的价格/量核对无冲突。
- 东财stock_value_em的总市值为元、总股本为股，不乘万/亿；依据[AKShare官方字段表](https://akshare.akfamily.xyz/data/stock/stock.html)。新浪宽表无可靠统一单位与公告时间，未知单位明确unknown，不作为严格PIT财务输入。
- BaoStock复权日线从raw及冻结至anchor的因子历史重建，qfq rebasing至anchor；hfq保留供应商累计因子口径。因子history/hash进入provenance和cache key。不用今天供应商latest替代历史anchor；无法证明anchor的AkShare复权备用请求拒绝。PE/PB仍是供应商raw口径，不由复权价格重新计算。
- `STRICT/PARTIAL/UNAVAILABLE`枚举保留；当前公有接口没有已归档原始修订链证明，日线/因子/有pubDate财务只标PARTIAL，东财估值与新浪无公告时间财务标UNAVAILABLE。本批不产出STRICT或已验证投资结论。date-only pubDate保守到下一已核对session开盘可见，记录first_seen/revision unknown/statement_basis/source_hash；它仍不能排除后来重述。
- 成功返回的空因子窗口标 `no_actions_in_range`，写带schema的零行Parquet；它区别于网络失败、空日线与未知财务。

## 6. 元数据、分区与冻结manifest

实际head先用Alembic ScriptDirectory查为20261002_07，新迁移 `20261004_08` 的down_revision明确为20261002_07。迁移自身固定列定义，不引用未来可变ORM；SQLite/PostgreSQL保护证券与dataset表不允许UPDATE/DELETE。迁移升降级验证保留旧表/旧数据；未施加到正在运行的数据库。

三张新表：

1. `inv_quant_instrument`：instrument_id PK，market/exchange/currency/timezone，带有效期别名/状态/规则/生命周期的definition JSON。
2. `inv_quant_dataset_snapshot`：snapshot_id PK，semantic_hash UNIQUE，cache/request索引，provider/upstream/family/lineage、retrieved_at/asof、PIT/rightspolicy、schema/normalizer版本、row_count/quality_flags、manifest_ref、partitions、仅元数据的frozen_payload。SQLite不存完整raw/normalized行流。
3. `inv_quant_snapshot_ownership`：investigation_id+snapshot_id复合PK/FK、rights_scope、retention_until。删一个卷宗仅删其所有权，共享快照与其他卷宗引用保留；没有强制清除全局快照的危险GC。

逻辑内容分区 `layer(raw|normalized)/market(CN)/dataset/year`；物理文件沿用 LocalContentAddressedBlobStorage 的 `sha256/aa/bb/<digest>`，URI `blob://sha256/<digest>`，无每bar一个blob。每分区有row_count/hash/ref。Parquet内部ordinal/canonical JSON列保证原字段类型/顺序精确重放，DuckDB视图排除内部列。

manifest v2：version、semantic_hash、cache_key、request_hash、result元信息（含权益/单位/PIT/质量/口径）、raw/normalized行流hash、全部分区refs+hash、row_count。读取先验manifest和分区bytes，再验行数、行流hash及语义hash。Parquet重写版本变化可能产新bytes/hash，但不覆盖旧快照。

cache key涵盖provider/upstream、universe、dataset/range/asof、adjustment/anchor及factorhash、fields、schema/normalizer、权益scope/许可对象。默认schema/normalizer版本为2。

freeze使用SQLite BEGIN IMMEDIATE覆盖blob发布到metadata提交，与旧卷宗GC同写锁避免同hash竞态。保守保留无所有权的全局dataset快照；其自动过期/清除不是本批功能。DuckDB每次查询独立临时catalog再以read_only=True打开，参数化固定SQL、128MB/1 thread、≤5000行；禁自动装/载扩展，不做共享写库，不在HTTP事件循环执行科学查询。

估值SDK会返回全历史响应，因此raw原始响应比请求区间更宽（最终48而非每快照固定2个分区）；normalized只保留请求日期与asof允许的范围，raw不直接进入计算或报告。这种上游过取明确保留，PIT仍为UNAVAILABLE。

## 7. 真实数据与离线证据

最终目录：`D:/deepsearch/.phase3-quant-m/live-04/`；原始数据为内部研究私有证据，不提交/分享。前3轮保留供追查，但最终验收以live-04及离线审计为准。

|标的|日期范围|raw行数|BaoStock/腾讯重叠|核对结果|qfq/hfq|离线|
|---|---|---:|---:|---|---|---|
|000001 平安银行|2024-05-20～2024-06-14|19|19|MATCH，未证明源独立|各19行冻结|同ID命中、stale|
|600519 贵州茅台|同上|19|19|MATCH，未证明源独立|各19行冻结|同ID命中、stale|
|000333 美的集团|同上|19|19|MATCH，未证明源独立|各19行冻结|同ID命中、stale|

额外：三份日历、三份证券基础快照；平安2024-06-14因子事件1行（分红窗口），另两只该窗口无事件，零行冻结；平安2024Q1财务1行，pubDate2024-04-20、available_at2024-04-22T09:30:00+08:00、银行毛利率null；东财估值19行/PIT UNAVAILABLE。

可核查证据：

- [派生离线审计JSON](D:/deepsearch/docs/quant-task-m-evidence.json)：20快照/48分区，全部SHA256验证，禁止网络和SDK后全命中stale，权益导出/分享false。
- 私有真实取数汇总：`D:/deepsearch/.phase3-quant-m/live-04/summary.json`。
- 私有metadata：`D:/deepsearch/.phase3-quant-m/live-04/metadata.sqlite`；blob根同目录`blobs/`；23份录制调用在`calls/`。
- 早期问题：live-01成交量100倍冲突和复权KeyError、live-02金融可见日历拒绝、live-03修正后证据，均未覆盖。

复现命令（PowerShell，从项目根运行；必须新output目录避免录制身份覆盖）：

```powershell
$env:UV_PROJECT_ENVIRONMENT='D:/deepsearch/.phase3-quant-m/venv313'
uv sync --python 3.13 --locked --extra dev --extra web --extra server --extra quant
.phase3-quant-m/venv313/Scripts/python.exe scripts/verify_quant_data.py --output .phase3-quant-m/new-live --supplementary
.phase3-quant-m/venv313/Scripts/python.exe scripts/audit_quant_snapshot.py --root .phase3-quant-m/new-live --output .phase3-quant-m/new-offline-audit.json
```

## 8. 验证结果与命令

|验收|结果|证据|
|---|---|---|
|3.13 quant+旧后端全量，不调用真实外部服务|591 passed / 3 skipped / 7 deselected|`.phase3-quant-m/final-full313.xml`|
|3.13 quant单元/集成+旧迁移|33 passed（32 quant + 1 migration）|`.phase3-quant-m/final-quant.xml`|
|3.11无quant依赖：quant无依赖单测+迁移|26 passed|`.phase3-quant-m/final-base311.xml`|
|3.11无quant启动导入|通过，确认七种量化包都不在环境|本机命令实测|
|3.11旧服务创建/无密钥/回放报告冒烟|4 passed|`test_investigation_server.py`独立运行|
|3.13启动不导入SDK|通过，包版本实测锁定|本机命令实测|
|Ruff|本批及旧存储接入文件通过|下列命令|
|git diff --check|通过，仅既有LF/CRLF提示|下列命令|
|3.11额外旧业务全量|未通过验收：取消恢复用例挂起，停止而非伪造pass|`.phase3-quant-m/cancel311-diagnostic.log`|

3跳过为Windows符号链接权限/仅POSIX信号用例；7排除为live/infrastructure，真实数据联网另行实测，未运行DeepSeek联网调查或PostgreSQL/Redis基础设施用例。

```powershell
.phase3-quant-m/venv313/Scripts/python.exe -m pytest tests -m 'not live and not infrastructure' --basetemp=.phase3-quant-m/final-full313 -p no:cacheprovider -q --junitxml=.phase3-quant-m/final-full313.xml
.phase3-quant-m/venv313/Scripts/python.exe -m pytest tests/unit/quant tests/integration/quant tests/integration/investigation/test_migrations.py --basetemp=.phase3-quant-m/final-quant -p no:cacheprovider -q --junitxml=.phase3-quant-m/final-quant.xml
.phase3-quant-m/venv311/Scripts/python.exe -m pytest tests/unit/quant tests/integration/investigation/test_migrations.py --basetemp=.phase3-quant-m/final-base311 -p no:cacheprovider -q --junitxml=.phase3-quant-m/final-base311.xml
.phase3-quant-m/venv313/Scripts/ruff.exe check src/marketpulse/quant tests/unit/quant tests/integration/quant scripts/verify_quant_data.py scripts/audit_quant_snapshot.py migrations/versions/20261004_08_quant_data.py migrations/env.py src/marketpulse/investigation/deletion.py
git diff --check
```

覆盖契约/冻结、权益fail-closed、别名生命周期、单位空值、公告PIT、版本规则、provisional/日历越界、qfq/hfq多行锚点、录制重放/篡改/超时、分区/manifest、hash损坏、明确ID不被latest替换、来源降级与冲突不平均、共享所有权删除、无事件零行表。

## 9. 依赖与仍存限制

quant extra实际锁定：pandas3.0.6、numpy2.5.3、pyarrow25.0.1、duckdb1.5.6、akshare1.19.1、baostock0.9.4、exchange-calendars4.13.2。科学包只在Python≥3.12 marker下安装；推荐独立3.13 worker，原项目继续支持3.11且未装quant也能启动。实测3.13.13/3.11.15，不替换运行中的旧.venv。

仍存限制：

- 3.11 Windows旧取消请求挂起；只定位到调用/等待边界，未修复，不能宣称3.11完整回归通过。
- 公共数据权益/来源独立性/历史修订链未证明；不可raw导出或对外分享，也不能凭本批快照发布严格PIT投研结论。
- 腾讯字段单位逻辑针对锁定版；升级SDK必须重新核对接口和回归，不复用旧单位假设。缺少anchor证明时不使用AkShare复权数据替代BaoStock。
- 仅季度利润核心字段，不是完整三大财务报表；新浪未知单位摘要仅补充。全市场生命周期、ST/停牌宇宙与官方未来日历未建设。
- 自动清除全局快照、量化作业/计算证据/HTTP端点/前端图表均未建设；不是本批遗漏后继续偷偷实施的功能。
- CI为Linux双环境配置，本机Windows执行证据不能替代远端CI。没有发布、自动交易或新公网导出。

## 10. 开发日志要点与停止点

[开发日志](D:/deepsearch/docs/quant-dev-journal.md) 在子项完成及真实问题发现后持续追加，记录：冻结容器、有效期ID、依赖Python marker/缓存权限、供应商空值/单位、复权闭包与锚点、公告日历范围、Parquet不进SQLite、GC写锁、零事件语义、Windows断网故障注入、3.11旧取消挂起。日志含现象、定位、关键修正与可复用经验，没有把失败证据改成成功。

停止点：P0-A/B数据底座及其验收材料；等待用户检查。未进入 P0-C；旧3.11取消问题如需修复，必须先明确扩展任务范围。
