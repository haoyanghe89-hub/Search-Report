# UI Refactor v3.3 八维自检

本记录以 `docs/ui-refactor-v3-handoff.md`、v1/v2 规范与 v3.3 任务书为唯一设计依据。评分只覆盖本轮允许修改的前端呈现层，不代表第三方内容质量或后端数据完整性。

| 维度 | 初始分 | 具体发现 | 处理 | 最终分 | 验证 |
| --- | ---: | --- | --- | ---: | --- |
| Typography | 9.1 | `ReportDetail.vue` 的 720px 正文列已有 17px/1.8，但未显式启用字偶距，段落短尾缺少行尾优化。 | `base.css` 启用正常 kerning；报告段落增加 `text-wrap: pretty`；保留 display/body 的 64px→17px 尺度反差。 | 9.6 | build 0；test 30/30；diff check 通过 |
| Whitespace | 9.0 | 1100px 容器扣除双侧内边距后，224px 目录 + 48px gap 会挤压目标 720px 报告列。 | `ReportDetail.vue` 将目录收敛为 208px、沟槽收敛为 32px，使 720px 阅读列完整落入可用宽度；卡片仍保持 24px/移动端 16px 内边距。 | 9.6 | build 0；test 30/30；diff check 通过 |
| Hierarchy | 9.1 | Hero 状态戳与 48–64px 标题垂直居中，短标题时视觉权重偏高；摘要标签仍像普通卡片标题。 | 状态戳改为标题上缘小幅挂接；摘要改为 `FOLIO BRIEF / 执行摘要` 的 mono overline；仍只保留一个 accent 实底 CTA。 | 9.6 | build 0；test 30/30；diff check 通过 |
| Color | 8.9 | 主文字双主题对比度满足 7:1，但 11px 元数据的 muted token 在浅/深主题下偏弱。 | 仅提高 `--text-muted` 双主题对比度；保留三层中性背景、单一靛蓝 accent 和 8% 语义淡底；硬编码颜色仍只在 `tokens.css`。 | 9.7 | build 0；test 30/30；diff check 通过 |
| Motion | 9.2 | Hero/ScrollTrigger/Tab/开卷均已 token 化且不劫持滚动；新建调查 Dialog 未监听运行时 reduced-motion 切换。 | `dialogMotion.js` 增加可选最终态收口；`NewInvestigationModal.vue` 实时监听并卸载 media listener；报告 Dialog 同步即时落到可见最终态。 | 9.7 | build 0；test 30/30；diff check 通过 |
| Micro-interactions | 9.1 | 按钮/卡片/输入/引用/Dialog/骨架状态完整；`FolioSelect.vue` 菜单仍使用孤立 CSS keyframe，运行时 reduced-motion 不会即时收口。 | 菜单入场迁移到 token 驱动 GSAP；补齐 media listener、kill 清理和最终态；保留键盘列表框语义与原 emit。 | 9.7 | build 0；test 30/30；diff check 通过 |
| Responsive | 9.0 | `max-width: 48rem` 将精确 768px 错归手机抽屉；Playwright 又复现 844×390 下 case-list 被底部回放块压成 0px 并发生点击遮挡。 | 统一以 `width < 48rem` 启用手机布局；短横屏桌面 Sidebar 改为整体纵向滚动、案例列表保留内容高度，消除层叠与点击拦截。 | 9.7 | 源码轮 build 0/test 30/30；短横屏修复后待最终矩阵复验 |
| Originality | 8.8 | 编号、戳记、索引卡、开卷、时间戳和档案空状态已形成记忆点；浏览器标题仍为“调查学报”，首页 overline 未进入编号语法。 | 统一为“数字卷宗 · Digital Folio”；首页使用 `DOSSIER 00 / DIGITAL FOLIO`；A1–A6 共享 mono overline、细描边和无阴影档案语言。 | 9.6 | build 0；test 30/30；diff check 通过；截图人工核对通过 |

## 原创性落地映射

- A1 编号系统：`SectionHeading.vue`、报告目录/章节、来源/证据/声明/时间线统一使用 `SECTION / SOURCE / EXHIBIT / CLAIM / CASE TIME`。
- A2 证据戳记：证据关系、声明验证、引用溯源使用 mono、细描边、轻微旋转的单色 stamp；普通元数据 badge 不滥用。
- A3 索引卡：来源与证据卡增加左上编辑编号、较强细边框、无阴影；保留三层背景，不叠加纸张噪点。
- A4 报告仪式：`ReportDetail.vue` 首次进入以 480ms 淡入/上移完成“开卷”，不遮屏、不锁滚动，reduced-motion 直接显示。
- A5 时间轴叙事：预览与完整时间线增加 `CASE TIME` 等宽编号、tabular 日期、节点与细连接线。
- A6 品牌细节：Sidebar `DF / ARCHIVE`、首页 `DOSSIER 00`、档案式空状态图示、`CASE FILE` 骨架语气和统一页面标题。

## Playwright 最终验收

- 运行环境：项目 `.venv` 后端 + Vite 前端 + Python Playwright 驱动本机 Edge（headless）。
- 视口：1440×900、1366×768、1024×768、768×1024、390×844、360×640、844×390；每档均覆盖 dark/light。
- 结果：77/77 检查通过；文档无横向溢出，768px 平板边界正确，390/360 Drawer 在视口内且主触控目标不小于 44px，844×390 Sidebar 可滚动且不再遮挡案例卡。
- 功能：9 个 tab 全部可达；报告 v3→v2 版本切换、17 节 scrollspy、阅读进度 100%、引用 hover 预览、溯源 Dialog 打开/关闭、证据戳记、CTA 磁吸与卡片 hover 均通过。
- 降级：reduced-motion 下 `scroll-behavior: auto`，Hero/报告/章节 opacity 均为 1，无隐藏内容或位移入场。
- 控制台：无 page error、无非预期 console error；审核 tab 未登录时 `/review/current` 的 401 是现有鉴权流程的预期响应。
- 修复：844×390 Sidebar 列表被压成 0px；reduced-motion 报告/Tab 的短暂 opacity 过渡；favicon 404；三处测试等待/定位误判。
- 证据：`frontend/test-results/v3-3/acceptance.json` 与同目录截图。
