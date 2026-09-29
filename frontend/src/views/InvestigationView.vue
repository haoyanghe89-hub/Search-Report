<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useInvestigation } from '../composables/useInvestigation.js'
import RunProgress from '../components/RunProgress.vue'
import RunHistory from '../components/RunHistory.vue'
import TopBar from '../components/TopBar.vue'
import AgentFlow from '../components/AgentFlow.vue'
import EvidenceChain from '../components/EvidenceChain.vue'
import SectionHeading from '../components/SectionHeading.vue'
import Timeline from '../components/Timeline.vue'
import ReviewPanel from '../components/ReviewPanel.vue'
import { projectAgents, verificationSummary, resultsPending, runModeLabel, runStatusLabel, runFailureLabel } from '../composables/presentation.js'
import ReportDetail from '../components/ReportDetail.vue'
const props = defineProps({ investigationId: { type: String, required: true }, replaying: Boolean })
const emit = defineEmits(['updated', 'replay', 'new-investigation'])
const { detail, runs, runId, run, budget, workers, data, loading, starting, error, running, load, loadRun, start, cancel } = useInvestigation(props.investigationId)
const pending = computed(() => resultsPending({ replaying: props.replaying, starting: starting.value, running: running.value, loading: loading.value }))
const tab = ref('overview')
const tabs = [['overview', '概览'], ['agents', '智能体流程'], ['sources', '来源'], ['evidence', '证据'], ['claims', '声明'], ['conflicts', '冲突与缺口'], ['timeline', '时间线'], ['report', '报告'], ['review', '审核']]
const query = ref('')
const selectedEvidence = ref('')
const filtered = computed(() => Object.fromEntries(['sources', 'evidence', 'claims'].map(key => [key, data.value[key].filter(x => JSON.stringify(x).toLowerCase().includes(query.value.toLowerCase()))])))
const source = id => data.value.sources.find(x => x.source_id === id)
const claim = id => data.value.claims.find(x => x.claim_id === id)
const date = value => value ? new Date(value).toLocaleString('zh-CN') : '未记录'
const modeLabel = runModeLabel
const snapshotUrl = id => '/api/snapshots/' + encodeURIComponent(id) + '?format=cleaned'
const safeUrl = value => /^https?:\/\//i.test(value || '') ? value : undefined
function viewEvidence(id) { selectedEvidence.value = id; query.value = ''; tab.value = 'evidence' }
async function launch() { await start(); emit('updated') }
const agents = computed(() => projectAgents(data.value.steps))
const verification = computed(() => verificationSummary(data.value.claims))
const chain = computed(() => [
  { number: data.value.sources.length, label: '信息来源', sub: 'Sources' },
  { number: data.value.evidence.length, label: '证据摘录', sub: 'Evidence' },
  { number: data.value.claims.length, label: '调查声明', sub: `${verification.value.verified} 条已验证` },
  { number: data.value.reports.length, label: '调查报告', sub: 'Reports' },
])
const timelinePreview = computed(() => data.value.timeline.slice(0, 5).map(e => ({ date: date(e.event_time), event: e.description, description: e.validation_status })))
const exportUrl = computed(() => !pending.value && data.value.reports[0] ? '/api/reports/' + encodeURIComponent(data.value.reports[0].report_id) + '/export?format=markdown' : '')
const searchDialog = ref(null)
const searchQuery = ref('')
const searchResults = computed(() => searchQuery.value.trim() ? ['sources', 'evidence', 'claims'].flatMap(key => data.value[key].map(x => ({ key, id: x.source_id || x.evidence_id || x.claim_id, text: x.statement || x.content || x.title }))).filter(x => x.text?.toLowerCase().includes(searchQuery.value.trim().toLowerCase())).slice(0, 40) : [])
function openSearch() { if (!pending.value) searchDialog.value.showModal() }
function selectResult(result) { tab.value = result.key; query.value = searchQuery.value; selectedEvidence.value = ''; searchDialog.value.close() }
function shortcut(event) { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openSearch() } }
watch(pending, value => { if (value) { searchDialog.value?.close(); tab.value = 'overview'; query.value = ''; selectedEvidence.value = '' } })
onMounted(() => window.addEventListener('keydown', shortcut))
onUnmounted(() => window.removeEventListener('keydown', shortcut))
</script>
<template>
  <div class="investigation-view">
    <TopBar :case-name="detail?.title || '读取中'" :category="run ? modeLabel(run) : '新建事件'" :export-url="exportUrl" :search-disabled="pending" @open-search="openSearch" />
    <div class="content-area">
    <header class="hero">
      <div class="hero-tag">事件调查 · {{ run ? modeLabel(run) : '等待调查' }}</div>
      <h1 class="hero-title">{{ detail?.title || '正在读取调查…' }}</h1>
      <p class="hero-lede">{{ detail?.investigation_goal || '重建事件经过，追溯证据与结论之间的联系。' }}</p>
      <div class="hero-meta-row">
        <div class="meta-block"><span class="meta-label">档案编号</span><span class="meta-value archive-id" :title="investigationId">{{ investigationId }}</span></div>
        <div class="meta-block"><span class="meta-label">运行状态</span><span class="meta-value">{{ replaying ? '正在回放' : starting ? '正在启动' : loading && !run ? '正在读取' : runStatusLabel(run?.status) || '尚未运行' }}</span></div>
        <div class="meta-block"><span class="meta-label">声明验证</span><span class="meta-value">{{ pending ? '等待本次结果' : verification.label }}</span></div>
        <div class="meta-block"><span class="meta-label">信息来源</span><span class="meta-value">{{ pending ? '收集与整理中' : data.sources.length + ' 个来源' }}</span></div>
      </div>
      <div class="hero-actions">
        <button v-if="investigationId === 'INV-EAST-PALESTINE-2023'" class="btn btn-primary" :disabled="pending" @click="emit('replay')">{{ replaying ? '正在回放…' : '运行回放调查' }} <span>→</span></button>
        <button v-else class="btn btn-primary" :disabled="starting || running || loading" @click="launch">{{ starting ? '正在启动…' : '启动联网调查' }} <span>→</span></button>
        <button class="btn btn-ghost" @click="emit('new-investigation')">调查新主题</button>
        <button v-if="running" class="btn btn-ghost" @click="cancel">取消运行</button>
        <button class="quiet-button" :disabled="pending" @click="load">刷新</button>
      </div>
    </header>
    <p v-if="error" class="notice error" role="alert">{{ error }} <button @click="load">重新加载</button></p>
    <p class="muted">联网调查使用服务端模型配置，可能产生调用费用。离线案例请使用左侧回放入口。</p>
    <div class="run-bar" v-if="runs.length"><RunHistory :runs="runs" :model-value="runId" :disabled="pending" @update:model-value="loadRun" /></div>
    <RunProgress v-if="pending" :replaying="replaying" :starting="starting" :running="running" :phase="run?.current_phase" :workers="workers" :budget="budget" :steps="data.steps" />
    <template v-else>
    <p v-if="run?.interruption_reason" class="notice">运行说明：{{ runFailureLabel(run.interruption_reason) }}</p>
    <nav class="section-nav" aria-label="调查内容"><button v-for="[key, label] in tabs" :key="key" class="nav-tab" :class="{ active: tab === key }" :aria-current="tab === key ? 'page' : undefined" @click="tab = key">{{ label }} <span class="tab-count" v-if="Array.isArray(data[key])">{{ data[key].length }}</span></button></nav>
    <section v-if="tab === 'overview'">
      <AgentFlow :agents="agents"><template #heading><SectionHeading section-num="01" section-name="智能体协作" section-desc="执行记录驱动" /></template></AgentFlow>
      <EvidenceChain :chain="chain"><template #heading><SectionHeading section-num="02" section-name="证据链概览" section-desc="由来源到结论" /></template></EvidenceChain>
      <div v-if="run" class="overview-columns">
        <section><SectionHeading section-num="03" section-name="事件时间线" /><Timeline :items="timelinePreview" /><p v-if="!timelinePreview.length" class="empty">尚无有证据关联的事件。</p><button class="quiet-button" @click="tab = 'timeline'">查看完整时间线 →</button></section>
        <section><SectionHeading section-num="04" section-name="关键声明" /><article v-for="c in data.claims.slice(0, 4)" :key="c.claim_id" class="claim-preview"><span class="badge" :class="c.validation_status.toLowerCase()">{{ c.validation_status }}</span><p>{{ c.statement }}</p></article><p v-if="!data.claims.length" class="empty">尚无调查声明。</p><button class="quiet-button" @click="tab = 'claims'">查看声明与验证依据 →</button></section>
      </div>
      <SectionHeading section-num="05" section-name="调查范围" /><p class="prose">{{ detail?.event_description }}</p>
      <ul class="questions"><li v-for="q in detail?.questions" :key="q.question_id">{{ q.text }}</li></ul>
      <p v-if="!run" class="empty">尚无运行记录。启动联网调查后，这里会显示实际执行步骤。</p>
    </section>
    <section v-if="tab === 'agents'">
      <AgentFlow :agents="agents"><template #heading><SectionHeading section-num="01" section-name="智能体流程" section-desc="实际持久化步骤" /></template></AgentFlow>
        <h2>执行记录 <small>{{ run?.current_phase }}</small></h2>
        <div class="table-wrap"><table><thead><tr><th>角色 / 阶段</th><th>步骤</th><th>状态</th><th>耗时</th></tr></thead><tbody><tr v-for="s in data.steps" :key="s.step_id"><td>{{ s.agent_role }}<small>{{ s.phase }}</small></td><td>{{ s.logical_step_key }}<small v-if="s.error_code">{{ s.error_code }}</small></td><td>{{ s.status }}</td><td>{{ (s.active_elapsed_ms / 1000).toFixed(1) }} 秒</td></tr></tbody></table></div>
        <p v-if="!data.steps.length" class="empty">尚无持久化执行步骤。</p>
        <p v-if="budget" class="notice">已用预算：搜索 {{ budget.search_calls_used }}/{{ budget.max_search_calls }}，抓取 {{ budget.fetch_calls_used }}/{{ budget.max_fetch_calls }}，模型 {{ budget.model_calls_used }}/{{ budget.max_model_calls }}，Token {{ budget.tokens_used }}/{{ budget.max_tokens }}。</p>
    </section>
    <label v-if="['sources','evidence','claims'].includes(tab)" class="filter">筛选当前记录<input v-model="query" type="search" placeholder="输入关键词" /></label>
    <section v-if="tab === 'sources'">
      <p v-if="!filtered.sources.length" class="empty">暂无匹配来源。</p>
      <article v-for="s in filtered.sources" :key="s.source_id" class="record">
        <div class="row"><h2><a :href="safeUrl(s.canonical_url)" target="_blank" rel="noopener noreferrer">{{ s.title }}</a></h2><span class="badge">{{ s.evidence_eligible === true ? '可用于取证' : s.evidence_eligible === false ? '不可用于取证' : '待检查' }}</span></div>
        <p>{{ s.publisher || s.organization || '发布机构未知' }} · {{ s.source_type }} · {{ s.parse_status || '尚未解析' }}</p>
        <p class="muted">发布时间：{{ date(s.published_at) }}；采集时间：{{ date(s.retrieved_at) }}</p>
        <p class="muted">来源家族：{{ s.family_id || '尚未确认' }}</p>
        <a v-if="s.snapshot_id" :href="snapshotUrl(s.snapshot_id)" target="_blank" rel="noopener">打开归档正文</a>
      </article>
    </section>
    <section v-if="tab === 'evidence'">
      <p v-if="!filtered.evidence.length" class="empty">暂无匹配证据。</p>
      <button v-if="selectedEvidence" @click="selectedEvidence = ''">显示全部证据</button>
      <article v-for="e in filtered.evidence.filter(x => !selectedEvidence || x.evidence_id === selectedEvidence)" :key="e.evidence_id" class="record">
        <h2>{{ source(e.source_id)?.title || e.evidence_id }}</h2><blockquote>{{ e.content }}</blockquote>
        <p class="muted">{{ e.evidence_id }} · {{ e.locator_type }} · 提取于 {{ date(e.extracted_at) }}</p>
        <a :href="snapshotUrl(e.snapshot_id)" target="_blank" rel="noopener">查看归档正文与定位上下文</a>
        <details><summary>精确定位数据</summary><pre>{{ JSON.stringify(e.locator_payload, null, 2) }}</pre></details>
        <ul><li v-for="r in e.relations" :key="r.claim_id">{{ r.stance }} / {{ r.entailment_status }}：{{ claim(r.claim_id)?.statement || r.claim_id }}</li></ul>
      </article>
    </section>
    <section v-if="tab === 'claims'">
      <p v-if="!filtered.claims.length" class="empty">暂无匹配声明。</p>
      <article v-for="c in filtered.claims" :key="c.claim_id" class="record">
        <div class="row"><span class="badge" :class="c.validation_status.toLowerCase()">{{ c.validation_status }}</span><small>{{ c.claim_type }} / {{ c.importance }}</small></div>
        <h2>{{ c.statement }}</h2><p>{{ c.validation_basis || '尚无验证依据' }}</p><p class="muted">置信度：{{ c.confidence === null ? '未评估' : c.confidence }}；{{ c.confidence_basis || '未记录置信度说明' }}</p>
        <div class="actions"><button v-for="id in c.supporting_evidence_ids" :key="id" @click="viewEvidence(id)">支持证据 {{ data.evidence.findIndex(e => e.evidence_id === id) + 1 }}</button><button v-for="id in c.contradicting_evidence_ids" :key="id" @click="viewEvidence(id)">反证 {{ data.evidence.findIndex(e => e.evidence_id === id) + 1 }}</button></div>
      </article>
    </section>
    <section v-if="tab === 'conflicts'">
      <h2>冲突</h2><p v-if="!data.conflicts.length" class="empty">当前记录未发现冲突；这不代表已经排除所有矛盾。</p>
      <article v-for="c in data.conflicts" :key="c.conflict_id" class="record"><h3>{{ c.conflict_type }} · {{ c.severity }} · {{ c.status }}</h3><ul><li v-for="id in c.claim_ids" :key="id">{{ claim(id)?.statement || id }}</li></ul><p>{{ c.resolution_summary || '尚无解决结论' }}</p><p>{{ c.resolution_basis }}</p><p v-for="reason in c.possible_explanations" :key="reason">{{ reason }}</p><details><summary>冲突值与可能原因</summary><pre>{{ JSON.stringify({ values: c.competing_values, causes: c.possible_causes }, null, 2) }}</pre></details></article>
      <h2>研究缺口</h2><p v-if="!data.gaps.length" class="empty">暂无记录。</p><article v-for="g in data.gaps" :key="g.gap_id" class="record"><h3>{{ g.gap_type }} · {{ g.severity }} · {{ g.status }}</h3><p>{{ g.reason }}</p><p>{{ g.suggested_action }}</p><ul><li v-for="action in g.suggested_actions" :key="action">{{ action }}</li></ul></article>
    </section>
    <section v-if="tab === 'timeline'">
      <p v-if="!data.timeline.length" class="empty">暂无有证据关联的时间线记录。</p>
      <article v-for="event in data.timeline" :key="event.timeline_event_id" class="record"><time>{{ date(event.event_time) }}</time><h2>{{ event.description }}</h2><p>{{ event.time_precision }} · {{ event.validation_status }}</p><button v-for="id in event.evidence_ids" :key="id" @click="viewEvidence(id)">查看事件证据</button></article>
    </section>
    <ReportDetail v-if="tab === 'report'" :reports="data.reports" :evidence="data.evidence" :show-review="false" />
    <section v-if="tab === 'review'"><ReviewPanel v-if="data.reports.length" :key="data.reports[0].report_id" :report-id="data.reports[0].report_id" @updated="loadRun()" /><p v-else class="empty">当前运行尚未生成报告。</p></section>
    </template>
    </div>
    <dialog ref="searchDialog" class="search-dialog" aria-labelledby="search-title"><div class="row"><h2 id="search-title">搜索当前调查</h2><button @click="searchDialog.close()">关闭</button></div><label>来源、证据与声明<input v-model="searchQuery" type="search" placeholder="输入关键词" autofocus /></label><p v-if="!searchQuery.trim()" class="muted">在当前运行的真实记录中检索。</p><p v-else-if="!searchResults.length" class="empty">没有匹配记录。</p><button v-for="(result, index) in searchResults" :key="index" class="search-result" @click="selectResult(result)"><small>{{ {sources: '来源', evidence: '证据', claims: '声明'}[result.key] }}</small>{{ result.text }}</button></dialog>
  </div>
