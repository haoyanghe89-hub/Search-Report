# Investigation Platform — 架构合同与实施状态

本文件记录 2026-09-21 前已确认的设计。目标仓库为 `haoyanghe89-hub/Search-Report`，在现有 MarketPulse 工程中逐步演进。**设计合同不代表能力已经实现**。

当前：保留 MarketPulse regression baseline；Phase 0 建立验证记录和 Git 基线，Phase 1a 交付通用 Blob Storage，Phase 2A–2D 交付 Investigation typed domain、24 张 `inv_` 表、Alembic 首版 migration、typed locator 与 SourceSnapshot 持久化。Phase 3 已交付通用 Search/Fetch/Model Port、call-level Recording/Replay adapter、HTML/TXT/文本层 PDF 解析、Source Acquisition 纵向切片及真实 PostgreSQL CI。Phase 4.1 增加独立 Harness 的持久化 Step/checkpoint、Unit of Work、精确调用绑定、RunBudget 与五角色类型契约；假 Agent 主链止于 READY_FOR_REPORT。Phase 4.2 增加完全独立于 Agent/Harness 的 Evidence / Claim / Validation Core、八类 typed profile、固定验证流水线、来源 lineage/独立性/质量评估、冲突与强反证门禁、结构化缺口以及 append-only 验证持久化。真实 Agent 调查、完整 Replay Harness、报告/发布、审核认证、自动恢复与新前端仍需后续阶段实现。详见 [迁移边界](docs/07-investigation-migration.md)、[Phase 2 验收](docs/10-phase2-data-foundation-acceptance.md)、[Phase 3 验收](docs/11-phase3-acquisition-recording-acceptance.md)、[Phase 4.1 验收](docs/12-phase4-1-harness-runtime-acceptance.md) 及 [Phase 4.2 验收](docs/13-phase4-2-validation-core-acceptance.md)。

## 1. 产品与依赖方向

V1 = **local trusted single-operator deployment**。本机操作者创建公开事件调查，查看过程、来源、证据、主张和中文报告。普通调查接口依赖本机信任边界；报告签发必须经服务端 Reviewer 认证。V1 不支持 LAN/public multi-user exposure，不建设注册、租户、SSO、LDAP 或复杂 RBAC。

依赖方向：`legacy MarketPulse -> generic infrastructure <- Investigation Platform`。通用基础设施不得导入 market-specific domain；新调查领域不得通过兼容层依赖旧市场模型。暂保留 `marketpulse` Python 包名是迁移期的打包选择，不代表保留市场业务。最终可整体重命名，禁止复制出第二套工程。

最终角色为 Supervisor/Planner、Researcher、Analyst、Verifier、Writer。Agent 负责计划、查询建议、语义提取、候选主张、语义冲突和缺口识别；Harness 负责状态机、工具执行、上下文、schema 校验、retry/timeout/budget、checkpoint、幂等、trace、终止和发布门禁。

## 2. 领域与验证

领域至少包含 Investigation、ResearchTask、Source、SourceSnapshot、Evidence、Claim、ClaimEvidenceRelation、ConflictSet、ValidationResult、ResearchGap、TimelineEvent、Report、ReportSection。Source 是逻辑身份，Snapshot 是不可变来源版本；Evidence 必须定位 Snapshot 中的具体原文，Claim 是独立命题，支持/反对关系通过 ClaimEvidenceRelation 表达。淘汰混合型 EvidenceClaim。

链路：`ReportSection -> Claim -> Evidence -> SourceSnapshot -> DocumentArtifact/locator -> 原文`。不要仅验证引用 ID 存在；必须验证定位内容与 Claim 的蕴含关系。

采用 typed Python ValidationProfile/Policy，不做 DSL 或通用规则引擎：

| ClaimType | 证明责任 |
| --- | --- |
| STATEMENT | 一份权威原始资料、精确 locator、蕴含校验可证明“机构说过 X”；不自动证明 X 是世界事实 |
| INSTITUTIONAL_ACTION | 直接机构记录及行为、主体、日期一致性 |
| EVENT_FACT | 强一手证据、通常独立旁证、无未解决强反证；权威例外须显式建模 |
| QUANTITATIVE | 数字、单位、口径、时间、范围及 provenance 对齐；重要数字通常需独立旁证；冲突不平均 |
| CAUSAL | 时间先后、机制、因果支持、独立旁证、替代解释与反证检查；更高门槛 |
| IMPACT | 区分观察到的影响与因果影响；症状报告不能自动证明事故致病 |
| ATTRIBUTION | 区分行为、调查归因、法律责任、分析推断；利益相关方声明不足以证明责任 |
| ANALYTIC_INFERENCE | 保持推断语义，不能静默升级为已验证事实 |

