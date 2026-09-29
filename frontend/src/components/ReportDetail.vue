<script setup>
import { label, chineseText, validationExplanation } from '../composables/chinese.js'
import { ref, computed, watch, onUnmounted } from 'vue'
import request from '../api/request.js'
import FolioSelect from './FolioSelect.vue'
import ReviewPanel from './ReviewPanel.vue'
const props = defineProps({ runId: String, runStatus: String, showReview: { type: Boolean, default: true }, reports: { type: Array, default: () => [] }, evidence: { type: Array, default: () => [] } })
const emit = defineEmits(['updated'])
const generating = ref(false)
const canGenerate = computed(() => ['READY_FOR_REPORT', 'BLOCKED', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(props.runStatus))
async function generate() {
  if (generating.value || !canGenerate.value) return
  generating.value = true; error.value = ''
  try {
    const result = await request('/runs/' + props.runId + '/reports', { method: 'POST', body: JSON.stringify({ report_type: props.runStatus === 'READY_FOR_REPORT' ? 'FULL_INVESTIGATION' : 'INVESTIGATION_STATUS' }) })
    emit('updated')
    reportId.value = result.report.report_id
  } catch (e) { error.value = e.message }
  finally { generating.value = false }
}
const reportId = ref('')
const reportOptions = computed(() => props.reports.map(r => ({ value: r.report_id, label: `v${r.version} · ${{ FULL_INVESTIGATION: '完整调查报告', INVESTIGATION_STATUS: '调查状态报告' }[r.report_type] || r.report_type}`, description: label(r.report_type), status: r.release_status ? label(r.release_status) : '待评估', detail: r.report_id })))
const detail = ref(null)
const citations = ref([])
const error = ref('')
const citation = ref(null)
const citationLoading = ref(false)
const dialog = ref(null)
let version = 0
let citationVersion = 0
const titles = { EXECUTIVE_SUMMARY: '执行摘要', SCOPE_AND_MANDATE: '调查范围与目标', INVESTIGATION_QUESTIONS: '调查问题', METHODOLOGY: '调查方法', SOURCE_COVERAGE: '来源覆盖', TIMELINE: '事件时间线', VERIFIED_FINDINGS: '已验证发现', PROBABLE_FINDINGS: '可能成立的发现', DISPUTED_FINDINGS: '争议发现', QUANTITATIVE_FINDINGS: '量化发现', IMPACT_SCOPE_AND_ANALYSIS: '影响范围', CAUSAL_AND_MECHANISM_ANALYSIS: '原因与机制', ACTOR_AND_ATTRIBUTION_ASSESSMENT: '参与方与责任', CONFLICT_ANALYSIS: '冲突分析', REMEDIATION_AND_FOLLOW_UP: '应对与后续行动', LIMITATIONS_AND_RESEARCH_GAPS: '局限与研究缺口', CONCLUSIONS_AND_NEXT_STEPS: '结论与下一步', EXECUTIVE_STATUS: '当前调查状态', SEARCH_AND_SOURCE_SUMMARY: '搜索与来源概况', AVAILABLE_FINDINGS: '现有发现', BLOCKING_GAPS_AND_LIMITATIONS: '阻塞缺口与局限', NEXT_STEPS: '下一步' }
const safeUrl = value => /^https?:\/\//i.test(value || '') ? value : undefined
const refs = (section, unit) => citations.value.filter(c => c.section_key === section && c.unit_key === unit)
function snapshotId() { return citation.value?.evidence?.snapshot_id || props.evidence.find(e => e.evidence_id === citation.value?.evidence?.evidence_id)?.snapshot_id }
async function load(id) {
  const ticket = ++version
  detail.value = null
  citations.value = []
  error.value = ''
  if (!id) return
  try {
    const [report, links] = await Promise.all([request('/reports/' + id), request('/reports/' + id + '/citations')])
    if (ticket !== version) return
    detail.value = report
    citations.value = links
  } catch (e) { if (ticket === version) error.value = e.message }
}
async function openCitation(id) {
  const ticket = ++citationVersion
  citation.value = null
  citationLoading.value = true
  error.value = ''
  if (!dialog.value.open) dialog.value.showModal()
  try {
    const result = await request('/citations/' + id)
    if (ticket === citationVersion) citation.value = result
  } catch (e) { error.value = e.message }
  finally { if (ticket === citationVersion) citationLoading.value = false }
}
watch(() => props.reports.map(r => r.report_id).join(','), () => {
  if (!props.reports.some(r => r.report_id === reportId.value)) reportId.value = props.reports[0]?.report_id || ''
}, { immediate: true })
watch(reportId, load, { immediate: true })
onUnmounted(() => { version++; citationVersion++ })
</script>
<template>
  <section>
    <div class="row report-toolbar" v-if="runId && canGenerate"><p class="muted">按当前证据生成中文详版，保留旧版与原始引用，不重新联网调查。</p><button :disabled="generating" @click="generate">{{ generating ? '正在生成…' : '生成新版报告' }}</button></div>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p v-if="!reports.length" class="empty">当前运行尚未生成报告。调查运行结束后，可在此查看报告、引用与发布门禁。</p>
    <template v-else>
      <div class="row report-toolbar"><FolioSelect v-model="reportId" label="报告版本" :options="reportOptions" /><a class="button" :href="'/api/reports/' + encodeURIComponent(reportId) + '/export?format=markdown'" download>导出 Markdown</a></div>
      <template v-if="detail">
        <p class="notice">报告类型 {{ label(detail.report.report_type) }}；发布状态 {{ label(detail.report.release_status) }}；审核状态 {{ label(detail.report.review_status) }}。导出不会改变发布状态。</p>
        <nav class="report-outline" aria-label="报告目录"><a v-for="s in detail.sections" :key="s.section_id" :href="'#report-' + s.section_id">{{ titles[s.section_type] || label(s.section_type) }}</a></nav>
        <article :id="'report-' + s.section_id" v-for="s in detail.sections" :key="s.section_id" class="report-section"><h2>{{ titles[s.section_type] || s.section_type }}</h2><p v-if="!s.content?.units?.length" class="muted">{{ s.content?.status === 'NOT_APPLICABLE' ? '本节不适用。' : '当前证据不足，尚不能形成结论。' }}</p><p v-for="unit in s.content?.units || []" :key="unit.unit_key">{{ unit.text }} <button v-for="c in refs(s.section_type, unit.unit_key)" :key="c.citation_id" class="citation-link" @click="openCitation(c.citation_id)">[{{ c.display_ordinal + 1 }}]</button></p></article>
        <details><summary>报告完整性标识</summary><p class="muted">{{ detail.report.report_hash }}</p></details>
        <ReviewPanel v-if="showReview" :key="reportId" :report-id="reportId" @updated="load(reportId)" />
      </template>
    </template>
    <dialog ref="dialog" class="citation-dialog" aria-labelledby="citation-title"><div class="row"><h2 id="citation-title">引用溯源</h2><button @click="dialog.close()">关闭</button></div><p v-if="citationLoading" role="status">正在读取引用…</p><p v-if="error" class="notice error">{{ error }}</p><template v-if="citation"><h3>{{ chineseText(citation.claim?.statement) }}</h3><p>{{ label(citation.claim?.validation_status) }} · {{ validationExplanation(citation.claim) }}</p><p class="muted">证据原文（保留来源语言）</p><blockquote>{{ citation.evidence?.exact_quote || citation.evidence?.excerpt || '证据原文不可用' }}</blockquote><a :href="safeUrl(citation.source?.canonical_url)" target="_blank" rel="noopener noreferrer">{{ chineseText(citation.source?.title) || '来源不可用' }}</a><p class="muted">{{ chineseText(citation.source?.publisher) }} · 发布时间 {{ citation.source?.published_at || '未记录' }} · 采集时间 {{ citation.source?.retrieved_at || '未记录' }}</p><p v-if="snapshotId()"><a :href="'/api/snapshots/' + encodeURIComponent(snapshotId()) + '?format=cleaned'" target="_blank" rel="noopener">打开完整归档正文</a></p><details><summary>定位与引用标识</summary><pre>{{ JSON.stringify(citation.citation.canonical_locator, null, 2) }}</pre><p class="muted">{{ citation.citation.citation_hash }}</p></details></template></dialog>
  </section>
</template>

<style scoped>
.report-outline { display: flex; flex-wrap: wrap; gap: 10px 22px; margin: 24px 0 36px; padding: 18px 0; border-block: 1px solid var(--paper-edge); font-size: 14px; }
.report-section { max-width: 850px; scroll-margin-top: 96px; }
.report-section p { line-height: 1.95; overflow-wrap: anywhere; }
.report-toolbar { align-items: flex-end; margin: 20px 0; }
.report-toolbar .folio-select { flex: 1 1 320px; }
.report-toolbar > a { flex-shrink: 0; margin-bottom: 4px; }
@media (max-width: 680px) { .report-section { scroll-margin-top: 24px; } }
</style>