</template>

<style scoped>
.investigation-view {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.content-area {
  padding: 56px 64px 80px;
  flex: 1;
  max-width: var(--content-max-width);
  margin: 0 auto;
  width: 100%;
}

/* Hero */
.hero {
  margin-bottom: 64px;
  position: relative;
}

.hero-tag {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 28px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent);
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.hero-tag::before {
  content: '';
  width: 28px;
  height: 1px;
  background: var(--accent);
}

.hero-title {
  font-family: var(--font-display);
  font-size: 52px;
  font-weight: 500;
  line-height: 1.15;
  color: var(--ink-black);
  margin-bottom: 24px;
  letter-spacing: -0.02em;
  font-variation-settings: "opsz" 144;
  word-break: break-word;
  overflow-wrap: break-word;
}

.hero-title em {
  font-style: italic;
  font-weight: 400;
  color: var(--ink-soft);
}

.hero-lede {
  max-width: 640px;
  font-size: 18px;
  line-height: 1.8;
  color: var(--ink-soft);
  font-family: var(--font-serif);
  font-style: italic;
  font-weight: 400;
  padding-left: 24px;
  border-left: 2px solid var(--accent-line);
  margin-bottom: 32px;
}

.hero-meta-row {
  display: flex;
  gap: 48px;
  padding-top: 24px;
  border-top: 1px solid var(--paper-edge);
  position: relative;
}

.hero-meta-row::before {
  content: '';
  position: absolute;
  top: -1px;
  left: 0;
  width: 40px;
  height: 1px;
  background: var(--accent);
}

.meta-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-label {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-faint);
}

