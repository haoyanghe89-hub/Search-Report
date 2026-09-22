const state = {
  investigations: [],
  investigation: null,
  run: null,
  report: null,
  citations: [],
  activeTab: "overview",
  liveResult: null,
};

const liveRunCache = {};

const PHASE_LABELS = {
  plan: "规划研究问题",
  search: "搜索公开来源",
  fetch: "抓取网页正文",
  extract: "提取证据",
  analyze: "分析证据",
  review: "复盘与补查决策",
  quality: "质量评估",
  report: "撰写报告",
  write: "保存报告",
  completed: "已完成",
};
const AGENT_LABELS = { master: "规划者", search: "研究员", analysis: "分析师", report: "报告员", harness: "调度器" };

const $ = (selector) => document.querySelector(selector);
const panel = $("#panel");

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function words(value) {
  return escapeHtml(String(value ?? "").replaceAll("_", " ").toLowerCase());
}

function formatDate(value) {
  if (!value) return "未记录";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function statusChip(value) {
  const text = String(value ?? "UNKNOWN");
  const css = text.toLowerCase().replaceAll("_", "-");
  return `<span class="status-chip ${css}">${words(text)}</span>`;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("is-visible");
  window.setTimeout(() => toast.classList.remove("is-visible"), 2800);
}

function showLoading(text = "正在调查…") {
  $("#loading-text").textContent = text;
  $("#loading-overlay").classList.add("is-visible");
  $("#loading-overlay").setAttribute("aria-hidden", "false");
}

function hideLoading() {
  $("#loading-overlay").classList.remove("is-visible");
  $("#loading-overlay").setAttribute("aria-hidden", "true");
}

async function fetchJson(path, options = {}) {
  const response = await fetch(path, { credentials: "include", ...options });
  if (!response.ok) {
    let payload = {};
    try { payload = await response.json(); } catch { /* non-JSON error */ }
    const detail = payload.detail;
    const message = typeof detail === "object" ? detail.message : detail;
    throw new Error(message || `${response.status} ${response.statusText}`);
  }
  return response.status === 204 ? null : response.json();
}

async function boot() {
  try {
    await fetchJson("/api/health");
    $("#system-state").classList.add("is-online");
    $("#system-state").lastChild.textContent = " 已连接";
    await loadInvestigations();
    const cases = await fetchJson("/api/cases");
    const replay = $("#run-replay");
    replay.disabled = !cases[0]?.replay_ready;
    if (!cases[0]?.replay_ready) replay.title = "回放数据未配置";
  } catch (error) {
    $("#system-state").lastChild.textContent = " 后端不可用";
    panel.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
  }
}

async function loadInvestigations() {
  state.investigations = await fetchJson("/api/investigations");
  $("#investigation-list").innerHTML = state.investigations.map((item) => `
    <button class="investigation-link ${state.investigation?.investigation_id === item.investigation_id ? "is-active" : ""}"
      data-investigation-id="${escapeHtml(item.investigation_id)}">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${item.run_count} 次运行</span>
    </button>`).join("");
}

async function openInvestigation(investigationId, preferredRunId = null) {
  try {
    const [investigation, runs] = await Promise.all([
      fetchJson(`/api/investigations/${encodeURIComponent(investigationId)}`),
      fetchJson(`/api/investigations/${encodeURIComponent(investigationId)}/runs`),
    ]);
    state.investigation = investigation;
    state.liveResult = null;
    state.report = null;
    state.citations = [];
    const cachedLive = liveRunCache[investigationId] || null;
    const selected = preferredRunId
      ? runs.find((run) => run.run_id === preferredRunId)
      : (cachedLive ? null : runs[0]);
    state.run = selected ? (await fetchJson(`/api/runs/${encodeURIComponent(selected.run_id)}`)).run : null;
    if (!state.run) {
      let restored = cachedLive;
      if (!restored) {
        try {
          const liveRuns = await fetchJson(
            `/api/investigations/${encodeURIComponent(investigationId)}/live-runs`
          );
          const completed = liveRuns.find((r) => r.status === "completed");
          if (completed) {
            restored = await fetchJson(`/api/live-runs/${encodeURIComponent(completed.run_id)}`);
            liveRunCache[investigationId] = restored;
          }
        } catch { /* no live runs */ }
      }
      if (restored) _applyLiveState(restored);
    }
    $("#case-hero").classList.add("is-hidden");
    $("#empty-guidance").classList.add("is-hidden");
    $("#active-investigation").classList.remove("is-hidden");
    $("#investigation-title").textContent = investigation.title;
    $("#investigation-goal").textContent = investigation.investigation_goal;
    $("#investigation-breadcrumb").textContent = state.run
      ? `回放运行 · ${state.run.run_id}`
      : (state.liveResult ? `真实调研 · ${state.liveResult.run_id}` : "调查草稿");
    $("#run-badge").innerHTML = state.run
      ? statusChip(state.run.status)
      : (state.liveResult ? statusChip("COMPLETED") : statusChip("NO_RUN"));
    await renderTab(state.activeTab);
  } finally {
    await loadInvestigations();
  }
}

function panelHeading(title, detail) {
  return `<div class="panel-heading"><h2>${escapeHtml(title)}</h2><p>${escapeHtml(detail)}</p></div>`;
}

async function renderOverview() {
  const item = state.investigation;
  if (state.liveResult) {
    const r = state.liveResult;
    const a = r.analysis || {};
    const q = r.quality;
    panel.innerHTML = `${panelHeading("调查概览", `真实调研 · ${escapeHtml(r.topic)}`)}
      <div class="metric-strip">
        ${[[r.evidence?.sources?.length || 0, "来源"], [r.evidence?.claims?.length || 0, "证据"], [r.executed_queries?.length || 0, "搜索查询"], [r.research_round || 0, "研究轮次"], [r.warnings?.length || 0, "警告"]].map(([value, label]) => `<div class="metric"><strong>${value}</strong><span>${label}</span></div>`).join("")}
      </div>
      ${q ? `<div class="record"><div class="record-top"><h3>质量评估</h3>${statusChip(q.passed ? "PASSED" : "FAILED")}</div>${(q.issues || []).length ? `<ul>${q.issues.map((i) => `<li>${escapeHtml(i.code)}：${escapeHtml(i.message)}</li>`).join("")}</ul>` : "<p>未发现问题。</p>"}</div>` : ""}
      <div class="record"><h3>执行摘要</h3><p>${escapeHtml(a.executive_summary || "无")}</p></div>
      <div class="record"><h3>结论建议</h3><div class="record-meta"><span>${escapeHtml(a.recommendation || "—")}</span><span>置信度 ${(a.confidence ?? 0).toFixed(2)}</span></div></div>
      <div class="record"><h3>下一步</h3><ul>${(a.next_steps || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("") || "<li>无</li>"}</ul></div>`;
    return;
  }
  if (!state.run) {
    panel.innerHTML = `${panelHeading("调查概览", "尚未开始调查")}
      <div class="record">
        <p>该调查尚无运行记录。点击下方按钮启动真实大模型调查：</p>
        <button class="primary-button" id="start-run">开始调查</button>
        <p class="record-meta" style="margin-top:12px;">将调用搜索、抓取与大模型 API（需配置 DEEPSEEK_API_KEY），结果整理到来源/证据/声明视图。</p>
      </div>
      ${(item.questions || []).length ? `<ul class="question-list">${item.questions.map((question) => `<li class="record"><div class="record-top"><h3>${escapeHtml(question.text)}</h3>${question.is_critical ? statusChip("CRITICAL") : ""}</div></li>`).join("")}</ul>` : ""}`;
    $("#start-run")?.addEventListener("click", startRun);
    return;
  }
  const counts = item.counts;
  const budget = state.run ? (await fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}`)).budget : null;
  panel.innerHTML = `${panelHeading("调查概览", "持久化状态")}
    <div class="metric-strip">
      ${[[counts.sources, "来源"], [counts.evidence, "证据"], [counts.claims, "声明"], [counts.conflicts, "冲突"], [counts.open_gaps, "待解缺口"]].map(([value, label]) => `<div class="metric"><strong>${value}</strong><span>${label}</span></div>`).join("")}
    </div>
    <ul class="question-list">${item.questions.map((question) => `<li class="record"><div class="record-top"><h3>${escapeHtml(question.text)}</h3>${question.is_critical ? statusChip("CRITICAL") : ""}</div></li>`).join("")}</ul>
    ${budget ? `<div class="record"><h3>回放预算</h3><div class="record-meta"><span>轮次 ${budget.research_rounds_used}/${budget.max_research_rounds}</span><span>搜索 ${budget.search_calls_used}/${budget.max_search_calls}</span><span>抓取 ${budget.fetch_calls_used}/${budget.max_fetch_calls}</span><span>模型 ${budget.model_calls_used}/${budget.max_model_calls}</span><span>来源 ${budget.sources_used}/${budget.max_sources}</span></div></div>` : ""}`;
}

async function renderProcess() {
  if (state.liveResult) {
    const events = await fetchJson(`/api/blackboard-runs/${encodeURIComponent(state.liveResult.run_id)}/events`);
    panel.innerHTML = `${panelHeading("智能体流程", `${events.length} 个黑板事件`)}
      <div class="trace"><div class="trace-stage"><strong>规划者</strong><span>PLAN</span></div><div class="trace-stage"><strong>研究员</strong><span>SEARCH</span></div><div class="trace-stage"><strong>分析师</strong><span>ANALYZE</span></div><div class="trace-stage"><strong>报告员</strong><span>REPORT</span></div></div>
      ${(state.liveResult.research_round || 0) > 1 ? `<div class="feedback-loop">复盘决策触发了第 ${state.liveResult.research_round} 轮补充研究。</div>` : ""}
      <ul class="record-list">${events.map((ev) => `<li class="record"><div class="record-top"><h3>${escapeHtml(AGENT_LABELS[ev.actor] || ev.actor)} · ${escapeHtml(ev.event)}</h3></div><div class="record-meta"><span>${escapeHtml(PHASE_LABELS[ev.phase] || ev.phase)}</span><span>${formatDate(ev.created_at)}</span><span>版本 ${ev.version}</span></div></li>`).join("")}</ul>`;
    return;
  }
  if (!state.run) return renderNoRun();
  const steps = await fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/steps`);
  const looped = steps.some((step) => step.research_round && step.research_round > 1);
  panel.innerHTML = `${panelHeading("智能体流程", `${steps.length} 个持久化步骤`)}
    <div class="trace"><div class="trace-stage"><strong>规划者</strong><span>PLAN</span></div><div class="trace-stage"><strong>研究员</strong><span>COLLECT</span></div><div class="trace-stage"><strong>分析师</strong><span>ANALYZE</span></div><div class="trace-stage"><strong>验证者</strong><span>VERIFY</span></div></div>
    ${looped ? `<div class="feedback-loop">验证者反馈触发了有界的研究缺口 → 采集 → 分析 → 验证循环。</div>` : ""}
    <ul class="record-list">${steps.map((step) => `<li class="record"><div class="record-top"><h3>${escapeHtml(step.agent_role)} · ${escapeHtml(step.logical_step_key)}</h3>${statusChip(step.status)}</div><div class="record-meta"><span>${escapeHtml(step.phase)}</span><span>${escapeHtml(step.step_type)}</span><span>第 ${step.research_round ?? "—"} 轮</span><span>${step.active_elapsed_ms} 毫秒</span></div></li>`).join("")}</ul>`;
}