顺序：Evidence 存在 -> Snapshot 存在 -> locator 有效 -> entailment -> lineage -> 强反证 -> 独立性 -> 来源质量 -> 分类型充分性 -> status -> confidence -> 两者各自的 basis。强反证优先于数量，禁止多数投票。独立性按 origin/syndication cluster，转载同一发布只算一个证据族。

对外 Claim 状态为 VERIFIED、PROBABLE、DISPUTED、UNVERIFIED。内部 PENDING/REQUIRES_RESEARCH/REJECTED 必须映射到这四类。Status 与判断置信度分离；`DISPUTED + confidence=0.95` 合法，confidence 阈值不能决定 VERIFIED。LLM 可给语义判断，Policy 重新计算最终状态。

VERIFY 返工：evidence_gap/source_conflict -> COLLECT；analysis_error -> ANALYZE；passed -> REPORT。有轮次、时间、工具调用和模型预算，未解决问题显式留存。

## 3. 报告与发布治理

`Validated Claims -> Writer -> Draft -> ReportValidator -> ReportReleasePolicy`。Writer 不决定状态、风险放行或发布。VERIFIED 进入事实；PROBABLE 进入明确保留措辞的判断；DISPUTED 展示各方证据、差异解释及未解决状态；UNVERIFIED 进入待验证问题/局限，不写作肯定事实。

Report.review_status = NOT_REQUIRED/PENDING/APPROVED/REJECTED/CHANGES_REQUESTED；Report.release_status = DRAFT/RESTRICTED/REVIEW_REQUIRED/PUBLISHED。报告可生成且不可发布。PUBLISHED 可以包含正确分区的普通争议/未知信息，不要求全部 Claim VERIFIED。Plan 标记 critical_question_ids 和 critical_claim_requirements；关键覆盖缺失阻断发布。

Hard Gate 不可人工覆盖：缺 Evidence/Snapshot、无效引用/locator、entailment 失败、无支持事实、伪造来源、integrity/schema 失败、阻断安全失败。失败为 RESTRICTED。Review Gate 处理已通过硬门禁但仍有高风险归责、因果、长期健康/环境影响、高严重度争议及非阻断 provenance/security warning 的情况。

ReleasePolicy 检查 unsupported_claim_count、invalid_citation_count、关键问题/主张覆盖、阻断冲突、一手/独立来源覆盖、必需章节、缺口严重性、安全/provenance alerts。完整报告满足题目 15 章节；受限报告显示阻断缺口、未解决主张/冲突与下一步。usable_source_count = 0、verified_claim_count = 0 或调查受阻时生成简短 Investigation Status Report，含目标、搜索范围/调用、获取结果、阻断原因、证据缺口及下一步，不能假造完整长报告。

Human Review 只决定当前状态和风险标识下是否允许发布，不改变 Claim.validation_status。动作 APPROVE、REJECT、REQUEST_MORE_RESEARCH 均要求 reason；后者形成 HumanResearchRequest -> Supervisor -> ResearchTask -> 采集/分析/验证 -> 新版报告 -> 再审。

ReviewDecision 绑定 report_version、report semantic fingerprint、claim_set_hash、release_policy_version，并记录 review/report/investigation/run IDs、认证 reviewer_id、时间及理由。物质性 Claim/Evidence relation/Citation/Conflict/报告变化使旧 approval 失效。AuditEvent append-only，保留 actor、前后状态、目标 IDs、理由与时间。

## 4. Reviewer 与部署

ReviewerAuthenticator 抽象由 ConfiguredReviewerAuthenticator 实现。服务端配置 REVIEWER_ID、REVIEWER_DISPLAY_NAME、REVIEWER_PASSWORD_HASH、REVIEW_SESSION_SECRET、REVIEW_SESSION_TTL_MINUTES；密码只存强 hash，示例配置不放真 secret。

