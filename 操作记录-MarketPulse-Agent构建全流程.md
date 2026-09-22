# MarketPulse Agent 构建全流程操作记录

> 场景考核要求：给定一个真实问题场景，在限定时间内构建一个能够
>
> **自主搜索、分析并输出结果**
>
> 的 Agent，重点考察系统设计、调试思路与工程能力。
> 本文档记录：① 我用命令行操控你电脑上的 Codex 完成构建的
>
> **全过程与真实命令**
>
> ；② 同一操作在你手动操作桌面版 Codex 时应输入的 
>
> **Prompt**
>
> 。



***

## 一、场景设定



| 项目     | 内容                                                                                     |
| ------ | -------------------------------------------------------------------------------------- |
| 问题场景   | SaaS 公司计划进入「AI 会议纪要」市场                                                                 |
| 构建目标   | **MarketPulse Agent**：输入任意产品方向 / 关键词 → 自主联网搜索市场 / 竞品 / 定价 → 分析 → 输出中文 Markdown 市场可行性报告 |
| 核心能力   | 自主搜索、分析、结构化输出（Go / Conditional Go / No-Go 建议）                                          |
| LLM 引擎 | DeepSeek（`DEEPSEEK_API_KEY` 环境变量，你的真实 key）                                             |
| 最终成果   | Python 3.11+ 包 + FastAPI + React/shadcn 可视化前端，32 项测试通过                                 |



***

## 二、环境准备（一次性）

### 2.1 安装 9 个 Skills 到 Codex



```
\# 9 条命令（来自你的 product-engineer-agent-skills-clean.md）

npx skills add obra/superpowers --skill brainstorming -a codex --copy -y

npx skills add obra/superpowers --skill writing-plans -a codex --copy -y

npx skills add anthropics/skills --skill frontend-design -a codex --copy -y

npx skills add shadcn-ui/ui --skill shadcn -a codex --copy -y

npx skills add https://github.com/openai/plugins/tree/main/plugins/openai-developers/skills/agents-sdk -a codex --copy -y

npx skills add obra/superpowers --skill executing-plans -a codex --copy -y

npx skills add vercel-labs/agent-browser -a codex --copy -y

npx skills add obra/superpowers --skill systematic-debugging -a codex --copy -y

npx skills add obra/superpowers --skill verification-before-completion -a codex --copy -y
```

安装后 Skill 位于 `C:\Users\lenovo\.codex\skills\`（用户级，Codex 任意目录可用）。

### 2.2 安装 standalone Codex CLI（桌面版环境需要）



```
irm https://chatgpt.com/codex/install.ps1 | iex

\# 安装后路径：C:\Users\lenovo\\.codex\packages\standalone\current\bin\codex.exe
```

### 2.3 配置 DeepSeek API Key（供 Agent 运行时使用）



```
setx DEEPSEEK\_API\_KEY "sk-你的key"
```

> 备注：key 只写入用户环境变量，不进代码、不进 .env、不进日志。

### 2.4 关键经验：CLI 与桌面版的关系

**现象**：`codex exec "..."`（非交互模式）在你电脑上**持续挂起**（无网络连接、CPU≈0）。

**排查**：已排除模型、认证、配置、代理、干净 CODEX\_HOME 等因素；根因是桌面版 Codex 持有 app-server/IPC 且走 [chatgpt.com](https://chatgpt.com) 内部认证，CLI 无法独立直连 OpenAI API（auth.json 的 key 直调 [api.openai.com](https://api.openai.com) 返回 401）。

**解法**：改用 `codex queue`**&#x20;命令投递消息到桌面版会话队列**，由你桌面上打开的 Codex 消费执行 —— 完全可用（毫秒级返回），且你能实时看到 Codex 干活。



***

## 三、6 阶段操控记录（命令 + 可复用 Prompt）

> 统一变量：会话名 
>
> `marketpulse-agent`
>
> ，thread id 
>
> `01a0acff-dd2b-7792-bbb9-0cbdac1e508b`
> 工作目录：
>
> `C:\Users\lenovo\Doubao\chats\2026-09-16\new-chat\marketpulse-agent`

### 阶段 1/6：brainstorming（需求澄清与 MVP 收敛）

**我的实际命令（PowerShell）**：



```
\$codex = "C:\Users\lenovo\\.codex\packages\standalone\current\bin\codex.exe"