async function renderSources() {
  if (state.liveResult) {
    const rows = state.liveResult.evidence?.sources || [];
    panel.innerHTML = `${panelHeading("来源", `${rows.length} 个公开来源`)}<ul class="record-list">${rows.map((row) => `<li class="record"><div class="record-top"><h3>${escapeHtml(row.title)}</h3>${statusChip(row.source_type || "other")}</div><p>${escapeHtml(row.domain || "未知域名")}</p><div class="record-meta"><span>${escapeHtml(row.id)}</span><span>访问于 ${formatDate(row.accessed_at)}</span></div><p><a href="${escapeHtml(safeUrl(row.url))}" target="_blank" rel="noreferrer">打开原始来源</a></p></li>`).join("") || `<li class="record"><p>未采集到来源。</p></li>`}</ul>`;
    return;
  }
  if (!state.run) return renderNoRun();
  const rows = await fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/sources`);
  panel.innerHTML = `${panelHeading("来源", `${rows.length} 个持久化来源`)}<ul class="record-list">${rows.map((row) => `<li class="record"><div class="record-top"><h3>${escapeHtml(row.title)}</h3>${statusChip(row.parse_status || "DISCOVERED")}</div><p>${escapeHtml(row.publisher || row.organization || "未记录发布方")}</p><div class="record-meta"><span>${words(row.source_type)}</span><span>${row.is_official ? "官方" : "独立"}</span><span>${row.is_first_hand ? "一手" : "二手"}</span><span>快照 ${escapeHtml(row.snapshot_id || "待处理")}</span></div><p><a href="${escapeHtml(safeUrl(row.canonical_url))}" target="_blank" rel="noreferrer">打开原始来源</a></p></li>`).join("")}</ul>`;
}

async function renderEvidence() {
  if (state.liveResult) {
    const rows = state.liveResult.evidence?.claims || [];
    const sourcesById = new Map((state.liveResult.evidence?.sources || []).map((s) => [s.id, s]));
    panel.innerHTML = `${panelHeading("证据", `${rows.length} 条带来源引用的证据摘录`)}<ul class="record-list">${rows.map((row) => {
      const src = sourcesById.get(row.source_id);
      return `<li class="record"><div class="record-top"><h3>${escapeHtml(row.id)} · ${escapeHtml(row.subject)}</h3>${statusChip(row.claim_type)}</div><p>${escapeHtml(row.statement)}</p><blockquote class="evidence-quote">${escapeHtml(row.quote)}</blockquote><div class="record-meta"><span>来源 ${escapeHtml(row.source_id)}${src ? ` · ${escapeHtml(src.domain)}` : ""}</span></div>${src ? `<p><a href="${escapeHtml(safeUrl(src.url))}" target="_blank" rel="noreferrer">查看来源原文</a></p>` : ""}</li>`;
    }).join("") || `<li class="record"><p>未提取到证据。</p></li>`}</ul>`;
    return;
  }
  if (!state.run) return renderNoRun();
  const rows = await fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/evidence`);
  panel.innerHTML = `${panelHeading("证据", `${rows.length} 条定位器绑定摘录`)}<ul class="record-list">${rows.map((row) => `<li class="record"><h3>${escapeHtml(row.evidence_id)}</h3><blockquote class="evidence-quote">${escapeHtml(row.content)}</blockquote><div class="record-meta"><span>${words(row.locator_type)}</span><span>${escapeHtml(JSON.stringify(row.locator_payload))}</span><span>${row.relations.length} 个声明关联</span></div></li>`).join("")}</ul>`;
}

