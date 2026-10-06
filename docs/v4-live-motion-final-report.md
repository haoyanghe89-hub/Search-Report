# 调查实时动画与 Hero 自适应：任务 A 最终报告

验收日期：2026-10-01。依据 `v4-live-motion-task.txt`、`v5-taskA.txt` 与 v3 交接文档。保留 v3 已有设计；未修改 API、业务 composables、组件 props/emit、数据字段、轮询频率或后端。

## A1：实时动画最终结论

通过真实应用中的 `InvestigationView` 验收，而非仅孤立组件演示：拦截同一个 `RUN-LIVE-MOTION` 的 API 返回，保留生产代码的 2 秒轮询，由持久化状态驱动画面。

流程为等待登记 → 第一位研究员/第一条步骤入卷 → 第一条完成盖章，同时第二条入卷、阶段及预算更新 → 运行终态 → 进度区合卷 → 结果区开卷。旧结果在运行及合卷期间均不提前显示，完成后 9 个 tab 均可访问，指示器正确定位。

### 七项动画落地

| 项目 | 当前实现与参数 | 验收 |
| --- | --- | --- |
| 步骤归档入卷 | 只处理新增 step ID；500ms，opacity 0→1、y 18→0、rotation 0.5→0，power3.out；同批可见新增条目按既有 token 50ms stagger，已存在步骤不重播。当前可见活动步骤用 2px 细线、12% 透明度、1600ms 扫描，完成即停止 | 新旧步骤、滚动可见性均通过 |
| 状态盖章 | 仅 RUNNING/VERIFYING→COMPLETED/SUCCEEDED；350ms，scale 1.4→1、rotation -6→0，back.out(1.7)，每项每轮只盖一次。失败态保持静态语义提示，不闪烁 | 步骤及研究员戳记的瞬态均被采样捕获 |
| 研究员工作态 | 活跃卡细描边/elevated 层强调；新增活动研究员入场，普通状态变化用轻淡入，完成用盖章 | 入场、工作态和完成态通过 |
| 预算数字翻跳 | 使用整数 count-up 加轻淡入/位移，400ms；tabular-nums；上限始终静态。减少或降级直接对齐真实值 | 捕获中间值，最终搜索/抓取/模型调用为 4/2/1 |
| 阶段揭示 | phase 变化触发 400ms 淡入/轻位移，不逐字拆读也不循环。保留不确定进度 sweep，但收为 2px 细线，不伪造百分比 | 阶段变化和瞬态通过 |
| 合卷/开卷 | Vue 的 CSS-disabled Transition 使用 GSAP leave；进度区 480ms 淡出、y -8、scaleY 0.985，完成后结果区按既有 480ms 开卷。不遮屏、不锁滚动 | 验证 leave 期间无结果、leave 之后结果出现并开卷 |
| 空/等待态 | starting 或等待首条步骤时呈现 CASE INTAKE、索引线及编辑式说明；适宜设备保留小型 orbit | 空等待及首次步骤替换通过 |

视觉与动效参数均从 `tokens.css` 读取。数字采用 count-up、阶段采用淡入、进度采用细线 sweep，是任务允许的替代形式；未新增磁吸或指针跟随。

### 实时驱动与清理

- `watch` steps/workers/budget/phase/running 快照；动画不依赖验收脚本的固定时间表。初始快照登记为已见，不重播历史步骤。
- `RunProgress` 按 runId 设置 key，切换运行重建展示状态；异步 DOM 更新由 mounted 状态及 generation 保护。既有旧响应隔离及轮询机制不变。
- IntersectionObserver 管理新增离屏步骤：内容默认可读，仅进入可视区域时补一次入场。扫描只为可视活动步骤创建，离屏/完成即 kill；一批观察通知只同步一次。
- 100 条步骤测试：全部呈现，仅 4 个可见条目有扫描 tween；滚到底部后末项可见且首项扫描已销毁。
- reduced-motion 初始及运行中切换均停止 DOM、数字对象、phase、orbit、扫描 tween，预算立即对齐，清除位移并使内容完整可见。组件范围内禁用 CSS 过渡，避免全局 reduced-motion 样式残留 120ms 淡入。
- 触摸设备、saveData 或 hardwareConcurrency≤4 禁用循环环境动画；有限的一次性入场仍可在非 reduced-motion 下使用。未引入高耗能指针动画。
- 卸载前保留根元素并 kill 子节点 tween；卸载时清理计时器、watch、媒体查询监听器、IntersectionObserver、循环/phase/数字对象 tween。实测卸载后相关 DOM tween 和循环数均为 0。
- 取消 leave 会停止 tween、恢复进度可见性；卸载或运行中开启 reduced-motion 也会停止转场，直接呈现最终状态。