& \$codex queue --thread "01a0acff-dd2b-7792-bbb9-0cbdac1e508b" --message "【任务阶段 1/6 - brainstorming 需求澄清】请先阅读并使用 brainstorming skill（C:\Users\lenovo\\.codex\skills\brainstorming\SKILL.md）。场景：SaaS 公司计划进入 AI 会议纪要市场，构建 MarketPulse Agent：输入关键词 → 自主联网搜索市场/竞品/定价 → 分析 → 输出中文 Markdown 可行性报告。请提出最多 5 个关键澄清问题、比较 2-3 个方案、收敛 MVP 范围，写入 docs/01-brainstorming.md。只做澄清，禁止写代码。工作目录：C:\Users\lenovo\Doubao\chats\2026-09-16\new-chat\marketpulse-agent"
```

**过程要点**：Codex 消费消息后按 brainstorming skill 逐条提问（MVP 形态、市场范围……），我通过 queue 逐条回复：



```
\# 我回复 1（选 CLI 形态）

& \$codex queue --thread "01a0acff-dd2b-7792-bbb9-0cbdac1e508b" --message "选择 A：CLI 单次运行，输入关键词后生成 Markdown 报告。请继续收敛 MVP 并写入 docs/01-brainstorming.md。"

\# 我回复 2（选全球市场 + 授权自主决策）

& \$codex queue --thread "01a0acff-dd2b-7792-bbb9-0cbdac1e508b" --message "选择 A：全球市场，英文网页为主，中文报告。后续澄清问题请基于推荐项自主决策，直接收敛 MVP 并写入 docs/01-brainstorming.md。"
```

**你在桌面版应输入的 Prompt**（新建会话后直接粘贴）：



```
请先阅读并使用 brainstorming skill 来规范流程。

场景：我们是一家 SaaS 公司，计划进入「AI 会议纪要」市场，今天要在限定时间内构建一个 MarketPulse Agent：用户输入任意产品方向/关键词，Agent 能自主联网搜索市场、竞品、定价信息，分析后输出结构化市场可行性报告。

请提出最多 5 个关键澄清问题（说明为什么重要），比较 2-3 个可行方案，收敛 MVP 范围（做什么/不做什么/验收标准），将结论写入 docs/01-brainstorming.md。只做澄清与方案收敛，禁止写代码。

（然后按它的提问回答即可，例如：MVP 形态选 A-CLI；市场范围选 A-全球。）
```

**阶段结果** ✅：`docs/01-brainstorming.md`（15.8KB），收敛 MVP：OpenAI Agents SDK + 显式阶段编排、CLI 输入、中文 Markdown 报告。



***

### 阶段 2/6：writing-plans（技术方案拆解）

**我的实际命令**：



```
& \$codex queue --thread "01a0acff-dd2b-7792-bbb9-0cbdac1e508b" --message "【任务阶段 2/6 - writing-plans】请先阅读并使用 writing-plans skill（C:\Users\lenovo\\.codex\skills\writing-plans\SKILL.md）。基于 docs/01-brainstorming.md 已收敛的 MVP，拆解可执行 implementation plan：项目结构与模块划分、每个任务的详细步骤（涉及文件/实现要点/依赖）、每项任务的量化验收条件、风险点与调试预案。写入 docs/02-implementation-plan.md。只写计划不写代码。工作目录：C:\Users\lenovo\Doubao\chats\2026-09-16\new-chat\marketpulse-agent"
```

**你在桌面版应输入的 Prompt**：



```
请先阅读并使用 writing-plans skill 来规范流程。

基于 docs/01-brainstorming.md 已收敛的 MVP（OpenAI Agents SDK + 显式阶段编排；CLI 输入；中文 Markdown 报告），拆解出可执行的 implementation plan：项目结构与模块划分、每个实现任务的详细步骤（涉及文件、实现要点、依赖关系）、每项任务的验收条件（可量化）、风险点与调试预案（联网失败/解析失败/超时等）。