async function renderClaims() {
  if (state.liveResult) {
    const a = state.liveResult.analysis || {};
    const rows = [];
    if (a.executive_summary) rows.push({ statement: a.executive_summary, claim_type: "summary", confidence: a.confidence, source_ids: [] });
    (a.market_signals || []).forEach((s) => rows.push({ statement: s.statement, claim_type: "market_signal", confidence: a.confidence, source_ids: s.source_ids || [], interpretation: s.interpretation }));
    (a.rationale || []).forEach((r) => rows.push({ statement: r, claim_type: "rationale", confidence: a.confidence, source_ids: [] }));
    (a.opportunities || []).forEach((o) => rows.push({ statement: o, claim_type: "opportunity", confidence: a.confidence, source_ids: [] }));
    panel.innerHTML = `${panelHeading("声明", `${rows.length} 条分析声明`)}<ul class="record-list">${rows.map((row) => `<li class="record"><div class="record-top"><h3>${escapeHtml(row.statement)}</h3>${statusChip(row.claim_type)}</div>${row.interpretation ? `<p>${escapeHtml(row.interpretation)}</p>` : ""}<div class="record-meta"><span>置信度 ${row.confidence == null ? "—" : row.confidence.toFixed(2)}</span><span>${row.source_ids.length ? `引用 ${row.source_ids.map(escapeHtml).join("、")}` : "基于整体证据"}</span></div></li>`).join("") || `<li class="record"><p>暂无声明。</p></li>`}</ul>`;
    return;
  }
  if (!state.run) return renderNoRun();
  const rows = await fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/claims`);
  panel.innerHTML = `${panelHeading("声明", `${rows.length} 条原子声明`)}<ul class="record-list">${rows.map((row) => `<li class="record"><div class="record-top"><h3>${escapeHtml(row.statement)}</h3>${statusChip(row.validation_status)}</div><p>${escapeHtml(row.validation_basis || row.confidence_basis || "未记录验证依据")}</p><div class="record-meta"><span>${words(row.claim_type)}</span><span>${words(row.importance)}</span><span>置信度 ${row.confidence == null ? "—" : row.confidence.toFixed(2)}</span><span>${row.supporting_evidence_ids.length} 条支持证据</span></div></li>`).join("")}</ul>`;
}

async function renderConflicts() {
  if (state.liveResult) {
    const a = state.liveResult.analysis || {};
    const warnings = state.liveResult.warnings || [];
    panel.innerHTML = `${panelHeading("风险与局限", `${(a.risks || []).length} 项风险 · ${(a.limitations || []).length} 项局限 · ${warnings.length} 条警告`)}
      <ul class="record-list">${(a.risks || []).map((r) => `<li class="record"><div class="record-top"><h3>风险</h3></div><p>${escapeHtml(r)}</p></li>`).join("") || "<li class='record'><p>无风险记录。</p></li>"}</ul>
      <ul class="record-list">${(a.limitations || []).map((l) => `<li class="record"><div class="record-top"><h3>局限</h3></div><p>${escapeHtml(l)}</p></li>`).join("")}</ul>
      <ul class="record-list">${warnings.map((w) => `<li class="record"><div class="record-top"><h3>采集警告</h3></div><p>${escapeHtml(w)}</p></li>`).join("")}</ul>`;
    return;
  }
  if (!state.run) return renderNoRun();
  const [conflicts, gaps] = await Promise.all([
    fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/conflicts`),
    fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/gaps`),
  ]);
  panel.innerHTML = `${panelHeading("冲突与缺口", `${conflicts.length} 个冲突 · ${gaps.length} 个研究缺口`)}
    <ul class="record-list">${conflicts.map((row) => `<li class="record"><div class="record-top"><h3>${words(row.conflict_type)} 冲突</h3>${statusChip(row.resolution_status)}</div><p>${escapeHtml(row.resolution_summary || row.resolution_basis || "未解决")}</p><div class="record-meta"><span>${words(row.severity)}</span><span>${row.claim_ids.length} 个关联声明</span></div></li>`).join("") || `<li class="record"><p>未持久化冲突集。</p></li>`}</ul>
    <ul class="record-list">${gaps.map((row) => `<li class="record"><div class="record-top"><h3>${escapeHtml(row.reason)}</h3>${statusChip(row.status)}</div><p>${escapeHtml(row.suggested_action || (row.suggested_actions && row.suggested_actions.join(" · ")) || "未记录操作")}</p><div class="record-meta"><span>${words(row.gap_type)}</span><span>${words(row.severity)}</span></div></li>`).join("")}</ul>`;
}

async function loadLatestReport() {
  if (!state.run) return null;
  const reports = await fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/reports`);
  if (!reports.length) return null;
  const latest = reports[0];
  state.report = await fetchJson(`/api/reports/${encodeURIComponent(latest.report_id)}`);
  state.citations = await fetchJson(`/api/reports/${encodeURIComponent(latest.report_id)}/citations`);
  return state.report;
}

