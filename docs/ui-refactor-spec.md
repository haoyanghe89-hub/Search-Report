# 前端 UI 重构设计规范（Digital Folio · 数字卷宗）

> 目标：在**功能与接口完全不变**的前提下，将 `frontend/`（Vue 3 + Vite）从"demo 感"重构为**高级、简约、有质感、带创新交互动效**的产品级界面。
> 原则：**进化而非推翻**现有"纸墨卷宗"方向——保留卷宗/编辑部的气质，升级执行精度、双主题、动效体系与阅读体验。
> 本文是 CodeX 执行的唯一视觉依据，所有数值为硬约束。

---

## 1. 设计理念

- **关键词**：数字卷宗（Digital Folio）、现代编辑部、克制、留白、纸墨质感、琥珀高光。
- **高级感 = 提前定好的规则**：统一的色板、字阶、间距栅格、阴影层级与动效语言；任何组件不得自造数值，只能引用 token。
- **质感来源**：细腻的中性色阶、低饱和点缀、克制的多层暖调阴影、玻璃拟态（仅用于浮动层）、精确到像素的对齐与节奏。
- **创新但不炫技**：动效服务于层级与反馈，遵循物理缓动；首屏可惊艳，日常使用需安静。
- **双主题**：浅色（温润纸白）为默认，深色（暖墨黑 + 琥珀金高光）为高级模式，二者共享组件、仅切换 token。

---

## 2. 设计 Token（写入 `src/styles/tokens.css`，替换现 `variables.css`）

### 2.1 色彩 · 浅色主题（`:root` / `[data-theme="light"]`）

```css
/* 背景层级（从底到浮） */
--bg-canvas:        #F7F3EC;  /* 页面底色 */
--bg-surface:       #FCFAF5;  /* 卡片/面板 */
--bg-surface-raised:##FFFFFF;/* 浮层/对话框 */
--bg-subtle:        #EFE8DB;  /* 次级/凹陷区域 */
--bg-hover:         rgba(60, 45, 20, 0.045);
--bg-active:        rgba(60, 45, 20, 0.08);

/* 文字（墨色） */
--text-primary:     #1C1610;
--text-secondary:   #4A3F30;
--text-muted:       #6B5D4A;
--text-faint:       #9A8C74;
--text-disabled:    #BDB29E;
--text-on-accent:   #FCFAF5;

/* 边框 */
--border-subtle:    rgba(60, 45, 20, 0.08);
--border-default:   rgba(60, 45, 20, 0.14);
--border-strong:    rgba(60, 45, 20, 0.24);

/* 琥珀点缀（收敛） */
--accent:           #8B5A2B;
--accent-hover:     #734A22;
--accent-active:    #5E3C1B;
--accent-subtle:    rgba(139, 90, 43, 0.09);
--accent-line:      rgba(139, 90, 43, 0.28);
--accent-ring:      rgba(139, 90, 43, 0.35);

/* 验证/状态语义色（低饱和、沉稳；文字色 + 同色 subtle 底） */
--verified:  #3D6B45;  --verified-bg:  rgba(61, 107, 69, 0.11);
--probable:  #97741C;  --probable-bg:  rgba(151, 116, 28, 0.11);
--disputed:  #A3441F;  --disputed-bg:  rgba(163, 68, 31, 0.11);
--unverified:#8A7E6A;  --unverified-bg:rgba(138, 126, 106, 0.13);
--info:      #3E5F8A;  --info-bg:      rgba(62, 95, 138, 0.10);
--danger:    #B43E2E;  --danger-bg:    rgba(180, 62, 46, 0.10);
```

### 2.2 色彩 · 深色主题（`[data-theme="dark"]`）

