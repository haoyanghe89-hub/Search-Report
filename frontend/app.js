const state = {
  investigations: [],
  investigation: null,
  run: null,
  report: null,
  citations: [],
  activeTab: "overview",
};

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
  if (!value) return "Not recorded";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
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
    $("#system-state").lastChild.textContent = " Connected";
    await loadInvestigations();
    const cases = await fetchJson("/api/cases");
    const replay = $("#run-replay");
    replay.disabled = !cases[0]?.replay_ready;
    if (!cases[0]?.replay_ready) replay.title = "Replay fixture is not configured";
  } catch (error) {
    $("#system-state").lastChild.textContent = " Backend unavailable";
    panel.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
  }
}

async function loadInvestigations() {
  state.investigations = await fetchJson("/api/investigations");
  $("#investigation-list").innerHTML = state.investigations.map((item) => `
    <button class="investigation-link ${state.investigation?.investigation_id === item.investigation_id ? "is-active" : ""}"
      data-investigation-id="${escapeHtml(item.investigation_id)}">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${item.run_count} run${item.run_count === 1 ? "" : "s"}</span>
    </button>`).join("");
}

async function openInvestigation(investigationId, preferredRunId = null) {
  const [investigation, runs] = await Promise.all([
    fetchJson(`/api/investigations/${encodeURIComponent(investigationId)}`),
    fetchJson(`/api/investigations/${encodeURIComponent(investigationId)}/runs`),
  ]);
  state.investigation = investigation;
  const selected = preferredRunId ? runs.find((run) => run.run_id === preferredRunId) : runs[0];
  state.run = selected ? (await fetchJson(`/api/runs/${encodeURIComponent(selected.run_id)}`)).run : null;
  state.report = null;
  state.citations = [];
  $("#case-hero").classList.add("is-hidden");
  $("#empty-guidance").classList.add("is-hidden");
  $("#active-investigation").classList.remove("is-hidden");
  $("#investigation-title").textContent = investigation.title;
  $("#investigation-goal").textContent = investigation.investigation_goal;
  $("#investigation-breadcrumb").textContent = state.run ? `Replay run · ${state.run.run_id}` : "Investigation draft";
  $("#run-badge").innerHTML = state.run ? statusChip(state.run.status) : statusChip("NO_RUN");
  await loadInvestigations();
  await renderTab(state.activeTab);
}

function panelHeading(title, detail) {
  return `<div class="panel-heading"><h2>${escapeHtml(title)}</h2><p>${escapeHtml(detail)}</p></div>`;
}

async function renderOverview() {
  const item = state.investigation;
  const counts = item.counts;
  const budget = state.run ? (await fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}`)).budget : null;
  panel.innerHTML = `${panelHeading("Investigation overview", "Persisted state")}
    <div class="metric-strip">
      ${[[counts.sources, "Sources"], [counts.evidence, "Evidence"], [counts.claims, "Claims"], [counts.conflicts, "Conflicts"], [counts.open_gaps, "Open gaps"]].map(([value, label]) => `<div class="metric"><strong>${value}</strong><span>${label}</span></div>`).join("")}
    </div>
    <ul class="question-list">${item.questions.map((question) => `<li class="record"><div class="record-top"><h3>${escapeHtml(question.text)}</h3>${question.is_critical ? statusChip("CRITICAL") : ""}</div></li>`).join("")}</ul>
    ${budget ? `<div class="record"><h3>Replay budget</h3><div class="record-meta"><span>rounds ${budget.research_rounds_used}/${budget.max_research_rounds}</span><span>search ${budget.search_calls_used}/${budget.max_search_calls}</span><span>fetch ${budget.fetch_calls_used}/${budget.max_fetch_calls}</span><span>model ${budget.model_calls_used}/${budget.max_model_calls}</span><span>sources ${budget.sources_used}/${budget.max_sources}</span></div></div>` : ""}`;
}

async function renderProcess() {
  if (!state.run) return renderNoRun();
  const steps = await fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/steps`);
  const looped = steps.some((step) => step.research_round && step.research_round > 1);
  panel.innerHTML = `${panelHeading("Agent process", `${steps.length} durable steps`)}
    <div class="trace"><div class="trace-stage"><strong>Planner</strong><span>PLAN</span></div><div class="trace-stage"><strong>Researcher</strong><span>COLLECT</span></div><div class="trace-stage"><strong>Analyst</strong><span>ANALYZE</span></div><div class="trace-stage"><strong>Verifier</strong><span>VERIFY</span></div></div>
    ${looped ? `<div class="feedback-loop">Verifier feedback triggered a bounded ResearchGap → COLLECT → ANALYZE → VERIFY loop.</div>` : ""}
    <ul class="record-list">${steps.map((step) => `<li class="record"><div class="record-top"><h3>${escapeHtml(step.agent_role)} · ${escapeHtml(step.logical_step_key)}</h3>${statusChip(step.status)}</div><div class="record-meta"><span>${escapeHtml(step.phase)}</span><span>${escapeHtml(step.step_type)}</span><span>round ${step.research_round ?? "—"}</span><span>${step.active_elapsed_ms} ms</span></div></li>`).join("")}</ul>`;
}