async function renderReport() {
  const report = state.report || await loadLatestReport();
  if (!report) {
    panel.innerHTML = `${panelHeading("报告", "暂无报告版本")}
      <div class="record"><p>该运行尚未生成报告。</p>${state.run?.status === "READY_FOR_REPORT" ? `<button class="primary-button" id="generate-report">生成完整报告</button>` : ""}</div>`;
    $("#generate-report")?.addEventListener("click", generateReport);
    return;
  }
  const citationsByUnit = new Map();
  for (const citation of state.citations) {
    const group = citationsByUnit.get(citation.unit_key) || [];
    group.push(citation);
    citationsByUnit.set(citation.unit_key, group);
  }
  panel.innerHTML = `${panelHeading("调查报告", `版本 ${report.report.version} · ${words(report.report.report_type)}`)}
    <div class="record-meta"><span>${statusChip(report.report.release_status)}</span><span>审核 ${words(report.report.review_status)}</span><span>哈希 ${escapeHtml(report.report.report_hash.slice(0, 16))}…</span></div>
    <div class="export-bar"><button class="secondary-button" id="export-pdf">导出 PDF</button></div>
    <article>${report.sections.map((section) => `<section class="report-section"><h3>${words(section.section_type)}</h3>${(section.content?.units || []).map((unit) => `<p class="report-unit">${escapeHtml(unit.text)} ${(citationsByUnit.get(unit.unit_key) || []).map((citation) => `<button class="citation-button" data-citation-id="${escapeHtml(citation.citation_id)}">[${citation.display_ordinal}]</button>`).join(" ")}</p>`).join("") || `<p class="report-unit">${words(section.content?.status || "无支持材料")}</p>`}</section>`).join("")}</article>`;
  $("#export-pdf")?.addEventListener("click", exportPdf);
}