.meta-value {
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 600;
  color: var(--ink-deep);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.meta-value.verified {
  color: var(--status-verified);
}

.hero-actions {
  display: flex;
  gap: 12px;
  margin-top: 32px;
}

.btn {
  padding: 14px 28px;
  border-radius: 2px;
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.4s var(--ease-out);
  border: 1px solid transparent;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  position: relative;
  overflow: hidden;
}

.btn-primary {
  background: var(--ink-black);
  color: var(--paper-base);
  border-color: var(--ink-black);
}

.btn-primary::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.1), transparent);
  transition: left 0.6s var(--ease-out);
}

.btn-primary:hover::before {
  left: 100%;
}

.btn-primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(28, 22, 16, 0.15);
}

.btn-ghost {
  background: transparent;
  color: var(--ink-soft);
  border-color: var(--paper-edge);
}

.btn-ghost:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.btn-arrow {
  transition: transform 0.35s var(--ease-out);
  font-style: normal;
}

.btn:hover .btn-arrow {
  transform: translateX(4px);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 运行结果反馈 */
.run-feedback {
  margin-top: 16px;
  padding: 12px 20px;
  font-family: var(--font-serif);
  font-size: 14px;
  border-left: 3px solid;
}

.run-feedback.success {
  background: var(--accent-pale);
  border-left-color: var(--status-verified);
  color: var(--ink-deep);
}

.run-feedback.error {
  background: #fef2f2;
  border-left-color: #dc2626;
  color: #991b1b;
}

/* 章节导航 Tabs */
.section-nav {
  display: flex;
  gap: 0;
  margin-bottom: 48px;
  border-bottom: 1px solid var(--paper-edge);
  position: relative;
  overflow-x: auto;
}

.nav-tab {
  padding: 16px 0;
  margin-right: 36px;
  background: none;
  border: none;
  font-family: var(--font-serif);
  font-size: 14px;
  font-weight: 500;
  color: var(--ink-muted);
  cursor: pointer;
  position: relative;
  transition: color 0.35s var(--ease-out);
  white-space: nowrap;
  flex-shrink: 0;
}

.nav-tab::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 0;
  width: 0;
  height: 1px;
  background: var(--ink-black);
  transition: width 0.5s var(--ease-out);
}