```css
--bg-canvas:        #14110C;  /* 暖墨黑 */
--bg-surface:       #1C1813;
--bg-surface-raised:#252019;
--bg-subtle:        #100E0A;
--bg-hover:         rgba(239, 231, 216, 0.06);
--bg-active:        rgba(239, 231, 216, 0.10);

--text-primary:     #EFE7D8;
--text-secondary:   #C4B8A2;
--text-muted:       #9A8E78;
--text-faint:       #6E6553;
--text-disabled:    #524A3C;
--text-on-accent:   #14110C;

--border-subtle:    rgba(239, 231, 216, 0.08);
--border-default:   rgba(239, 231, 216, 0.15);
--border-strong:    rgba(239, 231, 216, 0.26);

--accent:           #D09A5C;  /* 琥珀金高光 */
--accent-hover:     #DDAE74;
--accent-active:    #BE8849;
--accent-subtle:    rgba(208, 154, 92, 0.15);
--accent-line:      rgba(208, 154, 92, 0.32);
--accent-ring:      rgba(208, 154, 92, 0.40);

--verified:  #7FB384;  --verified-bg:  rgba(127, 179, 132, 0.14);
--probable:  #D9B45A;  --probable-bg:  rgba(217, 180, 90, 0.14);
--disputed:  #DD8A66;  --disputed-bg:  rgba(221, 138, 102, 0.14);
--unverified:#A99E88;  --unverified-bg:rgba(169, 158, 136, 0.14);
--info:      #88A9CE;  --info-bg:      rgba(136, 169, 206, 0.14);
--danger:    #E08172;  --danger-bg:    rgba(224, 129, 114, 0.14);
```

主题切换：`<html data-theme="...">`，选择写入 `localStorage`，首次访问跟随 `prefers-color-scheme`；TopBar 提供日/夜切换按钮（带 320ms 图标过渡）。

### 2.3 字体排印

```css
--font-display: 'Fraunces', 'Noto Serif SC', Georgia, serif;   /* 大标题/节标题 */
--font-serif:   'Cormorant Garamond', 'Noto Serif SC', Georgia, serif; /* 导语/引用/报告正文 */
--font-sans:    'Inter', -apple-system, 'Noto Sans SC', system-ui, sans-serif; /* UI 与数据 */
--font-mono:    'JetBrains Mono', 'SFMono-Regular', Consolas, monospace;
```

- 可变字体 `Fraunces` 启用 `opsz`、`wght` 300–700、`ital`；中文标题用 Noto Serif SC 500/600。
- **字阶（size / line-height / 字重 / 字距）**：
  | token | size | line | weight | letter | 用途 |
  |---|---|---|---|---|---|
  | display-xl | 52 | 1.12 | 500 | -0.02em | Hero 主标题 |
  | h1 | 34 | 1.2 | 560 | -0.015em | 页面标题 |
  | h2 | 25 | 1.3 | 600 | -0.01em | 板块/报告节标题 |
  | h3 | 19 | 1.4 | 600 | 0 | 卡片标题 |
  | h4 | 16 | 1.5 | 600 | 0 | 子标题 |
  | body-lg | 16 | 1.75 | 400 | 0 | 中文正文/报告 |
  | body | 14 | 1.65 | 400 | 0 | UI 正文 |
  | small | 13 | 1.55 | 400 | 0 | 辅助 |
  | caption | 12 | 1.5 | 500 | 0.02em | 标签 |
  | overline | 11 | 1.4 | 500 | 0.14em | 大写小标（mono，uppercase） |
- 中文正文不使用斜体；斜体仅用于拉丁/导语；数字与英文用 tabular-nums（`font-variant-numeric: tabular-nums`）。
- 段落最大行宽 68–72 字符；报告正文栏宽 720–780px。

### 2.4 间距（4px 基准）

```css
--space-1:4; --space-2:8; --space-3:12; --space-4:16; --space-5:20;
--space-6:24; --space-8:32; --space-10:40; --space-12:48;
--space-16:64; --space-20:80; --space-24:96; --space-32:128;
```
垂直节奏使用 8 的倍数；卡片内边距 `--space-6`（紧凑 `--space-4`）；板块间距 `--space-24`。

### 2.5 圆角 / 阴影 / 模糊 / 边框