async function renderReview() {
  if (state.liveResult) {
    panel.innerHTML = `${panelHeading("发布审核", "真实调研报告")}
      <div class="record"><p>真实调研结果直接在报告页查看与导出，无需发布审核流程（该流程面向内置回放案例的治理演示）。</p><button class="secondary-button" id="goto-report">前往报告页</button></div>`;
    $("#goto-report")?.addEventListener("click", () => renderTab("report"));
    return;
  }
  const report = state.report || await loadLatestReport();
  if (!report) return renderReport();
  const review = await fetchJson(`/api/reports/${encodeURIComponent(report.report.report_id)}/review`);
  let reviewer = null;
  try { reviewer = await fetchJson("/api/review/me"); } catch { /* not signed in */ }
  panel.innerHTML = `${panelHeading("发布审核", "仅治理操作 — 声明状态在此不可变")}
    <div class="review-layout"><div>
      <div class="record"><div class="record-top"><h3>发布评估</h3>${statusChip(review.release_status)}</div><p>${escapeHtml(review.pending_request?.trigger_reason || "无待处理人工审核请求")}</p><div class="record-meta"><span>${review.evaluation ? `${review.evaluation.hard_finding_count} 项硬性发现` : "无评估"}</span><span>${review.evaluation ? `${review.evaluation.governance_finding_count} 项治理发现` : ""}</span></div></div>
      <ul class="record-list">${review.findings.map((item) => `<li class="record"><div class="record-top"><h3>${escapeHtml(item.code)}</h3>${statusChip(item.severity)}</div><p>${escapeHtml(item.detail)}</p></li>`).join("")}</ul>
    </div><aside class="review-box">${reviewer ? `<h3>${escapeHtml(reviewer.display_name)}</h3><p>已登录为 ${escapeHtml(reviewer.reviewer_id)}</p><label>决策理由<textarea id="decision-reason" rows="5" placeholder="记录治理依据"></textarea></label><div class="decision-actions"><button class="primary-button" data-decision="APPROVE">批准发布目标</button><button class="secondary-button" data-decision="REJECT">拒绝公开发布</button><button class="secondary-button" data-decision="REQUEST_MORE_RESEARCH">要求补充研究</button><button class="secondary-button" id="logout-reviewer">退出登录</button></div>` : `<h3>审核员登录</h3><p>发布操作需要服务器配置的审核员。</p><form id="review-login"><label>密码<input name="password" type="password" autocomplete="current-password" required /></label><button class="primary-button" type="submit">登录</button></form>`}</aside></div>`;
  $("#review-login")?.addEventListener("submit", loginReviewer);
  $("#logout-reviewer")?.addEventListener("click", logoutReviewer);
}

