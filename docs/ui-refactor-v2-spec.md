# 前端 UI 重构 v2 规范 —— 从"仪表盘"到"阅读器"

> 依据：对 Perplexity 设计系统、Deep Research UI（Perplexity / Manus / ChatGPT / Gemini）对比研究、三层信息架构（Answer → Evidence → Process）的提炼。目标：解决 v1 的"信息过载、无焦点、不想读报告"问题。v1 已完成的 GSAP 动效骨架、组件体系、报告创新（进度条/scrollspy/drop cap/引用胶囊）全部保留，本规范是**视觉语言与信息架构的重构**，不是重写。

## 0. 核心设计判断（一句话）

**详情页从"仪表盘"变成"阅读器"：一屏只讲一件事，其他信息让路。**

- 首屏焦点 = 报告/答案（Answer First，参考 Perplexity：问题即标题，紧跟正文，无装饰竞争）。
- 证据（Evidence）= 行内编号引用 + 紧凑来源条目，永远可一瞥验证（参考 Perplexity 双位来源：行内 + 来源面板）。
- 过程（Process）= 收敛为低视觉权重的可折叠区（参考 ChatGPT/Gemini 的可折叠研究步骤；**避免 Manus 式的"全程占屏"**——这正是 v1 杂乱的根源）。
- 情绪关键词：quiet（安静）、sharp（锐利）、credible（可信）、unhurried（不催促）。

## 1. 配色重构（tokens.css 整体重写）

参照 Perplexity 三层背景 + 单一 accent 原则，但保留产品品牌差异化：accent 用**靛蓝**（比 Perplexity 紫更"调查/专业"，比纯蓝更独特），报告正文保留 Fraunces 衬线（书卷质感 DNA）。

### 1.1 浅色（默认值给浅色，但应用**默认深色**，见 1.3）
| Token | 值 | 角色 |
|---|---|---|
| `--bg-base` | `#ffffff` | 页面底 |
| `--bg-surface` | `#f8f8fa` | 卡片/侧栏底 |
| `--bg-elevated` | `#f1f1f4` | hover/弹出层 |
| `--border-default` | `#e4e4e8` | 分隔线/描边 |
| `--border-strong` | `#c9c9d0` | 输入框/强调描边 |
| `--text-primary` | `#101014` | 标题/正文 |
| `--text-secondary` | `#4a4a52` | 次级正文 |
| `--text-muted` | `#8b8b93` | 元信息/占位 |
| `--accent` | `#4f46e5` | 主按钮/焦点/活动态（**每屏只出现一次**） |
| `--accent-hover` | `#4338ca` | accent hover |
| `--accent-subtle` | `#eef0ff` | accent 淡底（仅徽章/选中项） |
| `--success` | `#16a34a` | 已验证 |
| `--warning` | `#d97706` | 待核/警示 |
| `--danger` | `#dc2626` | 争议/错误 |
| `--success-bg`/`--warning-bg`/`--danger-bg` | 各自 8% 透明度淡底 | 徽章底色 |

### 1.2 深色（`[data-theme=dark]`，**默认主题**）
| Token | 值 | 角色 |
|---|---|---|
| `--bg-base` | `#0e0e11` | 页面底 |
| `--bg-surface` | `#17171b` | 卡片/侧栏 |
| `--bg-elevated` | `#202026` | hover/弹出层 |
| `--border-default` | `#2a2a31` | 分隔线 |
| `--border-strong` | `#3c3c46` | 输入框 |
| `--text-primary` | `#f3f3f5` | 标题/正文 |
| `--text-secondary` | `#a4a4ad` | 次级 |
| `--text-muted` | `#6d6d76` | 元信息 |
| `--accent` | `#818cf8` | 主按钮/焦点（每屏一次） |
| `--accent-hover` | `#a5b4fc` | hover |
| `--accent-subtle` | `rgba(129,140,248,.14)` | 淡底 |
| `--success` | `#4ade80` | 已验证 |
| `--warning` | `#fbbf24` | 待核 |
| `--danger` | `#f87171` | 争议 |

### 1.3 主题规则
- **应用默认 `data-theme="dark"`**（search agent 品牌面；useTheme.js 首次加载默认 dark，保留 localStorage/系统偏好逻辑但默认 dark）。
- 删除旧暖纸/墨/琥珀 token；`variables.css` 的兼容别名一并删除（v2 起不再兼容旧类名，一次性扫清硬编码颜色：全仓 grep 旧色值替换）。
- **不用 box-shadow 表达层级**：elevation 用 `bg-surface`→`bg-elevated` + 1px `--border-default` 表达（参考 Perplexity elev-ring）。可保留极淡的 `--shadow-soft`（`0 1px 2px rgba(0,0,0,.04)` 浅色 / `.12` 深色）仅用于浮动层（对话框/预览卡），卡片一律无阴影。
- 语义色只用于"验证状态"类徽章与警示，禁止大面积铺色。