将完整计划写入 docs/02-implementation-plan.md。只写计划，不要写实现代码。
```

**阶段结果** ✅：`docs/02-implementation-plan.md`（44KB），10 个按依赖排序的 TDD 任务，技术基线锁定 `openai-agents==0.22.2`。



***

### 阶段 3/6：agents-sdk + executing-plans（核心实现）

**我的实际命令**：



```
& \$codex queue --thread "01a0acff-dd2b-7792-bbb9-0cbdac1e508b" --message "【任务阶段 3/6 - 实现核心】请先阅读并使用 agents-sdk skill 与 executing-plans skill。按 docs/02-implementation-plan.md 开始实现，注意【关键工程约束】：1) LLM 引擎必须用 DeepSeek OpenAI 兼容 API（base\_url=https://api.deepseek.com，模型 deepseek-chat，key 从环境变量 DEEPSEEK\_API\_KEY 读取；用 set\_default\_openai\_client 注入自定义 AsyncOpenAI client 并关闭 tracing）；2) 搜索不得依赖 OpenAI 托管 WebSearchTool，请实现无需额外 API key 的联网搜索自定义工具（如 DuckDuckGo，做好超时重试）；3) 阶段编排：输入关键词→搜索→DeepSeek 分析→中文 Markdown 报告；4) 提供 .env.example，key 不写入代码。请实际创建项目文件、实现与基础测试（离线测试 + 联网冒烟分离）。工作目录：C:\Users\lenovo\Doubao\chats\2026-09-16\new-chat\marketpulse-agent。完成后总结模块与测试结果。"
```

**你在桌面版应输入的 Prompt**：



```
请先阅读并使用 agents-sdk skill 与 executing-plans skill 来规范流程。

按 docs/02-implementation-plan.md 的任务顺序开始实现 MarketPulse Agent 核心。注意以下关键工程约束：

1\. LLM 引擎：使用 DeepSeek 的 OpenAI 兼容 API（base\_url=https://api.deepseek.com，模型 deepseek-chat），API key 从环境变量 DEEPSEEK\_API\_KEY 读取；若用 openai-agents SDK，用 set\_default\_openai\_client 注入自定义 client 并关闭 tracing。

2\. 搜索能力：不得依赖 OpenAI 托管的 WebSearchTool；实现无需额外 API key 的联网搜索自定义工具（例如 DuckDuckGo 轻量实现，做好超时与重试）。

3\. 阶段编排：输入关键词 → 搜索市场/竞品/定价 → DeepSeek 分析 → 输出中文 Markdown 报告。

4\. 配置：提供 .env.example，实际读取环境变量；DeepSeek key 不写入代码。

请实际创建项目文件（Python 3.11+）、编写实现与基础测试（离线可重复测试 + 联网冒烟测试分离）。完成后总结实现了哪些模块、测试结果。
```

**阶段结果** ✅：完整 Python 包（agents /adapters/services /domain/tests /dist），DeepSeek 注入 + DuckDuckGo→Bing 搜索回退，mypy/pytest 通过。



***

### 阶段 4/6：frontend-design + shadcn（报告可视化前端）

**我的实际命令**：



```
& \$codex queue --thread "01a0acff-dd2b-7792-bbb9-0cbdac1e508b" --message "【任务阶段 4/6 - 报告可视化前端】请先阅读并使用 frontend-design skill 与 shadcn skill。目标：为 MarketPulse Agent 的报告输出做轻量可视化前端：1) 用 frontend-design 设计信息架构与视觉（核心结论 Go/Conditional Go/No-Go、市场概览、竞品对比、定价区间、证据来源）；2) 用 shadcn/ui 实现组件（浅色、产品经理风格）；3) 交互：输入关键词→调用已实现的 agent 工作流（uv run marketpulse 或 Python API）→展示结果，含加载状态。技术栈：Vite+React+TS+shadcn/ui，放 web/ 子目录。保持轻量。完成后总结页面结构、启动方式、对接方式。工作目录：C:\Users\lenovo\Doubao\chats\2026-09-16\new-chat\marketpulse-agent"
```

**你在桌面版应输入的 Prompt**：



```
请先阅读并使用 frontend-design skill 与 shadcn skill 来规范流程。

为 MarketPulse Agent 的报告输出做一个轻量可视化前端：

1\. 用 frontend-design 设计信息架构与视觉语言：报告核心结论（Go/Conditional Go/No-Go）、市场概览、竞品对比、定价区间、证据来源列表。

2\. 用 shadcn/ui 实现组件（浅色主题，专业产品经理风格）。

3\. 交互：输入关键词 → 调用已实现的 agent 工作流（调用 CLI 或复用其 Python API）→ 展示分析结果；运行较慢时需有加载状态。