function renderNoRun() {
  const isOverview = state.activeTab === "overview";
  panel.innerHTML = `${panelHeading("暂无运行", "创建或回放一个调查")}
    <div class="record">
      <p>该调查尚无运行记录。${isOverview ? "点击下方按钮启动真实大模型调查：" : '请切换到「概览」页启动调查。'}</p>
      ${isOverview ? '<button class="primary-button" id="start-run">开始调查</button><p class="record-meta" style="margin-top:12px;">将调用搜索、抓取与大模型 API（需配置 DEEPSEEK_API_KEY），结果整理到来源/证据/声明视图。</p>' : ""}
    </div>`;
  if (isOverview) $("#start-run")?.addEventListener("click", startRun);
}

async function renderTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll("#tabs button").forEach((button) => button.classList.toggle("is-active", button.dataset.tab === tab));
  panel.innerHTML = `<div class="record"><p>正在加载持久化${escapeHtml(tab)}数据…</p></div>`;
  try {
    const renderers = { overview: renderOverview, process: renderProcess, sources: renderSources, evidence: renderEvidence, claims: renderClaims, conflicts: renderConflicts, report: renderReport, review: renderReview };
    await renderers[tab]();
  } catch (error) {
    panel.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
  }
}

function _applyLiveState(st) {
  state.liveResult = st;
  state.run = null;
  state.citations = [];
  const draft = st.draft;
  state.report = draft
    ? {
        report: {
          title: st.topic,
          version: 1,
          report_type: "LIVE_RESEARCH",
          release_status: "DRAFT",
          review_status: "LIVE",
          report_hash: st.run_id,
        },
        sections: [
          { section_type: "executive_summary", content: { units: [{ text: draft.executive_summary.text }] } },
          { section_type: "rationale", content: { units: (draft.rationale || []).map((r) => ({ text: r.text })) } },
          { section_type: "next_steps", content: { units: (draft.next_steps || []).map((t) => ({ text: t })) } },
          { section_type: "limitations", content: { units: (draft.limitations || []).map((t) => ({ text: t })) } },
        ],
      }
    : null;
}

async function startRun() {
  if (!state.investigation) return;
  const button = $("#start-run");
  if (button) {
    button.disabled = true;
    button.textContent = "正在调查…";
  }
  showLoading("正在启动调查…");
  let pollTimer = null;
  try {
    const started = await fetchJson(
      `/api/investigations/${encodeURIComponent(state.investigation.investigation_id)}/research`,
      { method: "POST" }
    );
    const runId = started.run_id;
    const finalState = await new Promise((resolve, reject) => {
      let attempts = 0;
      const tick = async () => {
        attempts += 1;
        if (attempts > 240) {
          reject(new Error("调查超时（超过 10 分钟）"));
          return;
        }
        let st;
        try {
          st = await fetchJson(`/api/live-runs/${encodeURIComponent(runId)}`);
        } catch {
          showLoading("正在启动调查…");
          pollTimer = setTimeout(tick, 2500);
          return;
        }
        if (st.status === "completed") {
          resolve(st);
          return;
        }
        if (st.status === "failed" || st.status === "cancelled") {
          reject(new Error(`调查未完成：${st.error_category || "未知原因"}，请重试`));
          return;
        }
        const phase = PHASE_LABELS[st.phase] || st.phase || "进行中";
        const agent = AGENT_LABELS[st.active_agent] || "";
        const counts = `${st.evidence?.sources?.length || 0} 来源 · ${st.evidence?.claims?.length || 0} 证据`;
        showLoading(`正在调查（第 ${(st.research_round || 0) + 1} 轮）：${phase}${agent ? ` · ${agent}` : ""} — ${counts}`);
        pollTimer = setTimeout(tick, 2500);
      };
      tick();
    });
    liveRunCache[state.investigation.investigation_id] = finalState;
    _applyLiveState(finalState);
    $("#investigation-breadcrumb").textContent = `真实调研 · ${finalState.run_id}`;
    $("#run-badge").innerHTML = statusChip("COMPLETED");
    showToast("调查完成，结果已整理到来源/证据/声明");
    await renderTab("overview");
  } catch (error) {
    showToast(error.message);
    if (button) {
      button.disabled = false;
      button.textContent = "开始调查";
    }
  } finally {
    if (pollTimer) clearTimeout(pollTimer);
    hideLoading();
  }
}