## 2. 排版
- UI 字体：系统栈（`Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`）。
- 报告正文：保留 `--font-serif: "Fraunces", Georgia, serif`（阅读质感），正文 17px / 1.8，行宽 clamp(65ch)。
- 字阶：display 32/600（标题，**不用 700**）、heading-l 22/600、heading-m 18/600、body 15/1.65、body-sm 13、caption 11（来源标签/时间戳）。
- 数字用 `font-variant-numeric: tabular-nums`。
- Section 标签 sentence case（**禁全大写**），overline 风格只用于章节序号。

## 3. 布局收敛（"不知道看哪里"的根治）

### 3.1 详情页首屏（InvestigationView 重构重点）
自上而下严格四层，**每层只做一件事**：
1. **标题行**：报告标题（display）+ 状态徽章（调查完成/进行中）+ 主 CTA（"阅读报告"或"运行回放调查"）。元信息（档案编号/运行状态/声明验证/来源数）从 4 张卡片**收敛为一行紧凑元数据条**（`编号 · 15/15 条已验证 · 11 个来源`，muted 小字，无卡片背景）。
2. **执行摘要卡（新）**：若 run 有报告/摘要，首屏直接展示摘要卡（surface 底、border、radius-lg、内 padding-6）：3-5 句结论 + "阅读完整报告 →"链接到报告 tab。**这是"想读报告"的入口**。
3. **Tab 栏**：9 个 tab 保持（功能不变），视觉改为"等宽小号文字 + 2px 细下划线指示（accent）"，默认文字 secondary、无背景块（参考 Perplexity tab 规则）。
4. **过程/运维信息**（运行守护提醒、运行记录、联网说明、导出等）：移入页面底部一个**可折叠"调查过程"区**（`<details>` 或低对比 panel），不再占据首屏与 tab 竞争注意力。

### 3.2 全局布局
- Sidebar：宽度收窄（约 240px），案例项更紧凑，活动项用 accent-subtle 淡底 + 左侧 2px accent 条（保留），删除多余装饰；主题切换按钮单色图标。
- TopBar：保留 64px + 滚动玻璃，右侧图标统一单色 stroke，主按钮只有一个（accent 只在"主 CTA"出现）。
- 欢迎页：保留大标题+搜索框，装饰更淡（网格 opacity 降到 .02）。

### 3.3 报告阅读器（ReportDetail 强化）
- 阅读列宽 ≤720px 居中（`max-width: 720px; margin-inline: auto`），左侧 scrollspy 目录保留。
- 章节标题：overline 序号 + 标题（sentence case）+ 细分隔线（不用彩色底）。
- 引用胶囊保留；**hover 预览**改为参考 Perplexity 来源条目样式（favicon 圆形 16px + 域名 + 摘录）。
- 阅读进度条、drop cap、版本切换、骨架屏全部保留。

## 4. 组件规则（folio-ui.css 同步）
- 卡片/记录：`bg-surface` + 1px `--border-default` + `radius-lg(12px)`，**无阴影**；hover 仅 `bg-elevated`（或 border-strong）。
- 按钮：主按钮 accent 实底（一屏一个）；次按钮 ghost（描边）；文字按钮 quiet。移除旧"扫光"与所有彩色渐变。
- 徽章：改为"细描边 + 文字色"（`border 1px` + 语义文字色，可带 8% 淡底），不再用实色大底。
- 图标：全部单色（`--text-secondary`），stroke 1.5px，16/20px，禁止彩色图标。
- 输入：`bg-surface` + `border-default` + focus `border-accent` + 2px focus-ring（无 box-shadow）。
- 进度条：细（4px）、surface 底、accent 填充。
- 骨架屏：`bg-elevated` shimmer（保留）。

## 5. 动效（克制化）
- 保留：Hero 轻 stagger（dur .5）、Tab 下划线滑动（保留，更短 240ms）、报告进度条、数字 count up（保留但 800ms）、连接线 draw（保留但线色用 border-strong、更细）。
- 移除/弱化：所有 pulse/扫光/闪烁；列表 stagger 只保留淡入（y 位移 ≤8px）；对话框入场 scale 改 .98→1 fade（200ms）。
- reduced-motion 降级不变；卸载清理不变。

## 6. 验收标准
- `npm run build` 退出码 0；`npm test` 全绿。
- 首屏（详情）自上而下：标题行 → 摘要卡 → tab 栏 → 内容；一屏无超过 3 个"模块竞争"。
- 全仓无旧暖色/琥珀/纸墨硬编码残留（grep 核验：`#f5`, `#8b5`, amber, `--paper`, `--ink` 等）。
- 深色为默认主题，双主题均无阴影表达层级、accent 每屏至多一处。
- 9 个 tab 功能、接口、业务逻辑不变；报告创新功能（进度/scrollspy/drop cap/引用胶囊/版本切换）保留可用。