技术栈：Vite + React + TypeScript + shadcn/ui，放在 web/ 子目录。保持轻量，不做账号体系。完成后总结页面结构、如何启动、与 agent 的对接方式。
```

**阶段结果** ✅：`web/` 完整前端（shadcn/ui 组件 + FastAPI `/api/reports` 适配层），1440px 桌面 + 390px 移动浏览器验收通过。



***

### 阶段 5/6：真实端到端运行（核心能力验证）

**我的实际命令**：



```
& \$codex queue --thread "01a0acff-dd2b-7792-bbb9-0cbdac1e508b" --message "【任务阶段 5/6 - 真实端到端运行验证】现在运行 MarketPulse Agent 做真实验证：1) 输入示例关键词 AI meeting notes software；2) 让 Agent 自主联网搜索（DuckDuckGo 优先、Bing 回退）、DeepSeek 分析，输出真实中文市场可行性报告，保存到 reports/example-report.md；3) 启动 FastAPI 与 Vite，确认网页能展示该报告（可截图）。【关键】DeepSeek key 已配置在系统用户级环境变量 DEEPSEEK\_API\_KEY（setx 持久化）。若当前进程读不到，请在运行命令前用 \[Environment]::GetEnvironmentVariable('DEEPSEEK\_API\_KEY','User') 注入（不要输出密钥值）。若 API 失败或搜索异常，按 systematic-debugging 流程排查根因。工作目录：C:\Users\lenovo\Doubao\chats\2026-09-16\new-chat\marketpulse-agent。完成后总结来源数、核心结论、DeepSeek 调用是否成功、前端是否可访问。"
```

**你在桌面版应输入的 Prompt**：



```
现在运行 MarketPulse Agent 做一次真实端到端验证：

1\. 输入示例关键词：AI meeting notes software

2\. 让 Agent 自主联网搜索、DeepSeek 分析，输出真实中文市场可行性报告，保存到 reports/example-report.md

3\. 启动 FastAPI 与 Vite 前端，确认网页能展示该报告（可截图确认）

关键：DeepSeek API key 已配置在系统用户级环境变量 DEEPSEEK\_API\_KEY（setx 持久化）。如果当前进程环境读不到该变量，请在运行命令前用 \[Environment]::GetEnvironmentVariable('DEEPSEEK\_API\_KEY','User') 将其注入到命令环境（不要输出密钥值）。若 DeepSeek 调用失败或搜索异常，请按 systematic-debugging skill 流程排查根因并修复。

完成后总结：搜索到多少来源、报告核心结论、DeepSeek 调用是否成功、前端是否可访问。
```

**过程亮点**（真实暴露并修复的问题，体现调试思路）：



1. CLI Typer 参数顺序 bug → 最小复现后修复

2. 公开搜索连续限流 → 记录状态、分级降级

3. **SSRF 防护误判代理 DNS**：透明代理把公网域名解析到 `198.18.0.0/15` 保留段，抓取器误判为私网全部拒绝 → 新增显式开关 `MARKETPULSE_ALLOW_PROXY_DNS=true`，仅放行该网段，[localhost/](https://localhost/)私网仍拒绝

4. Bing/Yahoo 跳转包装链接 → 解码还原真实目标 URL

5. 搜索结果主题失真 → 增加相关性过滤 + `ddgs` 无密钥元搜索最终降级

6. 搜索超时累积 → 单请求上限 5 秒，超时立即切换提供方

**阶段结果** ✅：35 个候选页面 → 20 个有效来源 → 120 条证据；DeepSeek 两次调用 HTTP 200；报告结论 **Conditional Go（置信度 35%）**——"市场需求明确但竞争拥挤，建议聚焦垂直工作流 / 企业治理 / 深度业务集成"；前端真实验收通过（截图 `reports/example-report-ui.png`）。



***

### 阶段 6/6：verification-before-completion（最终验收）

**我的实际命令**：



```
& \$codex queue --thread "01a0acff-dd2b-7792-bbb9-0cbdac1e508b" --message "【任务阶段 6/6 - 最终验收】请先阅读并使用 verification-before-completion skill。对整个项目做交付前最终验收：1) 全量验证：mypy、ruff、pytest（单元+集成+联网冒烟按配置）、uv build；2) 核对交付物清单（docs、src、tests、web、reports、README、.env.example）；3) 检查 README 启动说明完整性；4) 输出 docs/03-acceptance.md 验收报告（逐项结果、已修复问题、已知限制、后续建议）。发现失败项修复后重跑。工作目录：C:\Users\lenovo\Doubao\chats\2026-09-16\new-chat\marketpulse-agent。完成后总结验收结果。"
```

**你在桌面版应输入的 Prompt**：



```
请先阅读并使用 verification-before-completion skill 来规范流程。