async function renderSources() {
  if (!state.run) return renderNoRun();
  const rows = await fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/sources`);
  panel.innerHTML = `${panelHeading("Sources", `${rows.length} persisted source identities`)}<ul class="record-list">${rows.map((row) => `<li class="record"><div class="record-top"><h3>${escapeHtml(row.title)}</h3>${statusChip(row.parse_status || "DISCOVERED")}</div><p>${escapeHtml(row.publisher || row.organization || "Publisher not recorded")}</p><div class="record-meta"><span>${words(row.source_type)}</span><span>${row.is_official ? "official" : "independent"}</span><span>${row.is_first_hand ? "first hand" : "secondary"}</span><span>snapshot ${escapeHtml(row.snapshot_id || "pending")}</span></div><p><a href="${escapeHtml(safeUrl(row.canonical_url))}" target="_blank" rel="noreferrer">Open canonical source</a></p></li>`).join("")}</ul>`;
}

async function renderEvidence() {
  if (!state.run) return renderNoRun();
  const rows = await fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/evidence`);
  panel.innerHTML = `${panelHeading("Evidence", `${rows.length} locator-bound excerpts`)}<ul class="record-list">${rows.map((row) => `<li class="record"><h3>${escapeHtml(row.evidence_id)}</h3><blockquote class="evidence-quote">${escapeHtml(row.content)}</blockquote><div class="record-meta"><span>${words(row.locator_type)}</span><span>${escapeHtml(JSON.stringify(row.locator_payload))}</span><span>${row.relations.length} claim relation(s)</span></div></li>`).join("")}</ul>`;
}