.nav-tab:hover {
  color: var(--ink-deep);
}

.nav-tab.active {
  color: var(--ink-black);
  font-weight: 600;
}

.nav-tab.active::after {
  width: 100%;
}

.tab-count {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-faint);
  margin-left: 6px;
  font-weight: 400;
}

/* 两列布局 */
.two-column {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 64px;
  margin-bottom: 56px;
}

/* 占位 */
.tab-placeholder {
  padding: 80px 0;
  text-align: center;
}

.placeholder-text {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 18px;
  color: var(--ink-faint);
}

/* 底部 */
/* 新调查空状态 */
.empty-investigation {
  text-align: center;
  padding: 80px 40px;
  background: white;
  box-shadow: 0 1px 2px var(--paper-shadow), 0 8px 32px rgba(60, 45, 20, 0.06);
}

.empty-icon {
  width: 80px;
  height: 80px;
  margin: 0 auto 24px;
  color: var(--accent);
  opacity: 0.6;
}

.empty-icon svg {
  width: 100%;
  height: 100%;
}

.empty-title {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 600;
  color: var(--ink-deep);
  margin: 0 0 12px 0;
}

.empty-desc {
  font-family: var(--font-serif);
  font-size: 14px;
  color: var(--ink-soft);
  margin: 0 0 32px 0;
  font-style: italic;
}

