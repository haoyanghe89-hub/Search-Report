# 前端重构 v3 交接文档 —— Awwwards / Webby / FWA 获奖级品质标准

> 本文件是「豆包助手」在当前对话中的任务交接书。新对话请先完整读取本文件与下述两份规范，再继续驱动 CodeX 执行。

## 0. 一句话现状

前端已完成两轮重构（v1：组件体系+GSAP 动效；v2：从"仪表盘"到"阅读器"+search-agent 配色），build/test 全绿。**用户对 v2 的评价："还是没有到我的预期"**，要求以 Awwwards、Webby Awards、FWA 获奖级网站为品质标准，从**排版、留白、视觉层级、色彩、动效、微交互、响应式、原创性**八个维度自检并持续优化，直到没有明显可提升之处。

## 1. 项目状态（不可变事实）

- 项目根：`D:\deepsearch`；Git 分支：**`ui-refactor`**（所有改动未 commit/push，用户尚未确认提交）。
- 主前端：`D:\deepsearch\frontend`（Vue 3.4 + Vite 5，仅 vue + gsap 依赖，无重型 UI 框架）。
- 独立子应用 `D:\deepsearch\web`（MarketPulse）不在本次范围。
- 后端：FastAPI，`uv run search-report-api`（离线案例回放无需密钥，可直接验收全部 9 个 tab）。
- 前端 dev：`cd frontend && npm run dev`（默认 5173；验收时前后端需同时启动，.env 已存在）。
- 已完成的 v2 状态：tokens.css/base.css/folio-ui.css 全 token 化、双主题默认深色、首屏四层结构（标题行→元数据条→执行摘要卡→内容）、报告阅读器（720px 居中、17px/1.8 serif、进度条/scrollspy/drop cap/引用胶囊/版本切换）、运维信息折叠、可视化组件减负。`npm run build` 60 模块退出码 0；`npm test` 30/30。

## 2. 硬约束（用户明确要求，不可违反）

- **功能/接口/业务逻辑完全不变**：不改 `src/api`、业务 composables；9 个 tab（overview/agents/sources/evidence/claims/conflicts/timeline/report/review）、props、emit、数据字段不变。
- 不引入重型 UI 框架；动效基于已装 **gsap**（含 ScrollTrigger）；所有视觉数值只用 `tokens.css` 的 token。
- 必须保留 `prefers-reduced-motion` 降级与卸载清理（onUnmounted kill tween/ScrollTrigger/监听）。
- 验收必须跑 `npm run build`（退出码 0）与 `npm test`（30/30）。

## 3. CodeX 操控通道（重要，新对话无此记忆）

- CodeX 桌面应用会话 thread ID：`01a0f59c-4d0a-7e70-a47b-be5102a379c2`（用户在桌面应用里可见该会话）。
- **投递消息**（桌面应用打开会话时用它，桌面会自动消费）：
  `codex queue --thread "01a0f59c-4d0a-7e70-a47b-be5102a379c2" --message "..."`
- 会话日志（查进度/完成事件）：`C:\Users\lenovo\.codex\sessions\2026\10\01\rollout-2026-10-01T11-57-36-01a0f59c-4d0a-7e70-a47b-be5102a379c2.jsonl`；完成事件为 `"type":"task_complete"`，其 `last_agent_message` 含报告；额度中断时该事件带 `error.codex_error_info=usage_limit_exceeded`。
- 备用通道：`Set-Location D:\deepsearch` 后 `codex exec resume`（会话被占用会报 already has an active writer；非交互需 `$null | codex exec`）。
- 每次下发一条完整任务，明确"完成后运行 npm run build + npm test 验证并报告改动与偏离"；逐阶段确认再发下一条。

## 4. 已有设计规范（v3 的起点）

- `D:\deepsearch\docs\ui-refactor-spec.md`：v1 规范（纸墨卷宗概念、组件体系、GSAP 清单、A11y）。
- `D:\deepsearch\docs\ui-refactor-v2-spec.md`：v2 规范（search-agent 阅读器：三层背景、单一靛蓝 accent、默认深色、四层首屏、报告阅读器、动效克制化）。**v3 应在其基础上"做加法"（提升品质），而非推翻。**