```css
--radius-xs:4; --radius-sm:6; --radius-md:8; --radius-lg:12;
--radius-xl:16; --radius-2xl:20; --radius-full:999px;
/* 卡片 lg；按钮 md；输入 md；徽章 full；对话框 xl；小标签 sm */

--shadow-xs: 0 1px 2px rgba(60,45,20,.05);
--shadow-sm: 0 1px 3px rgba(60,45,20,.06), 0 1px 2px rgba(60,45,20,.04);
--shadow-md: 0 4px 14px rgba(60,45,20,.08);
--shadow-lg: 0 14px 34px rgba(60,45,20,.11);
--shadow-xl: 0 26px 66px rgba(60,45,20,.17);   /* 对话框 */
/* 深色主题阴影统一用 rgba(0,0,0,.x)，透明度 .2/.32/.45，并靠 border-subtle 形成顶部微光 */

--blur-sm:8px; --blur-md:12px; --blur-lg:20px;
--ring: 0 0 0 2px var(--bg-canvas), 0 0 0 4px var(--accent-ring); /* focus */
```

### 2.6 动效 token

```css
--dur-xs:120ms; --dur-sm:200ms; --dur-md:320ms; --dur-lg:480ms; --dur-xl:640ms;
--ease-standard: cubic-bezier(.2, 0, 0, 1);
--ease-emphasized: cubic-bezier(.2, 0, .2, 1);
--ease-out-expo: cubic-bezier(.16, 1, .3, 1);
--ease-in-out: cubic-bezier(.65, 0, .35, 1);
```

---

## 3. 核心组件规范

- **按钮**
  - 主按钮：bg `--accent`（深色主题为琥珀金）、色 `--text-on-accent`、高 40、padding 0 20、radius `--radius-md`；hover 加深 + `--shadow-md`；active `scale(.98)`；过渡 200ms standard。
  - 次按钮：透明底、1px `--border-default`、字 `--text-secondary`；hover 边框 accent + `--accent-subtle` 底。
  - 文字按钮（quiet）：无框，hover `--bg-hover`，仅含文字与可选箭头（箭头 hover 时 x+3）。
  - 禁用：opacity .45、cursor not-allowed；focus-visible 使用 `--ring`。
  - **移除现有"按钮扫光"动画**（显廉价）。
- **卡片**：bg `--bg-surface`、border 1px `--border-subtle`、radius `--radius-lg`、padding `--space-6`；可点击卡片 hover：border `--border-default` + `--shadow-md` + y-2，过渡 320ms。
- **徽章/状态 badge**：高 22、padding 0 10、radius `--radius-full`、caption 字号、底色为对应 `--*-bg`、字色为对应语义色；**不再使用深色实心底**。
- **输入/搜索框**：高 44、bg `--bg-surface`、border `--border-default`、radius `--radius-md`、padding 0 14；focus：border accent + `--accent-ring` 外发光；占位符用 `--text-faint`。
- **对话框（dialog）**：bg `--bg-surface-raised`、radius `--radius-xl`、`--shadow-xl`、padding 24–28；遮罩 `rgba(20,15,8,.45)` + `--blur-sm`；进入：opacity 0→1 + scale .96→1（200ms ease-out-expo），退出反向 160ms。
- **骨架屏**：基于 `--bg-subtle` 的块 + 1.2s 左右往返的 shimmer（浅色高光 rgba(255,255,255,.5)，深色 rgba(255,255,255,.06)）。
- **空状态**：线性图标（1.5 描边、accent/faint、64px）+ h3 标题 + small 描述 + 可选主按钮；居中、上下留白 64。
- **提示 notice**：弱化处理为 `--accent-subtle`/语义底色 + 左侧 3px 语义竖线 + body 字号；**不用荧光色块**。
- **表格**：表头 overline 风格、字 `--text-muted`；行分隔 `--border-subtle`；行 hover `--bg-hover`；数字右对齐、tabular-nums。

---

## 4. 布局骨架