登录换取短期 HttpOnly session cookie，SameSite Strict/Lax，HTTPS 时 Secure，local demo 可显式关闭 Secure；过期、logout 撤销、登录限流、通用错误、Origin 校验、敏感信息不进日志。前端不把 token 放 localStorage。`/api/review/auth/login|logout|me` 与审批接口分离。客户端不得可信地指定 reviewer_id，身份由认证 context 注入。

审批必须在一致性事务内验证：认证、报告存在、当前版本/报告指纹/claim_set_hash、动作适用状态、全部 Hard Gates、当前 ReleasePolicy，然后追加 ReviewDecision/AuditEvent 并更新发布状态。旧版本审批返回 REVIEW_VERSION_CONFLICT。后端 authorization 不能由隐藏按钮替代。Review reason 按普通用户输入处理，不成为 system 指令。

DEPLOYMENT_MODE=local；宿主机应用端口默认绑定 127.0.0.1，容器内 0.0.0.0 合法；单 API process/单 uvicorn worker。CORS 明确前端 origin，禁止 wildcard credentials。普通 API 可本机使用，审核 mutation 必须认证。前端通过应用 API/Storage Port 访问证据摘录，禁止返回 OS 路径或挂载目录。默认不公开 raw prompt、auth 数据或未过滤录制调用。

Outbound 仅经受控 Search/Fetch：SSRF/private IP、逐跳重定向、MIME、大小、timeout/retry 防护继续有效。未来网络化须给 Investigation/Run/Source/Snapshot/Evidence/Claim/Report/trace/audit 加应用级访问控制；不能只放开监听端口。

## 5. Blob 与解析

Phase 3 的已实现组合边界：`SearchPort` / `FetchPort` / `ModelPort` 是 typed async contract；Live provider 由 `Recording*Adapter` 包裹，Replay 用 `Replay*Adapter` 替换 provider 而不更改调用方。`RepositoryRecordedCallStore` 把规范化请求及完整响应放入内容寻址 Blob，并持久化每次调用的 fingerprint、版本、时间、provider 元信息、状态和逻辑 BlobRef。失败记录不被当作可重放的结果；相同 fingerprint 的重复成功调用按顺序消费。暂时的旧搜索桥接位于 Investigation 包之外，不让新领域导入 market-specific 合同。

`HttpxFetchAdapter` 对初始 URL 及每次重定向目标执行 HTTP(S)/公网主机校验，限制 MIME、总字节、超时、跳转次数和暂时性故障重试。`DocumentParserRegistry` 依据签名优先、声明 MIME 辅助的规则选择解析器；HTML/TXT 保存稳定归一化文本，PDF 保存每个可靠页面的独立 artifact。扫描 PDF 不产出可取证页面，部分 PDF 只产出可靠页面；raw Snapshot 始终保留。基本可疑指令检测和 `UNTRUSTED` provenance 在解析边界执行，官方来源亦不例外。

`SourceAcquisitionService` 只负责搜索结果去重、Source 注册、Fetch、Snapshot/Artifact/Gap 持久化和分层来源统计；不负责 Claim 或 Report。`valid_for_statistics` 至少要求 Snapshot、可用解析内容、可取证 artifact 和 provenance。Phase 3 的 Replay 测试从新 Run 重走这个采集服务，重新注册 Source/Snapshot/Artifact 并解析录制的 Fetch body；它尚不声称完成后续状态机、Policy 或报告重放。

PostgreSQL 保存结构化领域状态、调用元数据和 BlobRef/hash/MIME/size/encoding/版本/provenance。不可变 raw HTML/PDF/JSON、清洗正文、逐页文本、录制 request/response 存在本地内容寻址 Blob Store；逻辑引用 `blob://sha256/<hash>`，实际路径只归 adapter 所有。相同内容复用，不同内容新 hash。

BlobStoragePort 提供 put_bytes/put_stream/get_bytes/open_stream/exists/verify_hash；首版 LocalContentAddressedBlobStorage，未来可替换 S3/MinIO。业务层不直接 open 文件。先写临时文件、flush/fsync、校验 hash/size、完整原子发布，再提交 DB reference；DB 回滚最多留下 orphan，不能引用 partial/missing blob。首版允许 orphan，不实现 GC 或跨 DB/filesystem 分布式事务。