## A2：标题长度自适应

只按实际展示标题的 Unicode 字符数选择 `hero-title--lg/md/sm`；不改变标题内容。阈值也来自 token，而非组件内硬编码。

| 标题长度 | class / token | 流体字号 | 实测桌面 / 手机 |
| --- | --- | --- | --- |
| ≤18 | lg / `--font-size-hero-lg` | clamp(40px, 5vw, 60px) | 60px / 40px |
| 19–36 | md / `--font-size-hero-md` | clamp(30px, 4vw, 42px) | 42px / 30px |
| >36 | sm / `--font-size-hero-sm` | clamp(24px, 3.2vw, 32px) | 32px / 24px |

长标题行高为 `--line-height-hero-long: 1.15`；保留字重和字距。修正旧手机规则的 `!important` 覆盖，使分档 class 在窄屏同样生效；标题片段限制宽度，避免不可断行片段溢出。

54 字长标题在 390×844 下高度约 138px，状态底部约 322px，主 CTA 底部约 429px，均在首屏；在 1440×900 下标题约 110px 高。短离线案例仍为 60px/40px 大标题。12 组标题测试均验证全文保留、对应字号、标题无内部溢出、状态与 CTA 首屏可见。

## Playwright 覆盖与证据

运行环境：本机 Python Playwright + headless Microsoft Edge。生产页面通过 Vite 加载；API mock 只匹配测试 origin 下 `/api/` 路径，不拦截源码模块。

- `final-acceptance.py`：203/203，通过，退出码 0。
- 完整实时矩阵：1440×900 / 390×844 × dark / light × normal / reduced-motion，共 8 组，每组同一 LIVE run 的分阶段轮询；覆盖等待、入场、盖章、预算、阶段、扫描停下、合卷/开卷、9 tab、溢出和浏览器错误。
- 短/中/长标题 × 两尺寸 × 两主题，共 12 组；保存流程、结果及标题截图共 28 张。
- `edge-acceptance.py`：11/11，通过，退出码 0；补充运行中切换 reduced-motion、100 条步骤及滚动、卸载、2 核设备降级。
- 完整矩阵浏览器 console error、pageerror、HTTP error 均为空；未见页面横向溢出。截图核对确认索引卡、细线扫描、状态与标题层级；长标题无截断。
- RAF 采样：最后一轮桌面深色记录运行中一次 60.6ms、首次结果挂载一次 72.7ms 间隔，其余 7 组运行及完成阶段均无 >50ms 间隔。未发现持续卡顿，但不能宣称所有帧均达标或替代真实手机性能测试；保留这两个孤立长帧作为性能限制（验收期间还并行运行过构建，不能据此精确归因）。

证据目录：`frontend/test-results/live-motion/`。主要文件：`final-acceptance.json`、`edge-acceptance.json`、`token-audit.json`；截图前缀 `flow-`、`results-`、`title-`。全页流程截图是在滚动后采集，固定栏会出现在截图当时的视口位置，不代表正常文档流重叠。

## 发现与修复