.empty-steps {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  max-width: 500px;
  margin: 0 auto 32px;
  text-align: left;
}

.empty-step {
  display: flex;
  gap: 12px;
  padding: 16px;
  background: var(--paper-warm);
  border: 1px solid var(--paper-edge);
  transition: all 0.3s var(--ease-out);
}

.empty-step:hover {
  border-color: var(--accent-line);
  transform: translateY(-2px);
  background: white;
}

.step-num {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--accent-pale);
  color: var(--accent);
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.step-title {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-deep);
  margin-bottom: 4px;
}

.step-desc {
  font-family: var(--font-serif);
  font-size: 12px;
  color: var(--ink-muted);
  line-height: 1.5;
}

.empty-cta {
  margin-top: 8px;
}

.page-footer {
  margin-top: 80px;
  padding-top: 24px;
  border-top: 1px solid var(--paper-edge);
  display: flex;
  justify-content: space-between;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-faint);
}

/* 响应式 */
@media (max-width: 1200px) {
  .content-area {
    padding: 40px 40px 64px;
  }
}

@media (max-width: 900px) {
  .two-column {
    grid-template-columns: 1fr;
    gap: 40px;
  }

  .hero-title {
    font-size: 36px;
  }

  .hero-meta-row {
    flex-wrap: wrap;
    gap: 24px;
  }
}
</style>