async function renderClaims() {
  if (!state.run) return renderNoRun();
  const rows = await fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/claims`);
  panel.innerHTML = `${panelHeading("Claims", `${rows.length} atomic claims`)}<ul class="record-list">${rows.map((row) => `<li class="record"><div class="record-top"><h3>${escapeHtml(row.statement)}</h3>${statusChip(row.validation_status)}</div><p>${escapeHtml(row.validation_basis || row.confidence_basis || "No validation basis recorded")}</p><div class="record-meta"><span>${words(row.claim_type)}</span><span>${words(row.importance)}</span><span>confidence ${row.confidence == null ? "—" : row.confidence.toFixed(2)}</span><span>${row.supporting_evidence_ids.length} supporting evidence</span></div></li>`).join("")}</ul>`;
}

async function renderConflicts() {
  if (!state.run) return renderNoRun();
  const [conflicts, gaps] = await Promise.all([
    fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/conflicts`),
    fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/gaps`),
  ]);
  panel.innerHTML = `${panelHeading("Conflicts & gaps", `${conflicts.length} conflicts · ${gaps.length} research gaps`)}
    <ul class="record-list">${conflicts.map((row) => `<li class="record"><div class="record-top"><h3>${words(row.conflict_type)} conflict</h3>${statusChip(row.resolution_status)}</div><p>${escapeHtml(row.resolution_summary || row.resolution_basis || "Unresolved")}</p><div class="record-meta"><span>${words(row.severity)}</span><span>${row.claim_ids.length} linked claim(s)</span></div></li>`).join("") || `<li class="record"><p>No conflict set was persisted.</p></li>`}</ul>
    <ul class="record-list">${gaps.map((row) => `<li class="record"><div class="record-top"><h3>${escapeHtml(row.reason)}</h3>${statusChip(row.status)}</div><p>${escapeHtml(row.suggested_action || row.suggested_actions.join(" · ") || "No action recorded")}</p><div class="record-meta"><span>${words(row.gap_type)}</span><span>${words(row.severity)}</span></div></li>`).join("")}</ul>`;
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
    panel.innerHTML = `${panelHeading("Report", "No report version")}
      <div class="record"><p>This run has no report yet.</p>${state.run?.status === "READY_FOR_REPORT" ? `<button class="primary-button" id="generate-report">Generate full report</button>` : ""}</div>`;
    $("#generate-report")?.addEventListener("click", generateReport);
    return;
  }
  const citationsByUnit = new Map();
  for (const citation of state.citations) {
    const group = citationsByUnit.get(citation.unit_key) || [];
    group.push(citation);
    citationsByUnit.set(citation.unit_key, group);
  }
  panel.innerHTML = `${panelHeading("Investigation report", `Version ${report.report.version} · ${words(report.report.report_type)}`)}
    <div class="record-meta"><span>${statusChip(report.report.release_status)}</span><span>review ${words(report.report.review_status)}</span><span>hash ${escapeHtml(report.report.report_hash.slice(0, 16))}…</span></div>
    <article>${report.sections.map((section) => `<section class="report-section"><h3>${words(section.section_type)}</h3>${(section.content?.units || []).map((unit) => `<p class="report-unit">${escapeHtml(unit.text)} ${(citationsByUnit.get(unit.unit_key) || []).map((citation) => `<button class="citation-button" data-citation-id="${escapeHtml(citation.citation_id)}">[${citation.display_ordinal}]</button>`).join(" ")}</p>`).join("") || `<p class="report-unit">${words(section.content?.status || "No supported material")}</p>`}</section>`).join("")}</article>`;
}

async function renderReview() {
  const report = state.report || await loadLatestReport();
  if (!report) return renderReport();
  const review = await fetchJson(`/api/reports/${encodeURIComponent(report.report.report_id)}/review`);
  let reviewer = null;
  try { reviewer = await fetchJson("/api/review/me"); } catch { /* not signed in */ }
  panel.innerHTML = `${panelHeading("Release review", "Governance only — claim status is immutable here")}
    <div class="review-layout"><div>
      <div class="record"><div class="record-top"><h3>Release evaluation</h3>${statusChip(review.release_status)}</div><p>${escapeHtml(review.pending_request?.trigger_reason || "No pending human review request")}</p><div class="record-meta"><span>${review.evaluation ? `${review.evaluation.hard_finding_count} hard findings` : "no evaluation"}</span><span>${review.evaluation ? `${review.evaluation.governance_finding_count} governance findings` : ""}</span></div></div>
      <ul class="record-list">${review.findings.map((item) => `<li class="record"><div class="record-top"><h3>${escapeHtml(item.code)}</h3>${statusChip(item.severity)}</div><p>${escapeHtml(item.detail)}</p></li>`).join("")}</ul>
    </div><aside class="review-box">${reviewer ? `<h3>${escapeHtml(reviewer.display_name)}</h3><p>Signed in as ${escapeHtml(reviewer.reviewer_id)}</p><label>Decision reason<textarea id="decision-reason" rows="5" placeholder="Record the governance rationale"></textarea></label><div class="decision-actions"><button class="primary-button" data-decision="APPROVE">Approve policy target</button><button class="secondary-button" data-decision="REJECT">Reject public release</button><button class="secondary-button" data-decision="REQUEST_MORE_RESEARCH">Request more research</button><button class="secondary-button" id="logout-reviewer">Log out</button></div>` : `<h3>Reviewer sign-in</h3><p>A server-configured reviewer is required for release actions.</p><form id="review-login"><label>Password<input name="password" type="password" autocomplete="current-password" required /></label><button class="primary-button" type="submit">Sign in</button></form>`}</aside></div>`;
  $("#review-login")?.addEventListener("submit", loginReviewer);
  $("#logout-reviewer")?.addEventListener("click", logoutReviewer);
}

function renderNoRun() {
  panel.innerHTML = `${panelHeading("No run", "Create or replay an investigation")}
    <div class="record"><p>This investigation does not have a persisted run yet.</p></div>`;
}

async function renderTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll("#tabs button").forEach((button) => button.classList.toggle("is-active", button.dataset.tab === tab));
  panel.innerHTML = `<div class="record"><p>Loading persisted ${escapeHtml(tab)} data…</p></div>`;
  try {
    const renderers = { overview: renderOverview, process: renderProcess, sources: renderSources, evidence: renderEvidence, claims: renderClaims, conflicts: renderConflicts, report: renderReport, review: renderReview };
    await renderers[tab]();
  } catch (error) {
    panel.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
  }
}

async function runReplay() {
  const button = $("#run-replay");
  button.disabled = true;
  button.textContent = "Replaying durable workflow…";
  try {
    const result = await fetchJson("/api/cases/east-palestine-2023/replay", { method: "POST" });
    showToast("Replay completed and persisted");
    await openInvestigation(result.investigation_id, result.run_id);
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Run replay investigation";
  }
}

async function generateReport() {
  await fetchJson(`/api/runs/${encodeURIComponent(state.run.run_id)}/reports`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ report_type: "FULL_INVESTIGATION" }) });
  state.report = null;
  await renderReport();
}

async function openCitation(citationId) {
  const detail = await fetchJson(`/api/citations/${encodeURIComponent(citationId)}`);
  $("#citation-title").textContent = `Citation ${detail.citation.display_ordinal}`;
  $("#citation-content").innerHTML = `<div class="chain-node"><strong>Report narrative</strong><p>${escapeHtml(detail.citation.section_key)} / ${escapeHtml(detail.citation.unit_key)}</p></div><div class="chain-node"><strong>Claim · ${escapeHtml(detail.claim?.validation_status || "missing")}</strong><p>${escapeHtml(detail.claim?.statement || "Claim unavailable")}</p></div><div class="chain-node"><strong>Evidence exact quote</strong><blockquote class="evidence-quote">${escapeHtml(detail.evidence?.exact_quote || detail.evidence?.excerpt || "Evidence unavailable")}</blockquote><p>${escapeHtml(JSON.stringify(detail.evidence?.locator_payload || detail.citation.canonical_locator))}</p></div><div class="chain-node"><strong>Source snapshot</strong><p>${escapeHtml(detail.source?.title || "Source unavailable")}</p><p>${escapeHtml(detail.source?.publisher || "")}</p>${detail.source ? `<a href="${escapeHtml(safeUrl(detail.source.canonical_url))}" target="_blank" rel="noreferrer">Open canonical source</a>` : ""}</div><div class="chain-node"><strong>Semantic citation hash</strong><p>${escapeHtml(detail.citation.citation_hash)}</p></div>`;
  $("#citation-drawer").classList.add("is-open");
  $("#citation-drawer").setAttribute("aria-hidden", "false");
}

async function loginReviewer(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  await fetchJson("/api/review/login", { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" }, body: JSON.stringify({ password: form.get("password") }) });
  showToast("Reviewer signed in");
  await renderReview();
}

async function logoutReviewer() {
  await fetchJson("/api/review/logout", { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" }, body: "{}" });
  showToast("Reviewer signed out");
  await renderReview();
}

async function submitDecision(decision) {
  const reason = $("#decision-reason")?.value.trim();
  if (!reason) return showToast("Enter a decision reason");
  await fetchJson("/api/review/decisions", { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ report_id: state.report.report.report_id, decision, reason }) });
  showToast("Review decision recorded");
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
  const form = new FormData(event.currentTarget);
  const created = await fetchJson("/api/investigations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: form.get("title"), event_description: form.get("event_description"), investigation_goal: form.get("investigation_goal"), questions: String(form.get("questions") || "").split("\n").map((item) => item.trim()).filter(Boolean) }) });
  $("#new-dialog").close();
  event.currentTarget.reset();
  await openInvestigation(created.investigation_id);
});

boot();