对整个 MarketPulse Agent 项目做交付前最终验收：

1\. 全量验证：mypy typecheck、ruff lint、pytest（单元+集成+联网冒烟按配置）、uv build（wheel）

2\. 核对交付物清单：docs、src/marketpulse、tests、web、reports、README.md、.env.example

3\. 检查 README 启动说明是否完整（DeepSeek key 配置、安装、CLI 用法、前端启动）

4\. 输出 docs/03-acceptance.md 验收报告：逐项验证结果、已修复问题、已知限制与后续建议

发现任何失败项请修复后重跑验证。完成后总结验收结果。
```

**阶段结果** ✅：`docs/03-acceptance.md`——**32 passed in 190.88s**（含真实搜索与 DeepSeek live 用例）、mypy/Ruff/ 构建全部通过、前端测试 + 生产构建通过；7 个已修复问题、7 个已知限制、5 条后续建议；最终判定**通过（存在已记录的非阻断限制）**。



***

## 四、最终交付物清单



```
marketpulse-agent/

├── docs/

│   ├── 01-brainstorming.md          # 需求澄清与 MVP 收敛

│   ├── 02-implementation-plan.md    # 技术方案拆解（10 个 TDD 任务）

│   └── 03-acceptance.md             # 最终验收报告（32 测试通过）

├── src/marketpulse/                 # Agent 核心包

│   ├── agents/                      # DeepSeek 客户端注入 + 提示词

│   ├── adapters/                    # 搜索（DDG→Bing→Yahoo→ddgs）+ 抓取 + robots

│   ├── services/                    # 采集/提取/分析/质量门禁/报告

│   ├── domain/                      # 数据模型（Pydantic）

│   ├── templates/report.md.j2       # 10 章节报告模板

│   ├── workflow.py / cli.py / web\_api.py

├── tests/                           # unit + integration + live（32 用例）

├── web/                             # Vite + React + shadcn/ui 前端

├── reports/

│   ├── example-report.md            # 真实生成的市场可行性报告（20 来源/120 证据）

│   └── example-report-ui.png        # 前端真实展示截图

├── dist/                            # wheel + sdist

├── README.md / .env.example / pyproject.toml / uv.lock
```

## 五、如何运行 Agent



```
\# 1. 安装依赖（项目目录）

uv sync --extra dev

\# 2. 配置 key（已配置则跳过）

setx DEEPSEEK\_API\_KEY "sk-你的key"

\# 3. CLI 跑一次真实研究（生成 reports/\<topic>-<时间戳>.md）

uv run marketpulse --competitors 5 "AI meeting notes software"

\# 4. 前端可视化（两个终端）

uv run marketpulse-api          # 终端1：FastAPI @ http://127.0.0.1:8000

cd web; npm install; npm run dev # 终端2：Vite @ http://localhost:5173

\# 5. 测试

uv run pytest -m "not live" -q          # 离线

\$env:RUN\_LIVE\_TESTS = "1"; uv run pytest tests/live -m live -v -s   # 联网冒烟（耗 DeepSeek 少量费用）
```

> 注：若你的网络环境使用透明代理把公网 DNS 映射到 
>
> `198.18.0.0/15`
>
> （如本机），需要 
>
> `$env:MARKETPULSE_ALLOW_PROXY_DNS = "true"`
>
> ；普通环境保持默认关闭。

## 六、方法论沉淀（面试 / 复盘可用）



1. **多阶段编排**：brainstorming → writing-plans → executing-plans → verification 形成完整工程闭环，每个 skill 只负责一个环节。

2. **命令驱动而非手把手**：通过 `codex queue` 精确投递阶段任务，Codex 自主读取 skill、执行、汇报；发现歧义用队列消息回复决策。

3. **真实场景暴露真实问题**：限流、SSRF 误判、代理 DNS、链接包装、相关性失真 —— 每个都是系统设计里值得写进复盘的真实案例。

4. **验收不造假**：Codex 在阶段 5 主动拒绝把 "成功写文件但研究失真" 的结果当作验收通过，坚持修复根因后重跑 —— 这正是考核要的工程态度。