async function runReplay() {
  const button = $("#run-replay");
  button.disabled = true;
  button.textContent = "正在回放持久化工作流…";
  showLoading("正在回放调查工作流…");
  try {
    const result = await fetchJson("/api/cases/east-palestine-2023/replay", { method: "POST" });
    showToast("回放完成并已持久化");
    await openInvestigation(result.investigation_id, result.run_id);
  } catch (error) {
    showToast(error.message);
  } finally {
    hideLoading();
    button.disabled = false;
    button.textContent = "运行回放调查";
  }
}

function exportPdf() {
  if (!state.report) return;
  showLoading("正在生成 PDF…");
  const title = escapeHtml(state.investigation?.title || "调查报告");
  const meta = state.report.report;
  const sectionsHtml = state.report.sections.map((section) => {
    const units = (section.content?.units || []).map((unit) => `<p>${escapeHtml(unit.text)}</p>`).join("");
    return `<section><h2>${words(section.section_type)}</h2>${units || "<p>（无内容）</p>"}</section>`;
  }).join("");
  const citationsHtml = state.citations.length
    ? `<section><h2>引用来源</h2><ol>${state.citations.map((c) => `<li>[${c.display_ordinal}] ${escapeHtml(c.claim_id)} — ${escapeHtml(c.evidence_id)}</li>`).join("")}</ol></section>`
    : "";
  const exportEl = document.createElement("div");
  exportEl.style.cssText = "max-width:780px;margin:0 auto;padding:24px;background:#fff;font-family:'Microsoft YaHei','PingFang SC','Segoe UI',sans-serif;color:#102536;line-height:1.7;";
  exportEl.innerHTML = `<h1 style="font-size:1.6rem;border-bottom:2px solid #1d6f9c;padding-bottom:8px;">${title}</h1>
<div style="color:#607280;font-size:0.85rem;margin-bottom:16px;">版本 ${escapeHtml(String(meta.version))} · 类型 ${words(meta.report_type)} · 发布状态 ${words(meta.release_status || "—")}</div>
${sectionsHtml}${citationsHtml}`;
  document.body.appendChild(exportEl);
  html2canvas(exportEl, { scale: 2, useCORS: true, backgroundColor: "#ffffff" }).then((canvas) => {
    document.body.removeChild(exportEl);
    const { jsPDF } = window.jspdf;
    const pdf = new jsPDF("p", "mm", "a4");
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();
    const imgWidth = pageWidth - 20;
    const imgHeight = (canvas.height * imgWidth) / canvas.width;
    let heightLeft = imgHeight;
    let position = 10;
    const imgData = canvas.toDataURL("image/png");
    pdf.addImage(imgData, "PNG", 10, position, imgWidth, imgHeight);
    heightLeft -= pageHeight - 20;
    while (heightLeft > 0) {
      position = heightLeft - imgHeight + 10;
      pdf.addPage();
      pdf.addImage(imgData, "PNG", 10, position, imgWidth, imgHeight);
      heightLeft -= pageHeight - 20;
    }
    hideLoading();
    pdf.save(`${title}.pdf`);
  }).catch((err) => {
    document.body.removeChild(exportEl);
    hideLoading();
    showToast("PDF 生成失败: " + err.message);
  });
}