## 5. 获奖级设计标准（本轮已调研，直接可用）

### 5.1 Awwwards 评分体系（评委视角）
- 设计 Design 40% / 创意 Creativity 20% / 内容 Content 10%（另有可用性/动效等）；6.5+ 获 Honorable Mention，最高分获 Site of the Day。
- 评委几秒内先看字体选择、间距、层级；再看色彩是否营造情绪并引导注意力。

### 5.2 获奖级共性模式（可执行清单）
1. **Intentional Storytelling**：每次滚动/点击/hover 都在推进叙事，内容渐进揭示（anticipation + reward），而非静态区块堆叠。
2. **Choreographed Motion**：动效是沟通不是装饰——timing/easing/sequencing 精心编排（GSAP ScrollTrigger 的 scrollytelling：章节 reveal、数字滚动、视差层级）。
3. **Typography as Architecture**：排版即设计本体——monumental display（巨型标题）+ intimate body（亲密正文）的强烈尺度对比；负空间作为构图工具；"当有人滚过你的 hero 没停下来，就是排版失败了"。
4. **Micro-Interactions & Hover States**：每个可交互元素都要有完整状态集（default/hover/focus/active/loading/empty/error）。常见获奖手法：
   - Magnetic buttons（按钮向光标磁吸）
   - Letter/word stagger reveal（文本逐字/逐词弹簧入场）
   - Kinetic typography（可变字体轴 hover/scroll 响应：weight/optical size）
   - Page-load curtain（页面载入遮幕滑开，内容露出）
   - Custom cursor（品牌光标 + 标签 morph："READ"/"OPEN"）
   - Ripple/state machines（点击反馈、多状态动画）
5. **Restraint（克制）**：Dieter Rams "Less, but better"。monochrome 模式下靠字重/尺度/节奏/视差做层级；动效揭示结构而非装饰。
6. **Kinetic/Scroll-driven storytelling**：长页叙事（NYT/Pudding 标准）；GSAP ScrollTrigger 成熟可用；注意"与滚动协作而非劫持滚动"。
7. **Micro-interaction 细则**：坐标从实时元素 rect 计算（可滚动页勿用固定值）；每个交互完整键盘路径 + `:focus-visible`。
8. **2026 趋势**：超大可变字体排版、滚动叙事、克制动效（subtle weight shift、gentle elastic）、沉浸式故事化。

### 5.3 落到本产品的原创性方向（供参考，助手可再发挥）
- 产品是"事件调查与证据验证"（数字卷宗 Folio）。可深挖**档案/卷宗/证据链**的原创视觉隐喻：索引卡、证据戳记、印章、纸张质感、编号系统、时间轴叙事——做成记忆点，避免"通用 SaaS 模板感"。
- 让"阅读报告"成为一次有仪式感的旅程：进入报告时遮幕/翻页过渡、章节标题的编辑感、引用胶囊的"开卷"交互。

## 6. 建议执行方式

1. 先读 §5 与两份规范；向 CodeX 下发"v3 品质标准"与八维自检协议（排版/留白/视觉层级/色彩/动效/微交互/响应式/原创性）。
2. 分 2-3 轮下发：v3.1 排版+留白+层级+色彩硬核打磨；v3.2 动效+微交互+响应式；v3.3 原创性包装 + 八维自检迭代（每轮 CodeX 自检打分→优化→重测，直到无明显可提升项）。
3. 每轮后人工用浏览器（localhost:5173 + 离线案例）抽查截图；最终 build + test 全绿后向用户交付，确认后再决定是否 commit。

## 7. 待办提醒
- 所有改动仍在 `ui-refactor` 分支未提交；交付后需用户确认是否 commit。
- CodeX 账号额度此前因用量中断过（约 2 小时后自动重置）；若再遇 usage_limit_exceeded，可稍等或用备用 exec 通道。
