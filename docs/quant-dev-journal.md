# 量化数据底座开发日志

持续记录 Task M/N/O 的 P0-A 至 P0-F；不实现 P1 回测、选股或交易。现有未提交业务变更全部保留。

## P0-A / 2026-10-04

### 开工：迁移与环境边界
- 现象：现有迁移文件尚未提交，不能按 Git 历史推断 head；默认 uv 缓存读取被沙箱拒绝。
- 根因：工作树含已完成的前批实现；默认缓存位于工作区外。
- 解决：通过 `ScriptDirectory.from_config(Config('alembic.ini')).get_heads()` 实测 head 为 `20261002_07`；后续使用工作区内专用 uv 缓存，必要下载走明确授权的命令。只在临时数据库验迁移，不改正在运行的数据库。
- 经验：以当前迁移图而非提交记录决定 down_revision；可选依赖不得让旧服务启动时导入 pandas/SDK。

### 契约、主数据、录制端口落盘
- 现象：Pydantic frozen 包含 dict/list 时仍可间接修改；六位代码还会在退市后重用。
- 根因：浅冻结及代码/证券实体混淆。
- 解决：记录采用 canonical JSON 字符串、集合用 tuple；Instrument 使用 `ins_` 内部 ID，独立有效期别名、状态与规则；DataR equest 校验感知时区、区间、三年上限与复权锚点。录制端口用 logical_key/ordinal/attempt 拒绝重复身份、记录失败类型与预算，Replay 校验请求哈希。
- 经验：冻结的是输入内容而非 Python 容器表面；SDK 调用需在录制上下文内，未知权益默认拒绝导出/分享。

## P0-B / 2026-10-04

### 数据适配边界与标准化落盘
- 现象：已核实的 Task L 实测中 BaoStock 全字符串、金融股空毛利率；腾讯量为手而换手率为比例，BaoStock 量为股而换手率为百分数。
- 根因：供应商字段同名不等于单位同源；新浪宽表没有公告可见时间或可靠统一单位。
- 解决：SDK 单独进程、硬预算退出且登录/查询/退出串行；标准化显式手×100、百分数÷100、空值 null；新浪指标标 unknown unit/PIT UNAVAILABLE，BaoStock pubDate 标 PARTIAL 而非 STRICT。日历仅接受有来源的已核对区间；未来库日历不直接放行。
- 经验：不以非零填充换取指标完整，不把公告日期当原始历史版本证明；交叉核对不等于来源独立。

### 冻结存储与向后兼容落盘
- 现象：冻结 Parquet 不能按单日创建 blob；注册共享快照后，旧卷宗删除不能误删共享内容，也不能改变无量化数据时的响应。
- 根因：列式分区与内容寻址是不同层次；共享资产不等于卷宗私有子记录。
- 解决：raw/normalized 按 market/dataset/year 聚合写 Parquet，manifest 保存每分区 SHA256；三张轻量 metadata 表接入已有 Base，所有科学库仍延迟导入。所有权仅指向快照而不反向私有化快照；旧删除结果不新增零计数量化字段，GC 仍检查全局引用。新迁移为 `20261004_08 -> 20261002_07`，快照/证券表拒绝 UPDATE/DELETE。
- 经验：指定快照 ID 必须校验完整 request hash，不以 latest 替换；同请求多份冻结内容要求用户明确 pin；Parquet/DuckDB 操作不放进事件循环。

### 第一轮验证与复权锚点修正
- 现象：旧环境运行契约/迁移测试 `16 passed`；Ruff 报长行/未用导入，格式化后继续校验。依赖解析的普通网络调用报 Windows socket 10013。
- 根因：网络沙箱边界；另经审查发现直接请求供应商 qfq 会使用供应商当前锚点，与历史 request.anchor 不等价。
- 解决：授权的 `uv lock --cache-dir .uv-cache/task-m` 成功锁定 109 个包，quant 库只在 Python≥3.12 标记下解析，3.13 专用环境 `.phase3-quant-m/venv313` 安装。BaoStock 日线先取 raw、再冻结至 anchor 的因子，用明确锚点重建；没有因子历史的备用源拒绝复权请求，禁止用今天 latest 冒充历史。
- 经验：版本 marker 应与库支持的 Python 一致；qfq 的字符串参数并不是可重现的完整口径。实际测试包括 `--basetemp` 专用目录及 `-p no:cacheprovider`。