async function generateReport() {
  await fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/reports`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ report_type: "FULL_INVESTIGATION" }) });
  state.report = null;
  await renderReport();
}

async function openCitation(citationId) {
  const detail = await fetchJson(`/api/citations/${encodeURIComponent(citationId)}`);
  $("#citation-title").textContent = `引用 ${detail.citation.display_ordinal}`;
  $("#citation-content").innerHTML = `<div class="chain-node"><strong>报告叙述</strong><p>${escapeHtml(detail.citation.section_key)} / ${escapeHtml(detail.citation.unit_key)}</p></div><div class="chain-node"><strong>声明 · ${escapeHtml(detail.claim?.validation_status || "缺失")}</strong><p>${escapeHtml(detail.claim?.statement || "声明不可用")}</p></div><div class="chain-node"><strong>证据原文</strong><blockquote class="evidence-quote">${escapeHtml(detail.evidence?.exact_quote || detail.evidence?.excerpt || "证据不可用")}</blockquote><p>${escapeHtml(JSON.stringify(detail.evidence?.locator_payload || detail.citation.canonical_locator))}</p></div><div class="chain-node"><strong>来源快照</strong><p>${escapeHtml(detail.source?.title || "来源不可用")}</p><p>${escapeHtml(detail.source?.publisher || "")}</p>${detail.source ? `<a href="${escapeHtml(safeUrl(detail.source.canonical_url))}" target="_blank" rel="noreferrer">打开原始来源</a>` : ""}</div><div class="chain-node"><strong>语义引用哈希</strong><p>${escapeHtml(detail.citation.citation_hash)}</p></div>`;
  $("#citation-drawer").classList.add("is-open");
  $("#citation-drawer").setAttribute("aria-hidden", "false");
}

async function loginReviewer(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  await fetchJson("/api/review/login", { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" }, body: JSON.stringify({ password: form.get("password") }) });
  showToast("审核员已登录");
  await renderReview();
}

async function logoutReviewer() {
  await fetchJson("/api/review/logout", { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" }, body: "{}" });
  showToast("审核员已退出");
  await renderReview();
}

async function submitDecision(decision) {
  const reason = $("#decision-reason")?.value.trim();
  if (!reason) return showToast("请输入决策理由");
  await fetchJson("/api/review/decisions", { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ report_id: state.report.report.report_id, decision, reason }) });
  showToast("审核决策已记录");
  state.report = null;
  await renderReview();
}

function safeUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
  } catch { return "#"; }
}

$("#run-replay").addEventListener("click", runReplay);
$("#refresh-button").addEventListener("click", loadInvestigations);
$("#investigation-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-investigation-id]");
  if (button) openInvestigation(button.dataset.investigationId);
});
$("#tabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-tab]");
  if (button) renderTab(button.dataset.tab);
});
panel.addEventListener("click", (event) => {
  const citation = event.target.closest("[data-citation-id]");
  const decision = event.target.closest("[data-decision]");
  if (citation) openCitation(citation.dataset.citationId);
  if (decision) submitDecision(decision.dataset.decision);
});
$("#close-citation").addEventListener("click", () => {
  $("#citation-drawer").classList.remove("is-open");
  $("#citation-drawer").setAttribute("aria-hidden", "true");
});
$("#new-investigation").addEventListener("click", () => $("#new-dialog").showModal());
$("#new-form").addEventListener("submit", async (event) => {
  if (event.submitter?.value === "cancel") return;
  event.preventDefault();
  // Capture the form element before any await: event.currentTarget becomes
  // null once event dispatch ends (the first await ends it).
  const formEl = event.currentTarget;
  const form = new FormData(formEl);
  try {
    const created = await fetchJson("/api/investigations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: form.get("title"), event_description: form.get("event_description"), investigation_goal: form.get("investigation_goal"), questions: String(form.get("questions") || "").split("\n").map((item) => item.trim()).filter(Boolean) }) });
    $("#new-dialog").close();
    formEl.reset();
    await openInvestigation(created.investigation_id);
  } catch (error) {
    showToast("创建失败: " + error.message);
  }
});

$("#edit-investigation").addEventListener("click", () => {
  const inv = state.investigation;
  if (!inv) return;
  const form = $("#edit-form");
  form.elements.title.value = inv.title;
  form.elements.event_description.value = inv.event_description;
  form.elements.investigation_goal.value = inv.investigation_goal;
  form.elements.questions.value = (inv.questions || []).map((q) => q.text).join("\n");
  $("#edit-dialog").showModal();
});
$("#edit-form").addEventListener("submit", async (event) => {
  if (event.submitter?.value === "cancel") return;
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    await fetchJson(`/api/investigations/${encodeURIComponent(state.investigation.investigation_id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: form.get("title"),
        event_description: form.get("event_description"),
        investigation_goal: form.get("investigation_goal"),
        questions: String(form.get("questions") || "").split("\n").map((item) => item.trim()).filter(Boolean),
      }),
    });
    $("#edit-dialog").close();
    showToast("调查已更新");
    await openInvestigation(state.investigation.investigation_id, state.run?.run_id || null);
  } catch (error) {
    showToast(error.message);
  }
});

boot();