- **Sidebar（260px）**：bg `--bg-surface`、右侧 1px `--border-subtle`；品牌区（display 小字 + overline）；案例项：圆角 md、padding 10–12、hover `--bg-hover`；活动项：`--accent-subtle` 底 + 左侧 2px accent 指示条 + 字色 primary；分组标题 overline。底部放主题切换与"新对话"。
- **TopBar（高 64，sticky top 0）**：默认透明；页面滚动 > 8 后 bg `rgba(canvas,.8)` + `--blur-md` + 底部 border；左侧案例标题（h4）+ 分类徽章；右侧：搜索（Cmd+K 提示）、导出、主题切换。
- **内容栅格**：max-width 1200（概览）/ 780（报告正文）；水平 padding 64（桌面）→ 32（平板）→ 20（手机）。
- **欢迎页**：垂直居中偏上；overline 小标 → display-xl 大标题（支持逐行 reveal）→ 副标题 → 居中大搜索框；背景加入极淡的纸纹/网格（opacity .03，纯装饰，不干扰）。
- **Hero（调查详情）**：overline tag → display-xl 标题 → 导语（serif、左竖线）→ 4 项 meta（等宽、分隔线）→ 操作按钮组；入场见 §5。

---

## 5. 动效清单（GSAP + ScrollTrigger，按需 import）

1. **首屏/欢迎页**：标题按行 `clip-path inset` + y 24→0 reveal（stagger 90ms，dur 700，ease-out-expo）；搜索框与提示延迟 250ms 淡入上移。
2. **Hero 入场**：tag → title → lede → meta row → actions 依次 fade + y 16，stagger 80ms。
3. **滚动触发**：各板块标题下划线（scaleX 0→1，transform-origin left）；卡片/记录列表 `ScrollTrigger.batch` fade-up（y 24、opacity 0、stagger 70）；只在进入视口播放一次。
4. **数字计数**：证据链 4 个数字进入视口时 `gsap.to` count up（1.2s，ease-out）。
5. **AgentFlow / 证据链**：节点依次显现；连接线用 `stroke-dashoffset` 绘制（draw，dur .9）。
6. **Tab 切换**：内容区 Vue `<Transition>`：旧 opacity 1→0/y 0→-8（150ms），新 opacity 0→1/y 8→0（260ms ease-out）；Tab 指示条用弹性/标准缓动滑动跟随（320ms）。
7. **对话框/弹窗**：scale .96 + fade（见 §3）。
8. **微交互**：按钮 active、卡片 hover 用 CSS；列表项 hover 位移用 CSS；**禁止**滥用弹跳与旋转。
9. **降级**：`prefers-reduced-motion: reduce` 时关闭所有位移/绘制，仅保留 120ms 透明度过渡。

GSAP 引入方式：`import gsap from 'gsap'`、`import { ScrollTrigger } from 'gsap/ScrollTrigger'`；在 `onMounted` 注册、`onUnmounted` `kill()` 所有 tween/trigger，避免切换案例后泄漏。

---

## 6. 各板块重构要点

- **概览**：AgentFlow、证据链改为精致卡片 + 可视化节点（§5.5）；时间线/关键声明双列卡片化；空状态统一。
- **来源 / 证据 / 声明列表**：统一"记录卡片"样式（标题 + 徽章 + 元信息行 + 折叠详情）；筛选框固定在列表上方；证据引用块使用 serif + 左竖线 + `--bg-subtle` 底；操作按钮改为小尺寸次按钮。
- **冲突与缺口**：严重度用语义色左边框 + 卡片；长 JSON 折叠在等宽代码块（bg subtle、radius md）。
- **时间线**：竖向轴线（1px border）+ 节点圆点（语义色）+ 日期 mono + 内容卡片；滚动 stagger 入场。
- **审核面板 / RunProgress / Recovery / History**：套用统一卡片、按钮、进度条（高 6、圆角 full、accent 填充、带过渡）；进度文字用 small + tabular。

### 6.1 报告板块（本次重点，见 §7）

---

## 7. 报告板块专项重构（重点创新）

1. **顶部工具行**：版本选择（FolioSelect 套用统一输入/下拉样式）+ 生成新版报告（主按钮）+ 导出 Markdown（次按钮）；报告类型/发布/审核状态合并为一行低调 meta（small + 徽章），不再用大 notice。
2. **阅读进度条**：报告区顶部 2px accent，`scaleX` 随滚动进度（ScrollTrigger 或 scroll listener，rAF 节流）。
3. **粘性目录（outline）**：
   - 桌面：报告正文左侧 220px 粘性目录（或正文上方折叠目录）；`IntersectionObserver` 做 scrollspy，当前节高亮 accent；点击 `scrollIntoView({behavior:'smooth'})`。
   - 移动：折叠为"目录"下拉。