1. 旧移动规则强制统一大字号：排除已带 Hero 分档 class 的标题，恢复自适应。
2. 实时调查过程默认折叠：pending/合卷时自动展开，让用户看见真实进展；终态后恢复可折叠。
3. 合卷超过 500ms：调整到 480ms；结果展示与开卷串联，tab 指示器在结果挂载后初始化。
4. 动态 reduced-motion 中数字还可能停在插值：kill 数字对象 tween 并立即对齐持久化预算。
5. reduced-motion 残留全局 120ms CSS 淡入：仅进度组件内关闭过渡，50ms 内复测所有内容 opacity=1、transform=none、循环=0。
6. 不可见步骤仍可能扫描/盖章：按可视性限制，离屏及时停止，批量观察通知只同步一次；100 条压力测试通过。
7. 原扫描为大色块：收为 token 定义的 2px、低透明度细线，避免干扰文本。
8. 等待视觉使用未定义 `--border`：修正为 `--border-default`；全量前端源码 token 审计通过。
9. 卸载后 root ref 已清空可能漏清 DOM tween：卸载前保留根元素并清理，补充卸载实测通过。
10. 验收工具问题：初版路由规则误拦截 `/src/api/` 模块，改为精确 API 匹配；旧 Vite HTML proxy 缓存导致测试探针缺失，换独立端口后重跑。未通过改业务绕开测试。

## 本轮文件清单

产品代码仅四处：

- `frontend/src/components/RunProgress.vue`：降级即时显示、卸载清理、可视条目动画限制、细线扫描、token 修正。
- `frontend/src/views/InvestigationView.vue`：标题分档、实时过程展示、合卷/结果开卷生命周期、运行 key、结果挂载后指示器初始化。
- `frontend/src/styles/tokens.css`：标题长度/字号/行高 token，合卷时长修正。
- `frontend/src/styles/folio-ui.css`：移动 Hero 规则与分档兼容。

验收资料：本报告；`frontend/test-results/live-motion/acceptance.py`、`final-acceptance.py`、`edge-acceptance.py`、`harness.html`、`token-audit.mjs` 及相应 JSON/PNG。目录中保留早期回放截图与验收结果，最终以 `final-acceptance.json`、`edge-acceptance.json` 为准。

工作区已有大量 v1–v3 与其他未提交改动，本轮未回退、提交或改写这些无关文件。测试后已停止本轮 5184 端口的 Vite 进程，移除临时 `frontend/.playwright-runtime` 依赖，未停止原有开发/后端服务；所有脚本、截图和 JSON 证据保留。依赖可重新安装恢复，不是业务数据删除。

复跑时在 `frontend` 中用 `python -m pip install --target .playwright-runtime playwright` 恢复测试依赖，启动独立 Vite 端口，在运行脚本的 PowerShell 中设置 `$env:LIVE_MOTION_BASE_URL='http://127.0.0.1:端口'`，分别运行 `python test-results/live-motion/final-acceptance.py` 和 `python test-results/live-motion/edge-acceptance.py`。浏览器使用系统 Edge，无需另下载 Chromium。

## 最终构建、测试与偏离

| 验证 | 结果 |
| --- | --- |
| npm run build | 退出码 0，57 modules，Vite 构建成功 |
| npm test | 退出码 0，30/30，fail=0 |
| git diff --check | 退出码 0，无 whitespace error；仅既有 LF/CRLF 提示 |
| 前端源码颜色/token 扫描 | 31 文件、177 已定义 token，硬编码颜色/未定义 token 问题 0 |

采用用户允许的 mock 多次轮询，而非付费真实联网调查。既有后端离线回放接口曾返回 500（Internal Server Error），不在本轮修复；授权审核接口的 401 属于既有访问控制边界，最终 mock 矩阵没有模拟错误，不等于证明真实审核鉴权或离线回放后端已修好。未改 ProposalGuard 或搜索后端。

没有新增业务能力或改变调用次数/预算/轮询。视觉达到本任务的卷宗叙事与可访问性验收要求；Awwwards/Webby/FWA 获奖属于外部评审结果，不作保证。真实后端端到端稳定性、真机性能与上述孤立长帧是已知限制。