Phase 1 adapter 使用同卷临时文件和 atomic no-clobber hard-link 发布，避免并发覆盖已有 hash；这是原子发布的具体实现，不会改写已有 Blob。需要支持硬链接的本地文件系统（Windows NTFS/Linux 本地 Docker volume）。不支持时显式 BLOB_IO_ERROR，不降级为直接写最终路径。Python API 依据：[os.link](https://docs.python.org/3/library/os.html#os.link)、[os.fsync](https://docs.python.org/3/library/os.html#os.fsync)。POSIX 同步新增目录项；Windows 无便携目录 fsync，本阶段测试进程异常安全，不声称断电/损坏磁盘持久性。

SourceSnapshot 保存 source_id、retrieved/published_at、raw/cleaned refs 与 SHA、MIME/encoding/HTTP status、parser/normalizer version、provenance。Evidence 始终引用具体 Snapshot。读取验证 hash，不一致为 BLOB_INTEGRITY_ERROR；不存在为 BLOB_NOT_FOUND。Snapshot 或 recorded call 只有 hash 没有 payload 不可重放。

DocumentParserPort + registry 依据实际 MIME 和 magic 选择 HtmlDocumentParser、PlainTextParser、PdfTextLayerParser，后缀仅作 hint。HTML/TXT 定位为 normalized char range + exact quote/hash；PDF 持久化每页文本并用 page/start/end 定位。所有 offsets 以持久化的、版本固定的文本为准。

parse_status 明确包含 DISCOVERED/FETCHED/PARSED/PARTIALLY_PARSED/UNSUPPORTED_MEDIA_TYPE/UNSUPPORTED_SCANNED_PDF/INSUFFICIENT_TEXT_LAYER/EMPTY_CONTENT/CORRUPT_DOCUMENT/ENCRYPTED_PDF/FETCH_FAILED/PARSE_FAILED。没有可用文本层的 PDF 保留 raw，evidence_eligible=false，不产生 Evidence/支持 Claim/计入 valid source。创建 UNREADABLE_SOURCE gap，建议 HTML/text/替代官方副本/旁证搜索。PDF 成功须检查字符数、有效页与密度，部分成功仅可靠页面可取证。TABLE_STRUCTURE_LOST 区域不能静默支持精确 QUANTITATIVE 结论。解析后仍为 UNTRUSTED DATA。

V1 无 OCR。未来 OCR/multimodal parser 必须同时设计 confidence、页/区域 provenance、原图回显及验证规则。

## 6. Replay 合同

Replay = **recorded nondeterministic inputs + fresh deterministic execution**；execution replay, not reasoning regeneration。共享 SearchPort/FetchPort/ModelPort/ReviewPort，由 composition root 注入 live/replay adapters；Agent/Harness 没有 `if replay_mode`。

允许录制搜索/抓取/tool response、Snapshot、LLM structured response、必要 embedding/rerank 和 HumanReviewDecision。逐调用记录 call_id、operation、normalized input、request fingerprint、schema version、provider/model/tool metadata、response hash、recorded_at、request_blob_ref、response_blob_ref。Fingerprint 包含 operation、结构化语义输入、prompt/template version、schema version、相关配置，不能只缓存整阶段。

新 Replay run/trace/agent_run/tool execution IDs，从空 Run、空业务状态开始。稳定业务 IDs 可确定性生成。重新执行 dispatch/state transitions、schema 校验、reducers、DB、Source/Snapshot registration、Evidence/Claim/relations、lineage/independence、conflict、locator、ValidationPolicy、status/confidence、gap routing、报告组装、release 和 trace。禁止恢复 Live 最终 Blackboard 或读取 expected 最终报告。

缺失调用为 REPLAY_CACHE_MISS（stage/agent/operation/fingerprint），损坏 Blob 为 BLOB_INTEGRITY_ERROR，均 fail closed，不访问真实网络/模型。模型语义判断可以录制，Policy 决策必须重算。

Review 录制重放先重新计算 ReleasePolicy，在 REVIEW_REQUIRED 时匹配报告/Claim/policy 指纹并重新 ApplyReviewDecision；不匹配为 REPLAY_REVIEW_MISMATCH 或继续待审。无需真人重登，但审计为 SYSTEM / RECORDED_HUMAN_REVIEW_APPLIED，带原 review_id/reviewer_id/decision timestamp/provenance，不能伪造新的人类操作。

便携 case_data/east_palestine_2023/ 包含 manifest、blobs、snapshots、recordings、expected。Export 遍历 Live 引用收集必需 payload；manifest 固定 case/live-run/workflow/schema/prompt versions、数量及 hashes。输入目录和 expected 评测目录隔离；expected 只用于结束后的 assertion。Fixture 必须能在新目录、空库、无 key、禁网环境执行。

## 7. 执行、恢复和通知

RunExecutorPort/RunExecutionManager -> InProcessRunExecutor。API 先创建 Investigation/Run 并 COMMIT，再 submit run_id，返回 202；commit 后 dispatch 失败仍保留可恢复的 CREATED/PENDING，由用户显式 Start/Continue。后台 task 只保留 active handle，不承载业务真相。

MAX_CONCURRENT_RUNS 默认 1（可配置 2 等受限值），等待者持久化 WAITING_FOR_EXECUTION，不能虚报 RUNNING。DB compare-and-set/版本检查保护 ownership；重复 Continue 只能一个成功。关闭浏览器不取消 Run；GET investigation/run/events 从 DB 恢复，SSE 在 DB commit 后通知，断线用持久化游标或 REST/poll 重同步。

ExecutionStep 记录 step/run IDs、type、agent、status、attempt、input_fingerprint、output_refs、timestamps、error_code、retryable、executor_instance_id、heartbeat_at。Step 为 PENDING/RUNNING/COMPLETED/FAILED/INTERRUPTED/CANCELLED。Run 为 CREATED/WAITING_FOR_EXECUTION/RUNNING/PAUSED/INTERRUPTED/BLOCKED/COMPLETED/FAILED/CANCELLED。

输出持久化 + Step COMPLETED + checkpoint commit 才算 durable。Checkpoint 记录当前/最后完成 step、phase、checkpoint/state versions、updated_at、interruption_reason；恢复依据 Step/Artifact graph，而非 phase 字符串。逐 Claim VERIFY 可复用已完成项，只重跑中断项。

启动 RecoveryScanner 按 owner/heartbeat/stale policy 标记安全确认的陈旧任务及审计；不自动执行。Continue 恢复中断任务，Retry 针对 retryable FAILED，Start New Run 新建 ID 且保留旧 Run。恢复前校验版本、完整 BlobRefs、无 active owner 和 workflow/checkpoint 兼容性；不兼容 RESUME_VERSION_MISMATCH。

业务步骤用稳定身份、unique constraints、幂等键；已 durable recorded 的外部调用可复用。READ_ONLY/IDEMPOTENT_WRITE/NON_IDEMPOTENT_WRITE 分类明确；未知副作用结果进入 BLOCKED/reconciliation，不能盲重试。cancel 先持久化 request，Harness 在安全边界协作退出，保留产物。shutdown 停收新工作、短宽限到检查点、再中断剩余任务；重启仍不自动续跑。

未来多 API 进程/副本、自动恢复、跨机器执行、优先级和高并发才切 QueueRunExecutor/worker lease/scheduler；不改变领域、Step/Checkpoint、Harness 或 API 语义。

## 8. 验收与尚待细化的局部设计

East Palestine 2023 必须最终 PUBLISHED：至少 10 valid sources、3 primary/official、3 independent secondary、3 source types、1 real conflict/discrepancy、15 章节及完整证据/引用链。至少一个真实官方/高质量文本层 PDF，E2E 能从报告定位确切页/摘录。高风险审核必须走真实认证签发；Hard Gate 不能覆盖。

验收包含 Live、禁网空库 Replay、删必要录制输入的 cache-miss 负测、损坏 Blob 负测、重算验证状态、重放审批指纹不匹配、进程中途退出/重启/手动 Continue/无重复数据、权限/会话过期/logout/旧版审批冲突测试。来源统计排除不可解析资料。

后续设计需细化 typed profiles 的精确参数、数值/时间对齐、lineage 特征、semantic fingerprint 的稳定化和 CPU/时间/预算参数；这些不阻塞 Phase 0/1。语义相关 Policy 修改可能改变执行路径，Replay 应显式 cache miss/mismatch，不放宽匹配迁就旧 fixture。源码演进的完整数据库迁移与 Executor 实现分别作为独立交付单元。