4. **正文排版**：
   - 节标题：Fraunces h2，带 overline 编号（如 `01 · 执行摘要`），节间留白 `--space-20` + 细分隔。
   - 执行摘要首段可加 **drop cap**（首字 3.2 行高、Fraunces、accent）。
   - 正文 `--font-serif`/中文 Noto Serif SC，行高 1.9，段间距 0.9em；表格、列表统一组件样式。
   - "证据不足"占位用 small + faint，不放大段灰字。
5. **引用溯源（核心交互）**：
   - 正文引用由 `[n]` 改为**琥珀色胶囊上标**（accent-subtle 底、accent 字、圆角 full、hover accent 底反白 + y-1）。
   - hover（桌面，120ms 延迟）显示轻量预览 tooltip：声明状态徽章 + 证据摘录前 2 行。
   - 点击弹出**溯源对话框**（复用 §3 对话框规范）：声明与验证状态 → 证据原文（serif 引用块）→ 来源标题/发布方/时间 → 原文链接与归档正文 → 折叠定位元数据；进入动画 scale+fade。
6. **版本切换**：切换版本时正文区 fade+slide 过渡（同 Tab 过渡），加载中显示骨架屏而非空白。
7. 报告 hash 等技术信息折叠处理。

---

## 8. 可访问性（A11y）

- 所有文字/背景对比度满足 WCAG AA（正文 ≥ 4.5:1，大字 ≥ 3:1）。
- 全局 `:focus-visible` 使用 `--ring`；交互元素具备 aria-label；对话框实现焦点陷阱与 Esc 关闭。
- 尊重 `prefers-reduced-motion`；语义化标题层级（h1→h2→h3 不跳级）。
- 图片/图标装饰性内容 `aria-hidden`。

---

## 9. 分阶段执行计划（CodeX 每阶段一个 turn，完成后构建自检）

- **阶段 0 · 安全准备**：确认工作区已提交；创建分支 `ui-refactor`（若未存在）；不得改动 `src/api`、`composables` 业务逻辑与任何接口路径。
- **阶段 1 · Token 与全局底座**：新建 `tokens.css`（双主题全部变量）、重构 `base.css`（reset、排版、滚动条、选区、focus）；`main.js` 引入；实现主题切换逻辑（composable `useTheme`）。
- **阶段 2 · 布局骨架**：Sidebar、TopBar（滚动响应、主题切换按钮）、欢迎页背景装饰。
- **阶段 3 · 通用组件样式**：按钮、卡片、徽章、输入、对话框、骨架、空状态、表格、进度条的全局/统一样式落地，移除旧扫光。
- **阶段 4 · 调查详情**：Hero 入场、Tab 指示与内容过渡、概览（AgentFlow、证据链、双列）。
- **阶段 5 · 列表板块**：来源、证据、声明、冲突、时间线（含时间线可视化）。
- **阶段 6 · 报告板块**：按 §7 全部实现（进度条、粘性 scrollspy 目录、排版、引用胶囊与预览、溯源对话框、版本过渡、骨架屏）。
- **阶段 7 · 其余面板**：RunProgress、RunHistory、RunRecovery、ReviewPanel、OperationsNotice、NewInvestigationModal、FolioSelect 统一化。
- **阶段 8 · 全量质检**：`npm run build` 无错误；用 **Playwright MCP** 逐页打开（欢迎页、9 个 tab、报告、弹窗、深色模式、移动视口）检查点击、错位、滚动与控制台错误，发现问题自行修复并复验；输出质检结论。

## 10. 验收标准

- `npm run build` 通过，无控制台 error；所有原有功能（新建/启动/取消/回放/刷新/生成报告/导出/溯源/审核/搜索）行为不变。
- 双主题完整、切换无闪烁；9 个 tab 与欢迎页视觉统一、无 demo 感。
- 动效流畅（60fps、无布局抖动）且 reduced-motion 可降级。
- 代码遵循 Ponytail：复用现有依赖与 token，不引入额外重型 UI 框架；新增样式集中管理、命名统一。
