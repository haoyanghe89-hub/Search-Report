# Task L 数据源最小连通性验证

日期：2026-10-04。独立环境，不导入业务包，不读取 `.env`，不写业务数据库，不调用付费模型。实际使用 Windows / Python 3.13.13；核心版本见 `requirements.txt`。行情测试标的为平安银行 `000001`，区间 2024-05-20 至 2024-06-14，共 19 个交易日。财务取 2024Q1；AkShare 部分接口不能限制报告期，其历史返回仅保存在本地。

## 重现

在仓库根目录执行（需要网络，下载依赖前自行确认）：

```powershell
uv venv docs/spikes/task_l/.venv --python .venv/Scripts/python.exe
uv pip install --python docs/spikes/task_l/.venv/Scripts/python.exe -r docs/spikes/task_l/requirements.txt
& docs/spikes/task_l/.venv/Scripts/python.exe docs/spikes/task_l/data_source_spike.py
& docs/spikes/task_l/.venv/Scripts/python.exe docs/spikes/task_l/data_source_spike.py --recheck
& docs/spikes/task_l/.venv/Scripts/python.exe docs/spikes/task_l/check_spike.py
```

普通探针最多并发 2，复测串行；HTTP 默认 12 秒，单子进程硬上限 55 秒，无自动重试，不做全市场扫描。BaoStock 使用公开 SDK 匿名登录，不是注册账户。脚本运行生成 `results/*.parquet`、JSON；Parquet 仅本地核验，已忽略，不作为可再分发数据集交付。首次/复测记录分别保留，不覆盖失败证据。

## 实际结果

|探针|首次|复测|实际返回|
|---|---|---|---|
|AkShare 东方财富 raw|连接超时|对端关闭连接|未通过，不宣称稳定|
|AkShare 东方财富 qfq / hfq|成功 / 成功|未重试|各 19 行，12 列|
|AkShare 腾讯 raw / qfq / hfq|全部成功|未重试|各 19 行，8 列|
|AkShare 东方财富利润表|请求历史分批数据时连接超时|不重复大历史请求|未通过；并非没有财务接口|
|AkShare 东方财富估值|成功|未重试|2,123 行，13 列|
|AkShare 新浪财务摘要|首次未探测|成功|80 个指标行、报告期宽列；无发布日期列|
|BaoStock raw / hfq|全部成功|未重试|各 19 行，18 列|
|BaoStock qfq|登录网络接收错误|成功|19 行，18 列|
|BaoStock 季度利润|成功|未重试|1 行，11 列；pubDate=2024-04-20、statDate=2024-03-31|
|BaoStock 复权因子|成功|未重试|1 行，5 列；2024-06-14|

事实文件：[`summary.json`](results/summary.json)、[`recheck.json`](results/recheck.json)、[`offline_checks.json`](results/offline_checks.json)。包含查询、时间、列名、类型、样例、完整本地 Parquet SHA256 和 DuckDB 行数。

离线核验通过 12 个成功产物：SHA256、DuckDB 行数一致，行情日期唯一且递增；腾讯/BaoStock 19 天原始收盘价最大绝对差 0；东方财富/腾讯 qfq 收盘价最大绝对差 0。BaoStock 成交量/腾讯 volume 中位比值约 100；BaoStock `turn`/腾讯 `turnover` 约 100.03（精度舍入），必须显式标准化。银行财务 `gpMargin`、`MBRevenue` 为空串，不可自动当 0。初次离线合并检查因 `datetime64` / `object` 日期键不一致失败，已仅在此验证脚本中对双方键显式转日期后重跑通过；这也是生产适配器必须做类型标准化的证据。

## 不能推出的结论

一次成功不证明长期 SLA、全市场/退市覆盖、历史修订版 PIT 完整性、商用授权、来源族独立性或策略有效。两平台数值一致是抽样一致性，不自动等于两个独立生产来源。免费库的软件许可证不替代上游数据许可；本结果不得拿来宣传收益。东方财富失败原因仅定位到连接/响应层，尚不能归因于封禁或 SDK 缺陷；没有绕过反爬、验证码或权限。