### 列式存储首轮验收与真实抓取启动
- 现象：3.13 quant 全依赖已安装，契约/冻结/降级首轮 `18 passed`；DuckDB 从独立只读 catalog 读取校验后的 Parquet 成功。内存日志不能跨进程重放。
- 根因：仅内存日志缺少持久化身份索引。
- 解决：补充 FileCallJournal，用原子 hard-link 禁止覆盖、调用内容 SHA256 验证与失败记录；开始三个标的真实验收，录制交易日历与证券上市信息，之后再冻结日线及复权。金融日期按下一已验证 session 开盘可见，同时保留 first_seen/revision unknown，仍只为 PARTIAL PIT。
- 经验：本地重放也必须匹配 logical identity 与请求 hash；“日历库无冲突”只证明核对通过，不是未来节假日权威性证明。东财估值单位经 [AKShare 官方说明](https://akshare.akfamily.xyz/data/stock/stock.html#id311) 核对为元/股，不能误乘万或亿。

### 真正实测暴露的两个错误（首轮数据不覆盖）
- 现象：首轮三只 raw 日线各 19 行已冻结/只读读取/断网命中。茅台腾讯量比 BaoStock 大 100 倍；qfq/hfq 第二根 bar 报 KeyError previous_close。
- 根因：锁定版 `akshare/stock_feature/stock_hist_tx.py:113` 已对大部分 symbol 把手乘100、但排除 sz000/sh688 等前缀；不能将平安银行 spike 的手单位推及所有标的。复权函数内循环的 field 复用了因子闭包变量。
- 解决：worker 随接口/版本输出 source_units，normalize 只按显式原单位换算；独立 factor_field 不被价格字段循环污染。补回归后另起 live-02 重跑，保留 live-01 冲突与失败调用证据，禁止平均或覆盖。
- 经验：源代码/版本级单位契约优先于泛化的“腾讯成交量都是手”；闭包捕获可变局部变量应特别测试多行序列。

### 第二轮核对与存储审查
- 现象：live-02 三只日线都达到19个重叠 session、无价格/量冲突；qfq/hfq 三只均成功。财务公告4月20日早于验收日历5月20日起点，严格校验拒绝推断。审查发现初版 SQLite payload 重复包含原始与标准化行。
- 根因：日历取数范围必须覆盖公告可见时间；SQLite 应只保存元数据而非完整时序副本。
- 解决：验收日历扩为2024年起，日线区间不变；存储 v2 把内容留在 Parquet，以内部 ordinal/canonical JSON 列保证精确回放及原字段类型，SQLite 与 manifest 仅保存描述和行流 hash。查询排除内部列。
- 经验：宁可拒绝未验证 session 也不猜公告可见时间；列式文件的排序/类型重建必须考虑原始记录精确重放。

### 第二层验收：旧业务隔离与故障回归
- 现象：Python3.11 无 numpy/akshare 的环境启动导入正常，契约/迁移16项通过；3.13 全量非联网后端首轮577通过、3个Windows/POSIX能力跳过、7个live/infrastructure排除；新增多行复权、显式单位、公告下一session、录制取消/篡改回归后量化28项通过。
- 根因：初始单行测试覆盖不到闭包变量复用；证券状态缺失不能当普通状态。
- 解决：新增 `test_adapters_recording.py` 覆盖多行 qfq/hfq、未知日历拒绝、T+1版本规则、缺省状态 unknown、空银行字段、FileCallJournal重开及篡改、预算超时录制；录制文件IO移至线程，不阻塞调用事件循环。数据内容不进入SQLite，Parquet读取额外校验每分区行数/行流hash。
- 经验：至少测试两根跨公司行为窗口的bar；仅安装base的真实Python版本导入比mock缺包更可靠。最终还会在全部改动稳定后重跑验收。

### 共享快照、篡改与 GC 边界验证
- 现象：量化加迁移32项通过；共享快照删除一个卷宗后仍能读取，另一个所有权保留；修改一个已知 blob 后离线命中被 SHA256 校验拒绝。审查发现 blob 在事务外发布，可能与旧卷宗 GC 的相同内容竞争。
- 根因：内容哈希去重使“新抓取”与“旧卷宗候选删除”可能指向同一文件；仅写完后插元数据不足以避免这个窗口。
- 解决：freeze 从 blob 发布到元数据提交持有 SQLite BEGIN IMMEDIATE，与现有 GC 同步；迁移改为固定列定义，避免以后 ORM 修改改变历史迁移。DuckDB 关自动装/载扩展，worker 输出流分块限额，超时/取消均杀子进程并等待退出。
- 经验：内容寻址解决重复与篡改，不单独解决所有权和 GC 并发；迁移必须冻结自己的 schema，而不是引用运行时 ORM。

### 无公司行为窗口的正确表达
- 现象：茅台和美的在验收窗口内 query_adjust_factor 成功但返回空行，初版误报取数不可用；金融空指标与“该区间确实无事件”不能混为一谈。
- 根因：把所有空 dataset 都作为网络/数据失败处理。
- 解决：仅对成功返回的 adjustment 空集允许 `no_actions_in_range`，写两份有 schema 的零行 Parquet、冻结 manifest；金融/日线空集仍拒绝。量化回归32项通过（不含单独迁移测试）。
- 经验：业务语义决定空值：未知财务是 null，无事件是可证明的空集合，断网是失败；三者不能用0代替。

### 真正断网审计的 Windows 特例
- 现象：最终 live-04 三只 raw/qfq/hfq、财务与估值均成功，无事件标的冻结0行因子表；尝试封禁全部 socket.connect 的离线审计时 asyncio.Runner 自身启动失败。
- 根因：Windows Proactor 通过本机 socketpair 建立事件循环唤醒管道，不能把初始化管道误当外部网络取数。
- 解决：离线审计先创建事件循环，再封禁所有后续 connect 与 create_subprocess_exec；全部读取只用已冻结SQLite/Parquet，并逐快照检查 stale/权益拒绝导出共享/内容hash。审计不将原始行情复制到docs。
- 经验：网络故障注入应隔离系统运行时初始化与业务取数，否则测试证明的是事件循环无法启动而非缓存可用。

### 最终结果与未修复的旧 3.11 取消挂起
- 现象：Python3.13最终全量 `591 passed, 3 skipped, 7 deselected`；quant+迁移 `33 passed`；Python3.11无七种quant依赖启动导入成功、quant契约/数据单位/录制骨架+迁移 `26 passed`。额外尝试3.11完整旧业务回归时挂起；授权环境重跑和单例均复现。
- 根因定位边界：完整 faulthandler 栈定位 `test_auto_recovery.py:124` 的 `client.post(.../cancel)`，主线程等 TestClient/anyio Future、Proactor 轮询；不是 PyPI/沙箱取数限制。深层取消等待根因尚未证实，不能称为已修复或把它归因于量化代码。
- 解决/止损：保留 `.phase3-quant-m/cancel311-diagnostic.log`，只结束命令行带本批专用 basetemp 的测试进程；未改原恢复/取消逻辑。CI两条保留真实全量验收与15分钟超时，不删除失败用例来凑通过；3.11全量兼容性仍待单独处理。
- 经验：导入兼容通过不等于所有异步行为跨Python版本兼容。遵守本批增量数据底座范围，交付时显式披露这项限制，不越权改旧业务。

### 收尾：服务冒烟与仓库行尾检查
- 现象：3.11旧服务启动/无模型密钥/回放报告4项冒烟通过。曾临时关闭core.autocrlf检查，导致Windows既有CRLF文件被大量报为行尾空白。
- 根因：关闭仓库行尾转换改变了检查语义，并非本批制造了全仓库空白修改。
- 解决：不改任何既有行尾，按项目原配置重新 `git diff --check`，退出0，仅既有LF/CRLF提示。终止的均为本批完整3.11/单例诊断测试进程，现有服务未停止，数据证据未删除。
- 经验：验证应沿用项目行尾契约，不用临时全局覆盖制造假差异。最终报告单列3.11取消挂起，不以通过的冒烟测试掩盖它。

## P0-C → 2026-10-04

### 契约与纯计算第一步
- 现象：Task N 新测试先因 compute 包尚不存在失败；实现后发现测试用指标名建字典覆盖了逐日收益的第一行。另一次测试因专用 basetemp 的父目录不存在失败。
- 根因：序列指标必须以 name + row_keys 定位，不能仅 name；pytest 不自动建立 basetemp 的父目录。这两项是验证脚本问题，不是收益公式问题。
- 解决：日收益保留逐日坐标，测试显式检查首行；建立 `.phase3-quant-n` 后再运行独立目录。新增 frozen Decimal 契约、显式年化252/elapsed-year、停牌 carry-forward/缺值传播，未恢复回撤日期保持 null。
- 经验：Decimal 编码不能使用依赖当前精度的 normalize()；以定点字符串去尾零锁定编码。任何坏日都不自动剔除。

### 既有冻结财务不具备完整估值输入
- 现象：M 的三只标的有 raw/qfq/hfq 日线，但仅平安银行单季财务；归母权益、明确TTM及当时同share-basis股数不足。
- 根因：BaoStock profit 表的 netProfit/roeAvg 不能自动推定为经过审计的TTM归母口径；供应商 PE/PB 也不等于本系统独立复算。
- 解决：估值契约分开 period_basis/statement_basis/share_basis/revision/available_at；缺项返回 null+原因，供应商披露指标单列，禁止倒推财务以凑出比率。
- 经验：能离线复算价格表现不意味着能验证历史估值；真实验收必须如实记录部分覆盖，不用合成财务冒充三标的真实输入。

### 有界执行与冻结记录
- 现象：纯计算已接入固定 worker 入口，SDK/模型凭据不传播，输入24MiB、stdout8MiB、stderr64KiB；所有流分块读取，硬截止/取消后 kill + wait，不提交半产物。
- 根因：仅 await 一个线程不能提供硬CPU取消；runtime latest 或调用时刻参与语义会使重放身份漂移。
- 解决：新建独立计算job租约/幂等键，输入存CAS；成功事务提交完整manifest/output/bundle及调用记录，恢复读取原input_ref；manifest冻结schema/spec/输入分区/许可/PIT/规则/日历/源码树/Python/lock/输出hash。
- 经验：同环境比较输出bytes；跨环境先校验输入/单位/时间/定义，再按spec容差比较，不用数值近似容忍输入篡改或源代码缺失。

## P0-D → 2026-10-04

### v2 引用与旧声明外键
- 现象：集成测试先通过六项计算/篡改检查，报告提交在 `inv_report_section_claims` 外键失败。
- 根因：旧章节通过关联表引用真实Claim；单独的量化sidecar ID不是真实持久化Claim，不能硬塞进去。旧Citation又绑定文本Evidence，不能删外键来扩展。
- 解决：量化数值观察落入现有Claim/ValidationResult链，以run隔离运行ID；v2单独存计算引用，保持文本Evidence/Citation旧表不变。assembler按证据种类分支，数值从冻结单元格模板只读追加。
- 经验：真正的增量集成要保留既有数据库约束；不能以“新的hash存在”代替Claim、最新Validation、owner、artifact和cell真实链。

### 门禁与正文边界
- 现象：同源多包装/复算成功并不满足独立性、许可或STRICT PIT；现有真实数据多为PARTIAL/UNAVAILABLE。
- 根因：可复现是计算性质，不是来源独立或投资结论可信度。
- 解决：QuantitativeProfile新增计算分支，不修改网页profile与15阶段政策；缺样本/校验/独立性/quality/rights/PIT/conflict时UNVERIFIED，不自动PROBABLE。v2新域哈希，旧v1未出现quant字段时序列化完全省略该字段。
- 经验：技术诊断只进折叠附录；未知授权触发报告治理审核，不能因报告外观像成品就发布数值投资结论。

### 验证身份不能只哈希门禁布尔值
- 现象：报告集成第二次在ValidationResult主键重复失败，return/volatility/drawdown三个单元格的门禁布尔结果相同。
- 根因：初版validation_hash只覆盖门禁结果，没有绑定cell_hash，因而不同数值观察共享了验证身份。
- 解决：验证身份加入cell_hash和policy_version；持久化时同时绑定真实Claim、run与最新Validation；Citation再次核对这条链。重跑量化报告通过。
- 经验：验证哈希必须绑定被验证的对象，不能只证明“某几个布尔条件通过”。writer全文必须等于只读模板，不能靠包含原句来允许附加虚构数字。

### 执行取消、恢复与真实断网样本
- 现象：有界worker在Windows Job Object的768MiB/单进程限制下运行成功；lease超时重领、不同spec复用幂等键拒绝、live量化正常/取消均持久化报告后COMPLETED，12项集成通过。
- 根因：计算job完成不是调查完成；重启不能把quant任务误路由到付费网页Agent。只累加价格/财务来源数也不能证明估值独立复核。
- 解决：quant-v1显式支路、原input_ref恢复、attempt递增、旧网页路线不变；按必需数据类型分别检查来源族门槛。复制M真实bundle到N私有验收目录，禁网络后对三标的19交易日计算与重算，并保留null财务缺口。
- 经验：三标的同环境输出bytes一致不等于三标的完整估值验收通过。本批真实样本仍缺同口径财务，必须在交付中标为未满足项；未知许可/PIT/谱系不能升级为VERIFIED。

## P0-C / P0-D → 2026-10-04（最终校验）

### 真实 worker 环境与 Windows 凭据隔离
- 现象：增加 worker 实际 Python/依赖/平台校验后，preflight-07 的9项集成失败、60项通过；子进程只返回“环境不匹配”。
- 根因：隔离环境白名单去掉了 PROCESSOR_ARCHITECTURE，platform.machine() 在父进程是 AMD64，在子进程是空字符串。读取子进程 stderr 后，以同一冻结输入及同一精简环境逐字段比对，仅 machine 不同，排除了公式或财报口径回归。
- 解决：白名单只补充 PROCESSOR_ARCHITECTURE / PROCESSOR_ARCHITEW6432 两个非敏感架构字段；同时记录 pointer_bits。实际 Python/依赖校验保留，伪造 Python 标签仍拒绝；未传播模型/数据源密钥。
- 经验：增加安全隔离后的验收，要比较真实执行环境而非母进程标签。不能为“让测试通过”删掉环境绑定，也不能放回全部环境变量。

### 单元格的日期和完整交易日边界
- 现象：供应商披露的单季财务最初继承价格窗口日期，最后一日PE/PB也继承整段样本数；虽然数值未变，坐标语义不够准确。
- 根因：汇总指标辅助函数默认采用价格序列的开始/结束与长度，不适用于单期披露值。
- 解决：财务披露值绑定实际财报期末，日线披露比率绑定最后一日，sample_count=1；收盘前的当日bar拒绝；重复日期/混入其他证券/多份歧义日历拒绝。展示明确raw价格收益不含现金分红，252仅为显式年化假设。
- 经验：可定位的cell必须同时锁定数值、单位、日期与口径；不能用19个价格观察替代一个财务观察的统计支持。

### 真实报告的方法说明不能沿用网页模板
- 现象：offline-02 三只真实标的复算成功，但报告折叠方法仍描述研究/分析模型协作，技术附录也继承“调查完成”通用模板。
- 根因：量化纯分支追加新正文时保留了空网页任务的非事实模板，没有按实际执行路径裁剪。
- 解决：只在quant-only报告分支替换方法说明为冻结输入→有界子进程→独立重算→单元格/最新验证链，去掉虚构的运行完成标签，保留真正的收尾诊断；加短窗口年化非预测提示。混合网页材料不改旧方法与事实。
- 经验：报告真实性不仅包括数值，也包括“到底做过什么”；本批未做网络调查、策略回测或模型生成数字，方法不能暗示做过。

### 验证与报告之间的输入完整性窗口
- 现象：计算验证重读输入CAS，引用原先只核对产物CAS与最新Validation；若两步之间冻结输入被破坏，引用阶段不能发现。
- 根因：把“已有最新验证”误当成底层输入仍完整，缺少出具引用时的再次读取。
- 解决：计算引用重新读取全部冻结快照并核对完整manifest描述；Blob缺失/损坏转为引用完整性HARD问题。quant报告最终校验/落库移入线程，数值重算仍只在有界子进程。新增验证后破坏测试专属Parquet的集成用例。
- 经验：真正的最新引用链既要验证身份，也要检查当前可读取的输入bytes；验证对象不可变的数据库约束不能替代CAS读时校验。

### 独立来源必须匹配当前声明口径
- 现象：检查独立性计数时发现，raw收益的来源计数可能把另一个上游的hfq快照也算作支持，即使原始生产者确实不同，价格口径也不可直接互证。
- 根因：早期只按dataset过滤支持，没有同时约束adjustment和覆盖区间。
- 解决：收益按spec的raw/qfq口径过滤，估值只认可raw；价格快照必须覆盖声明窗口。新增两个已确认来源族、但复权方式不同的测试，后者不增加支持数。
- 经验：来源族身份独立不等于支持当前口径；同一声明的证据必须同时匹配标的、时间、单位和价格定义。不能用不同复权方式凑高重要性验证门槛。

## P0-C / P0-D → 2026-10-04（额度恢复后收尾）

### hfq 独立性测试漏填冻结anchor
- 现象：`test_other_adjustment_does_not_inflate_claim_independence` 在快照load/attach时报“adjusted data needs a frozen anchor”，尚未走到独立性断言。
- 根因：测试用model_copy将raw请求改为hfq，但model_copy不重新验证，漏填adjustment_anchor；冻结快照读回时正确触发了原有契约校验。
- 解决：仅给测试hfq请求补`adjustment_anchor=request.end`，锚点不晚于asof且覆盖请求结束日；未改DataRequest或复权校验。
- 经验：修改frozen测试模型也须满足完整不变量，不能绕过重载校验；不同复权方式不计入raw声明支持，anchor门禁应保留。

### anchor 验证结果
- 现象/根因：修复前在重载处被契约拒绝，并不是独立性计数的断言问题。
- 解决：3.13 quant 专项重新运行，74 passed / 116.03s；证据`.phase3-quant-n/resume-anchor-01.xml`，使用独立basetemp与no:cacheprovider。
- 经验：先隔离验证测试构造修复，再接入真实财务，避免掩盖原有失败。

### 财务同口径与TTM：实际缺项及录制补取
- 现象：旧live-04仅银行一期BaoStock利润、银行估值；无明确归母/累计期间、期初权益和有可用时间标签的同日股本。独立PE/PB/ROE/趋势均为空。
- 根因：`netProfit/epsTTM`与季度末`totalShare`不能被直接认作归母TTM及估值日股数；Sina摘要无公告日期、单位未确认。缺失并不是零。
- 解决：新增SDK隔离进程内Eastmoney资产负债表/利润表接口，原始normalizer 3留存审计；3-parent-2从录制raw重放规范化PARENT_NETPROFIT、TOTAL_PARENT_EQUITY、OPERATE_INCOME、CURRENCY/NOTICE_DATE/UPDATE_DATE，以及stock_value_em同日总/流通股数。CNY元、share和Decimal串显式保存；利润累计YTD/annual，TTM=上年全年+本期累计-上年同期；ROE按TTM开始日前一天的真实权益和期末权益平均，不伪造期初权益字段。收入为合并口径，归母利润为parent口径。
- 经验：四季度总和必须先区分单季与累计；累计报表不能把四个YTD相加。SHARE_CAPITAL是金额科目，不能当股数，亦不从供应商PE倒推利润。

### 实时补取的网络与落盘问题
- 现象：首轮sandbox BaoStock日历失败；授权读取后calendar成功。银行balance、美的balance/income首次ConnectTimeout，限时录制重试成功。Sina摘要银行/茅台返回重复记录导致freeze拒绝，美的超时；未绕过重复校验。脚本初次假设Instrument.exchange属性报错。
- 根因：网络许可/上游波动，以及交易所实际在有效alias而非Instrument直接字段；Sina原始摘要指标重复。
- 解决：exchange从master.alias取值；每个SDK调用录制、100秒外层预算/12秒请求timeout；仅重试缺失报表两次，所有结果和错误即时落盘。只读backup live-04，新目录financial-live-03 → financial-frozen-01 → financial-frozen-02，未覆盖旧证据。仅转换已录制raw时也经过RecordingQuantDataPort，并在provenance绑定raw快照和原采集日期。
- 经验：不能用无公告/单位的备用摘要凑财务；失败调用与原始成功调用都应保留，规范化变更用新版本、新快照。

### 归母总额不等于普通股EPS、历史标签不等于STRICT PIT
- 现象：银行2024Q1 OTHER_EQUITY_TOOL=69944000000元；三家2024Q1利润表UPDATE_DATE在2025年，晚于研究asof。stock_value_em股本有交易日而无公告日期。旧master中文名已有乱码。
- 根因：银行归母总权益含优先/永续等其他权益工具；免费当前接口回溯可能重述历史，不能证明当时已知版本。源文本编码问题与数值语义是不同质量维度。
- 解决：显式share basis为total_issued_shares_parent_aggregate_not_ordinary_eps，不扣未取得的优先/永续分配、不冒充普通股EPS；报告注明归母总额口径，与披露PE/PB分列并计算差异，不平均。公告次交易日只是保守可用标签，财报PARTIAL、股本UNAVAILABLE PIT，仍不满足VERIFIED。修订/单位/来源/期间/口径写入manifest；不改旧master和原始source文字来掩盖乱码。
- 经验：能确定性算出数字不代表该数字可作当时的交易依据；计算一致、口径差异、历史可知性必须分别披露。

### 新口径必须显式分支，不能重解释旧同比
- 现象：财务接入后quant首次回归76 passed/3 failed，三个原合成用例的net_profit_growth从0.2变成null；真实报告估值与同比日期也沿用了价格窗口。
- 根因：仅看到parent_net_profit就优先计算归母同比，但旧样例该字段只有TTM，没有归母同期历史，原来的净利润同比历史仍是可用的；统一metric默认日期不适用于估值时点和财报期间。
- 解决：仅3-parent-2新分支用归母同比；旧分支保留net_profit含义。新估值/供应商对照为价格末日时点，ROE为实际TTM期间，增长为当前可比报告期；供应商标签区分BaoStock与东方财富。定向8项（5新单测+3旧集成）通过，继续重新跑专项和全量，初次失败XML保留不当作通过证据。
- 经验：增量功能不能靠字段优先级静默改变旧语义，日期也属于证据定义而非展示装饰。

### 新冻结三标的断网验收与兼容性验证
- 现象：原空财务已补齐成独立归母总额PE/PB、ROE及同比，但历史重述/授权等门槛仍不满足。
- 解决：最终`offline-financial-02`禁socket复算三标的，收益/回撤绝对差0、PE/PB相对差0，同环境bytes hash相同，单位篡改拒绝。各17条可复现观察均UNVERIFIED、6个非空章节、局限3条。只读取financial-frozen-02新快照，未用测试数据或模型填充。
- 验证：quant最终79 passed /130.61s（final-parent-quant-02.xml）；首轮全量638 passed、6 skipped、4 deselected /585.09s，最终再次全量仍在运行，待下条记录。Ruff通过；3.13导入37个quant模块和旧server通过；3.11确认7个可选库未安装，旧server/核心导入通过；git diff --check exit0（仅既有CRLF提示）。
- 经验：数值闭环可以交付，PIT和普通股分配口径缺口仍必须保留，不能因真实结果非空而放松VERIFIED门禁。

### 原证据不覆盖与最终manifest绑定复核
- 现象：补财务需要新快照，且运行过程中源码仍有修正，旧验收产物不能被冒称最终版本。
- 解决：只读比较live-04的20份snapshot_id/semantic_hash/manifest_ref/partitions/frozen_payload，全部在新包中原样保留；最终offline-financial-02三份artifact的环境与当前37模块源码/lock/runtime一致。source_tree_hash=`2de961f0994b7b94dc47a0cfa1730a90f03377b47af30bea3ad198ea39e96469`，lock_hash=`d35825d3d96aeef86d3e1d7a7159960c2f0a979db1d7ab16208c39dcbc36ca77`。
- 经验：重算“相同”还要核实来自最终源码和锁文件；旧价格与旧证据保留，新财务与新计算明确新增，不能覆盖或换latest。

### 最终全量结果与检查点
- 现象：全量回归包含无专用配置/Windows不支持的基础设施用例，不能把未执行项计为通过。
- 解决：`.phase3-quant-m/venv313/Scripts/python.exe -m pytest tests -q -m "not live" --basetemp .phase3-quant-n/final-parent-all313-02 -p no:cacheprovider --junitxml=.phase3-quant-n/final-parent-all313-02.xml`，最终638 passed、6 skipped、4 deselected、1 warning /545.64s，exit0。6跳过为3项PostgreSQL/Redis配置、2项Windows symlink权限、1项POSIX SIGTERM；4 live因外部网络/模型调用费用未运行。Starlette旧BlockingPortal别名弃用警告保留，不改业务依赖。
- 经验：最终交付以修改后的独立全量为证据，专项79项、Ruff、双版本导入、diff检查与真实离线报告一起归档。已更新v10交付文档，无新增迁移、未重启/迁移业务数据库、未进入前端/API，等待用户检查。
# P0-E / P0-F → 2026-10-04

- 现象：内部 `start_quant` 已支持持久化报告与取消，但 server 未注入 QuantService，浏览器无法启动。根因：P0-C/D 刻意停在内部接口。解决中：新增独立 quant 路由并在 lifespan 装配；旧本地可信操作员会话边界保持，不凭空声称已具备互联网多租户认证。经验：对外 HTTP 可用不等于可直接公网商用，未知数据授权仍禁止原始导出。

- 已完成首批接口与展品接线：新增 API 合成用例 3 项及纯展品 1 项通过（`api-01`，22.50s）；未把合成 fixture 当成真实数据。根因/经验：非 raw 请求仍必须冻结 anchor；价格收益与财务估值应分别选用复权/原始价格，不能把 hfq 默认为 qfq。新增显式 price_adjustment，归母估值始终 raw；验证来源筛选也识别 hfq，不增加独立来源族。
- 测试基目录坑：新 `.phase3-quant-o` 尚不存在时 pytest 的 basetemp mkdir 报 WinError 3。定位为父目录缺失而非计算失败；创建父目录后独立用例通过。所有后续回归使用新的 basetemp，不删除旧证据。
- 前端首次构建通过，ECharts 以动态 import/core+Line/Bar+Canvas 按需注册；初次 chunk 535KB 触发 Vite 500KB 提示，将继续评估拆包。npm 安装报告现有依赖安全警报（需另核实），不自动执行破坏性 `audit fix --force`。图表减少动效关闭 animation，ResizeObserver 随卸载断开并 dispose，表格保留完整原值与 cell_hash。

- 引用接线坑：内部仓储会合并 QuantCitationRow，但旧 HTTP 列表/详情只读取 CitationRow，真实报告引用列表为空。根因是 P0-D 保留旧对外行为、本批才需新分支。已增量合并列表，并为计算引用校验最新持久化 Claim/Validation、输入/产物/hash/ownership 后返回 COMPUTATION_CELL；没有伪造网页来源、引文或归档 URL。API 用例新增断言引用数量一致、计算引用能打开且仍 UNVERIFIED，专项 83 项通过（quant-final-01，125.18s）。
- 冻结源码门禁坑：`http-real-01` 在写实现代码的同时跑真实数据，后续 `input_for` 报 pinned source tree or lock is unavailable，API 正确拒绝数值。根因是 worker 环境已冻结、当前源码发生变化，并非财务数据缺失。保留失败目录作为诊断；稳定业务源码后在 `http-real-02` 新副本重新执行，不关闭 hash 校验、不覆盖 N/live 证据。经验：最终证明必须在实现稳定后跑；边写边跑只能是阶段诊断。
- 图表口径：财务曲线改为同报告期归母净利/合并营收同比（fraction），按年报对年报、同季度累计对上年同期在 worker 内计算；不足年份保留 null+reason。独立 PE/PB 与 BaoStock、AkShare/东方财富披露值分别列示，不平均。遗漏 benchmark/rf 的缺口已进入报告聚合局限，而不写零。
- 明确历史窗口：新入口可选择已冻结的具体日期/asof/ID 集合（19 日会直说 19 日），而不是把2024年快照当当前行情；没有歧义的可用窗口才显示，运行持久化 QUANT_FROZEN_PLAN。当前数据不足时走录制/有界 SDK 子进程取数与降级；已有快照优先，最终完整性失败仍拒绝输出。
- 前端依赖：ECharts6.1.0 锁定；core+Line/Bar+Canvas 动态导入，renderer176.77KB、echarts359.81KB，无500KB警告。npm test34/34、build退出0；审计确认两项来自原有Vite5.4.21/esbuild开发依赖，不来自 ECharts。本批不自动跨大版本升级，开发端只绑定127.0.0.1，公网部署前须处理安全更新。

### 新建量化任务成稿前停止轮询
- 现象：12组历史报告UI矩阵均通过，但新建真实冻结任务进入报告页后没有图表；`ui-debug-01/entry-failure.png/html`显示17条声明、空报告，而实际HTTP已COMPLETED并有报告。
- 根因：量化沿用durable-report-first收尾，报告持久化过程中暂置READY_FOR_REPORT/BLOCKED；前端用旧网页终态集合停止轮询，停在成稿前。另外并发读取run和reports可能跨越落库时刻。
- 解决：先新增两个红色回归用例，再仅对quant-v1将这两个过渡状态作为运行中；COMPLETED的quant报告ID若不在并发列表中，顺序补查一次，保留generation防陈旧响应。网页READY_FOR_REPORT仍终止轮询，后端状态/持久化协议不变。定向10项已全绿，继续重建及真实UI重跑。
- 经验：HTTP状态的终态语义要按工作流解释；不能靠固定sleep、手工刷新或提前把未持久化任务标COMPLETED解决。失败截图和旧私有证据目录保留。

### 真实HTTP、图表与最终回归
- 现象：已经能算出三标的数字，但新HTTP/图表仍须逐层证明，不能用合成API用例替代真实结果，也不能把已成稿当已验证。
- 解决：稳定后端源码后，`http-real-02`从N的financial-frozen-02只读backup，三标的实际HTTP quick完成，每份7个输入快照/17观察/17引用/3图/6非空章节。离线worker复算收益/回撤绝对差0、PE/PB相对差0，bytes hash一致。53份源冻结数据不被覆盖；取值仍是2024年19日历史样本，财务口径/PIT不足照常UNVERIFIED。
- UI：修复轮询后`ui-real-02`12场景（375/768/1440×亮/暗×减少/正常动效）exit0，3图、4正文节、附录折叠、无页面溢出，hfq/cell/引用可用、pageerror=[]。真实新建窗口→RUN-QUANT-6799d1d1cd6f4d32→RPT-204caa679519无需手动刷新成功。新增原值缺失原因显示，头部显示快照并区分成稿/验证。`lineage-final-01`逐个核对三标的各138图点（414总计）的value/unit/path/artifact/cell_hash全部一致。
- 回归：quant-final-01为83 passed/125.18s；backend-final-01不排除live标签，642 passed/10 skipped/502.11s，exit0，10跳过为3基础设施未配、2Windows symlink、1POSIX信号、4未启用live；1条Starlette弃用警告。前端最终36/36、build退出0。Ruff全部src/tests及三个O脚本通过，diff check exit0；3.13导入42quant模块+旧server；3.11实际无quant库启动新私有库health200/quant503，scientific模块未导入。之后只改前端/辅助验收/文档，未使后端源码manifest漂移。
- 经验：用真实服务的UI状态观测持久化边界，比只拿后端COMPLETED后强行点击更能揭示接线错误；最终必须同时交付数值、cell、引用、UI和明确限制。新建接口的CREATED回执不是终态，验收summary须结合run文件解读。未做跨OS、3.11全量/旧cancel挂起修复、当前源长窗口SLA或P1。
- 收尾：交付`docs/v11-taskO-p0ef-delivery.md`，保留所有成功/失败证据。专用127.0.0.1:8830验收服务已正常停止；未停止用户其它服务、未删除数据、未迁移用户业务库、未提交Git。启动与复查命令见交付第8节，等待用户检查。

### 用户检查时8830连接被拒绝
- 现象/根因：用户截图为ERR_CONNECTION_REFUSED，与上一轮停止专用服务的收尾记录一致，并非前端代码错误。本机Get-NetTCPConnection诊断被拒绝访问，不能将其静默输出当成“确认无监听”，改以实际HTTP响应和启动进程检查验证。
- 解决：使用原3.13环境与http-real-02隔离库，以隐藏后台进程重新启动serve_quant_o.py，仍仅监听127.0.0.1:8830。首页与health实际HTTP200，平安银行运行COMPLETED、3图与原报告可读；日志为`.phase3-quant-o/inspection-server.stdout.log`和`inspection-server.stderr.log`。本次留服务运行供用户检查，未改业务代码。
- 经验：自动验收完成与用户现场验收是两个阶段；临时服务停止后应明确说明，并在用户需要浏览时重新提供可用入口。

