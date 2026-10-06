<script setup>
import { label, chineseText, validationExplanation } from '../composables/chinese.js'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { clearDialogMotion, closeDialog, openDialog } from '../utils/dialogMotion.js'
import { tokenDuration, tokenEase, tokenLength, tokenNumber, tokenValue } from '../utils/motionTokens.js'
import { partitionReportSections } from '../utils/reportPresentation.js'
import request from '../api/request.js'
import FolioSelect from './FolioSelect.vue'
import ReviewPanel from './ReviewPanel.vue'
import QuantReportSection from './quant/QuantReportSection.vue'

gsap.registerPlugin(ScrollTrigger)

const props = defineProps({ runId: String, runStatus: String, showReview: { type: Boolean, default: true }, reports: { type: Array, default: () => [] }, evidence: { type: Array, default: () => [] } })
const emit = defineEmits(['updated'])
const generating = ref(false)
const canGenerate = computed(() => ['READY_FOR_REPORT', 'BLOCKED', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(props.runStatus))
const reportId = ref('')
const reportOptions = computed(() => props.reports.map(r => ({ value: r.report_id, label: `v${r.version} · ${{ FULL_INVESTIGATION: '完整调查报告', INVESTIGATION_STATUS: '调查状态报告' }[r.report_type] || r.report_type}`, description: label(r.report_type), status: r.release_status ? label(r.release_status) : '待评估', detail: r.report_id })))
const detail = ref(null)
const detailLoading = ref(false)
const citations = ref([])
const quantData = ref(null)
const error = ref('')
const citation = ref(null)
const citationLoading = ref(false)
const dialog = ref(null)
const reportRoot = ref(null)
const reportVersionContent = ref(null)
const reportBody = ref(null)
const progressFill = ref(null)
const readingProgress = ref(0)
const activeSectionId = ref('')
const previewCitationId = ref('')
const previewStyle = ref({})
const citationPreviews = ref({})
const previewErrors = ref({})
let version = 0
let citationVersion = 0
let previewVersion = 0
let previewTimer = null
let previewAnchor = null
let previewFrame = null
let progressTrigger = null
let sectionRevealTriggers = []
let sectionRevealTweens = []
let sectionRevealNodes = []
let scrollFrame = null
let motionPreference = null
let prefersReducedMotion = false
let reportOpeningTween = null
let reportOpened = false

const titles = { EXECUTIVE_SUMMARY: '结论速览', SCOPE_AND_MANDATE: '调查范围与目标', INVESTIGATION_QUESTIONS: '调查问题', METHODOLOGY: '调查方法', SOURCE_COVERAGE: '证据基础', TIMELINE: '事件时间线', VERIFIED_FINDINGS: '已验证发现', PROBABLE_FINDINGS: '可能成立的发现', DISPUTED_FINDINGS: '争议发现', QUANTITATIVE_FINDINGS: '量化发现', IMPACT_SCOPE_AND_ANALYSIS: '影响范围', CAUSAL_AND_MECHANISM_ANALYSIS: '原因与机制', ACTOR_AND_ATTRIBUTION_ASSESSMENT: '参与方与责任', CONFLICT_ANALYSIS: '冲突分析', REMEDIATION_AND_FOLLOW_UP: '应对与后续行动', LIMITATIONS_AND_RESEARCH_GAPS: '局限与后续建议', CONCLUSIONS_AND_NEXT_STEPS: '结论与下一步', EXECUTIVE_STATUS: '结论速览', SEARCH_AND_SOURCE_SUMMARY: '证据基础', AVAILABLE_FINDINGS: '核心发现', BLOCKING_GAPS_AND_LIMITATIONS: '局限与后续建议', NEXT_STEPS: '下一步', CORE_FINDINGS: '核心发现与分析', EVIDENCE_BASE: '证据基础', RESEARCH_APPENDIX: '调查问题与方法', TECHNICAL_APPENDIX: '技术诊断与方法说明' }
const presentedSections = computed(() => partitionReportSections(detail.value?.sections))
const bodySections = computed(() => presentedSections.value.body)
const appendixSections = computed(() => presentedSections.value.appendices)
const safeUrl = value => /^https?:\/\//i.test(value || '') ? value : undefined
const sourceDomain = value => { try { return new URL(value).hostname.replace(/^www\./, '') } catch { return '来源地址未记录' } }
const validationClass = value => ({ VERIFIED: 'verified', PROBABLE: 'probable', DISPUTED: 'disputed' }[value] || 'unverified')
const refs = (section, unit) => citations.value.filter(c => c.section_key === section && c.unit_key === unit)
const firstUnitKey = computed(() => {
  for (const section of [...bodySections.value, ...appendixSections.value]) {
    const unit = section.content?.units?.[0]
    if (unit) return `${section.section_id}:${unit.unit_key}`
  }
  return ''
})
const isFirstUnit = (section, unit) => firstUnitKey.value === `${section.section_id}:${unit.unit_key}`
const sectionNumber = index => String(index + 1).padStart(2, '0')
const sectionLabel = index => `SECTION ${sectionNumber(index)}`
const sectionScrollOffset = () => {
  const styles = getComputedStyle(document.documentElement)
  return Number.parseFloat(styles.getPropertyValue('--active-header-offset'))
    + Number.parseFloat(styles.getPropertyValue('--space-8'))
    + Number.parseFloat(styles.getPropertyValue('--space-1')) / 4
}

async function generate() {
  if (generating.value || !canGenerate.value) return
  generating.value = true
  error.value = ''
  try {
    const result = await request('/runs/' + props.runId + '/reports', { method: 'POST', body: JSON.stringify({ report_type: props.runStatus === 'READY_FOR_REPORT' ? 'FULL_INVESTIGATION' : 'INVESTIGATION_STATUS' }) })
    emit('updated')
    reportId.value = result.report.report_id
  } catch (e) { error.value = e.message }
  finally { generating.value = false }
}

function snapshotId() {
  return citation.value?.evidence?.snapshot_id || props.evidence.find(e => e.evidence_id === citation.value?.evidence?.evidence_id)?.snapshot_id
}

function destroyReportScroll() {
  if (scrollFrame !== null) window.cancelAnimationFrame(scrollFrame)
  scrollFrame = null
  progressTrigger?.kill()
  progressTrigger = null
  if (progressFill.value) gsap.killTweensOf(progressFill.value)
  destroySectionReveal(true)
}

function destroySectionReveal(showFinal = false) {
  sectionRevealTriggers.forEach(trigger => trigger.kill())
  sectionRevealTweens.forEach(tween => tween.kill())
  sectionRevealTriggers = []
  sectionRevealTweens = []
  if (sectionRevealNodes.length) {
    gsap.killTweensOf(sectionRevealNodes)
    if (showFinal) gsap.set(sectionRevealNodes, { opacity: 1, clearProps: 'willChange' })
  }
  sectionRevealNodes = []
}

function createSectionReveal() {
  destroySectionReveal(true)
  sectionRevealNodes = reportBody.value ? [...reportBody.value.querySelectorAll('.report-section-heading')] : []
  if (!sectionRevealNodes.length || prefersReducedMotion) {
    if (sectionRevealNodes.length) gsap.set(sectionRevealNodes, { opacity: 1 })
    return
  }
  gsap.set(sectionRevealNodes, { opacity: tokenNumber('--motion-emphasis-opacity'), willChange: 'opacity' })
  sectionRevealTriggers = ScrollTrigger.batch(sectionRevealNodes, {
    start: `top ${tokenValue('--scroll-trigger-start')}`,
    once: true,
    onEnter: batch => {
      const tween = gsap.to(batch, {
        opacity: 1,
        duration: tokenDuration('--dur-section'),
        stagger: tokenNumber('--motion-stagger-fast'),
        ease: tokenEase('--ease-gsap-reveal'),
        onComplete: () => gsap.set(batch, { clearProps: 'willChange' })
      })
      sectionRevealTweens.push(tween)
    }
  })
}

function playReportOpening() {
  if (reportOpened || !reportVersionContent.value) return
  reportOpened = true
  reportOpeningTween?.kill()
  if (prefersReducedMotion) {
    gsap.set(reportVersionContent.value, { opacity: 1, y: 0, clearProps: 'transform' })
    return
  }
  reportOpeningTween = gsap.fromTo(
    reportVersionContent.value,
    { opacity: 0, y: tokenLength('--motion-distance-folio') },
    {
      opacity: 1,
      y: 0,
      duration: tokenDuration('--dur-folio-open'),
      ease: tokenEase('--ease-gsap-reveal'),
      onComplete: () => gsap.set(reportVersionContent.value, { clearProps: 'opacity,transform' })
    }
  )
}

function handleReportEntered() {
  scheduleReportScroll()
  playReportOpening()
}

function scheduleReportScroll() {
  if (scrollFrame !== null) window.cancelAnimationFrame(scrollFrame)
  scrollFrame = window.requestAnimationFrame(() => {
    scrollFrame = null
    initReportScroll()
  })
}

function updateActiveSection(sections) {
  const offset = sectionScrollOffset()
  const active = sections.filter(section => section.getBoundingClientRect().top <= offset).at(-1) || sections[0]
  activeSectionId.value = active?.id || ''
}

function initReportScroll() {
  destroyReportScroll()
  const body = reportBody.value
  const progress = progressFill.value
  if (!body || !progress) return

  const sections = [...body.querySelectorAll('[data-report-section]')]
  activeSectionId.value = sections[0]?.id || ''
  readingProgress.value = 0
  gsap.set(progress, { scaleX: 0, transformOrigin: 'left center' })
  progressTrigger = ScrollTrigger.create({
    trigger: body,
    start: 'top top',
    end: 'bottom bottom',
    onUpdate: self => {
      readingProgress.value = Math.round(self.progress * 100)
      gsap.set(progress, { scaleX: self.progress })
      updateActiveSection(sections)
    }
  })
  ScrollTrigger.refresh()
  updateActiveSection(sections)
  createSectionReveal()
}

function scrollToSection(sectionId) {
  const section = reportBody.value?.querySelector(`#${CSS.escape(sectionId)}`)
  if (!section) return
  activeSectionId.value = sectionId
  section.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth', block: 'start' })
}

async function load(id) {
  const ticket = ++version
  destroyReportScroll()
  detail.value = null
  citations.value = []
  quantData.value = null
  detailLoading.value = Boolean(id)
  error.value = ''
  if (!id) {
    detailLoading.value = false
    return
  }
  try {
    const [report, links] = await Promise.all([request('/reports/' + id), request('/reports/' + id + '/citations')])
    if (ticket !== version) return
    detail.value = report
    citations.value = links
    if (report.report?.schema_version === 'quant-report-v2' && props.runId) {
      const quant = await request('/quant/runs/' + props.runId)
      if (ticket === version && quant.report_id === id) quantData.value = quant
    }
  } catch (e) { if (ticket === version) error.value = e.message }
  finally { if (ticket === version) detailLoading.value = false }
}

function hideCitationPreview() {
  if (previewTimer !== null) window.clearTimeout(previewTimer)
  previewTimer = null
  previewCitationId.value = ''
  previewAnchor = null
  previewStyle.value = {}
  previewVersion++
}

function positionCitationPreview() {
  if (!previewAnchor?.isConnected) return
  const preview = previewAnchor.querySelector('.citation-preview')
  if (!preview) return
  const anchorBounds = previewAnchor.getBoundingClientRect()
  const margin = tokenLength('--space-3')
  const gap = tokenLength('--space-2')
  const previewWidth = preview.offsetWidth
  const previewHeight = preview.offsetHeight
  const left = Math.min(Math.max(anchorBounds.left + anchorBounds.width / 2 - previewWidth / 2, margin), window.innerWidth - previewWidth - margin)
  const above = anchorBounds.top - previewHeight - gap
  const top = above >= margin ? above : anchorBounds.bottom + gap
  previewStyle.value = { left: `${left}px`, top: `${top}px` }
}

function scheduleCitationPosition() {
  if (previewFrame !== null || !previewCitationId.value) return
  previewFrame = window.requestAnimationFrame(() => {
    previewFrame = null
    positionCitationPreview()
  })
}

function showCitationPreview(id, anchor) {
  hideCitationPreview()
  previewAnchor = anchor
  const ticket = ++previewVersion
  previewTimer = window.setTimeout(async () => {
    previewTimer = null
    previewCitationId.value = id
    await nextTick()
    positionCitationPreview()
    if (citationPreviews.value[id] || previewErrors.value[id]) return
    try {
      const result = await request('/citations/' + id)
      if (ticket === previewVersion) citationPreviews.value = { ...citationPreviews.value, [id]: result }
    } catch {
      if (ticket === previewVersion) previewErrors.value = { ...previewErrors.value, [id]: true }
    }
  }, tokenDuration('--delay-citation-preview') * 1000)
}

async function openCitation(id) {
  hideCitationPreview()
  const ticket = ++citationVersion
  citation.value = null
  citationLoading.value = true
  error.value = ''
  openDialog(dialog.value, prefersReducedMotion)
  try {
    const result = await request('/citations/' + id)
    if (ticket === citationVersion) citation.value = result
  } catch (e) { if (ticket === citationVersion) error.value = e.message }
  finally { if (ticket === citationVersion) citationLoading.value = false }
}

function handleCitationClosed() {
  citationVersion++
  citationLoading.value = false
  clearDialogMotion(dialog.value)
}

function closeCitationDialog() {
  closeDialog(dialog.value, prefersReducedMotion)
}

function handleMotionPreference(event) {
  prefersReducedMotion = event.matches
  if (prefersReducedMotion) {
    clearDialogMotion(dialog.value, true)
    reportOpeningTween?.kill()
    if (reportVersionContent.value) gsap.set(reportVersionContent.value, { opacity: 1, y: 0, clearProps: 'transform' })
    destroySectionReveal(true)
  }
  else createSectionReveal()
}

watch(() => props.reports.map(r => r.report_id).join(','), () => {
  if (!props.reports.some(r => r.report_id === reportId.value)) reportId.value = props.reports[0]?.report_id || ''
}, { immediate: true })
watch(reportId, load, { immediate: true })
watch(detail, async value => {
  if (!value) return
  await nextTick()
  scheduleReportScroll()
})

onMounted(async () => {
  motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
  prefersReducedMotion = motionPreference.matches
  motionPreference.addEventListener('change', handleMotionPreference)
  window.addEventListener('resize', scheduleCitationPosition, { passive: true })
  window.addEventListener('scroll', scheduleCitationPosition, true)
  if (detail.value) {
    await nextTick()
    scheduleReportScroll()
  }
})

onUnmounted(() => {
  version++
  citationVersion++
  previewVersion++
  if (previewTimer !== null) window.clearTimeout(previewTimer)
  if (previewFrame !== null) window.cancelAnimationFrame(previewFrame)
  motionPreference?.removeEventListener('change', handleMotionPreference)
  window.removeEventListener('resize', scheduleCitationPosition)
  window.removeEventListener('scroll', scheduleCitationPosition, true)
  clearDialogMotion(dialog.value)
  reportOpeningTween?.kill()
  if (reportVersionContent.value) gsap.killTweensOf(reportVersionContent.value)
  destroyReportScroll()
})
</script>

<template>
  <section ref="reportRoot" class="report-detail">
    <div v-if="runId && canGenerate" class="row report-toolbar">
      <p class="muted">按当前证据生成中文详版，保留旧版与原始引用，不重新联网调查。</p>
      <button class="btn btn-primary" :disabled="generating" @click="generate">{{ generating ? '正在生成…' : '生成新版报告' }}</button>
    </div>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <div v-if="!reports.length" class="empty report-empty">
      <span class="empty-icon" aria-hidden="true">◇</span>
      <h3>尚未生成报告</h3>
      <p>调查运行结束后，可在此查看报告正文、引用溯源与发布门禁。</p>
    </div>
    <template v-else>
      <div class="row report-toolbar">
        <FolioSelect v-model="reportId" label="报告版本" :options="reportOptions" />
        <a class="button" :href="'/api/reports/' + encodeURIComponent(reportId) + '/export?format=markdown'" download>导出 Markdown</a>
      </div>

      <div v-if="detail" class="reading-progress" role="progressbar" aria-label="报告阅读进度" :aria-valuenow="readingProgress" aria-valuemin="0" aria-valuemax="100">
        <span ref="progressFill" class="reading-progress-fill"></span>
      </div>

      <Transition name="report-version" mode="out-in" @after-enter="handleReportEntered">
        <div v-if="detail" :key="detail.report.report_id" ref="reportVersionContent" class="report-version-content">
          <div class="report-meta-row">
            <span class="badge probable">第 {{ detail.report.version }} 版</span>
            <span class="badge unverified">{{ label(detail.report.report_type) }}</span>
            <span class="badge" :class="detail.report.release_status === 'RELEASED' ? 'verified' : 'unverified'">{{ label(detail.report.release_status) }}</span>
            <span class="badge" :class="detail.report.review_status === 'APPROVED' ? 'verified' : 'unverified'">{{ label(detail.report.review_status) }}</span>
            <span class="report-meta-note">导出不会改变发布状态</span>
          </div>

          <label class="report-outline-mobile">报告目录
            <select :value="activeSectionId" @change="scrollToSection($event.target.value)">
              <option v-for="(s, index) in bodySections" :key="s.section_id" :value="'report-' + s.section_id">{{ sectionLabel(index) }} · {{ titles[s.section_type] || label(s.section_type) }}</option>
            </select>
          </label>

          <div class="report-layout">
            <aside class="report-outline-desktop" aria-label="报告目录">
              <span class="outline-kicker">报告目录</span>
              <nav>
                <a v-for="(s, index) in bodySections" :key="s.section_id" :href="'#report-' + s.section_id" :class="{ active: activeSectionId === 'report-' + s.section_id }" :aria-current="activeSectionId === 'report-' + s.section_id ? 'location' : undefined" @click.prevent="scrollToSection('report-' + s.section_id)"><span>{{ sectionLabel(index) }}</span>{{ titles[s.section_type] || label(s.section_type) }}</a>
              </nav>
            </aside>

            <main ref="reportBody" class="report-prose">
              <article v-for="(s, sectionIndex) in bodySections" :id="'report-' + s.section_id" :key="s.section_id" class="report-section" data-report-section>
                <header class="report-section-heading">
                  <span>{{ sectionLabel(sectionIndex) }}</span>
                  <h2>{{ titles[s.section_type] || s.section_type }}</h2>
                  <i aria-hidden="true"></i>
                </header>
                <p v-for="unit in s.content?.units || []" :key="unit.unit_key" :class="{ 'report-lead': isFirstUnit(s, unit) }">
                  {{ unit.text }}
                  <span v-for="c in refs(s.section_type, unit.unit_key)" :key="c.citation_id" class="citation-anchor" @mouseenter="showCitationPreview(c.citation_id, $event.currentTarget)" @mouseleave="hideCitationPreview" @focusin="showCitationPreview(c.citation_id, $event.currentTarget)" @focusout="hideCitationPreview">
                    <button class="citation-link" :aria-label="`查看引用 ${c.display_ordinal + 1}`" @click="openCitation(c.citation_id)">[{{ c.display_ordinal + 1 }}]</button>
                    <span v-if="previewCitationId === c.citation_id" class="citation-preview" role="tooltip" :style="previewStyle">
                      <template v-if="citationPreviews[c.citation_id]">
                        <span class="citation-preview-source">
                          <span class="citation-favicon" aria-hidden="true">
                            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="6.25" /><path d="M1.75 8h12.5M8 1.75c1.5 1.7 2.25 3.78 2.25 6.25S9.5 12.55 8 14.25C6.5 12.55 5.75 10.47 5.75 8S6.5 3.45 8 1.75Z" /></svg>
                          </span>
                          <small>{{ sourceDomain(citationPreviews[c.citation_id].source?.canonical_url) }}</small>
                        </span>
                        <strong>{{ chineseText(citationPreviews[c.citation_id].source?.title) || '来源不可用' }}</strong>
                        <q>{{ citationPreviews[c.citation_id].evidence?.exact_quote || citationPreviews[c.citation_id].evidence?.excerpt || '原文片段不可用' }}</q>
                      </template>
                      <span v-else-if="previewErrors[c.citation_id]">预览不可用，点击查看完整溯源。</span>
                      <span v-else>正在读取引用来源…</span>
                    </span>
                  </span>
                </p>
                <QuantReportSection v-if="s.section_type === 'QUANTITATIVE_FINDINGS' && quantData" :data="quantData" />
              </article>
              <details v-if="appendixSections.length" class="report-appendices">
                <summary>附录与技术说明 <span>{{ appendixSections.length }} 项</span></summary>
                <section v-for="s in appendixSections" :id="'report-' + s.section_id" :key="s.section_id" class="report-appendix-section">
                  <header class="report-appendix-heading"><h2>{{ titles[s.section_type] || label(s.section_type) }}</h2></header>
                  <p v-for="unit in s.content?.units || []" :key="unit.unit_key">
                    {{ unit.text }}
                    <span v-for="c in refs(s.section_type, unit.unit_key)" :key="c.citation_id" class="citation-anchor"><button class="citation-link" :aria-label="`查看引用 ${c.display_ordinal + 1}`" @click="openCitation(c.citation_id)">[{{ c.display_ordinal + 1 }}]</button></span>
                  </p>
                </section>
              </details>
            </main>
          </div>
          <details class="report-integrity"><summary>报告完整性标识</summary><p class="muted">{{ detail.report.report_hash }}</p></details>
          <ReviewPanel v-if="showReview" :key="reportId" :report-id="reportId" @updated="load(reportId)" />
        </div>

        <div v-else-if="detailLoading" :key="'loading-' + reportId" class="report-skeleton" role="status" aria-label="正在加载报告">
          <span class="skeleton skeleton-shimmer report-skeleton-kicker">正在加载版本信息</span>
          <span class="skeleton skeleton-shimmer report-skeleton-title">正在加载报告标题</span>
          <span v-for="index in 5" :key="index" class="skeleton skeleton-shimmer report-skeleton-copy">正在加载报告正文</span>
        </div>

        <div v-else :key="'unavailable-' + reportId" class="empty report-empty">
          <span class="empty-icon" aria-hidden="true">◇</span><h3>报告暂时不可用</h3><p>请稍后重试，或选择其他历史版本。</p>
        </div>
      </Transition>
    </template>

    <dialog ref="dialog" class="citation-dialog" aria-labelledby="citation-title" @cancel.prevent="closeCitationDialog" @close="handleCitationClosed">
      <div class="citation-dialog-header"><div><span class="dialog-kicker">Evidence provenance</span><h2 id="citation-title">引用溯源</h2></div><button class="quiet-button" @click="closeCitationDialog">关闭</button></div>
      <div v-if="citationLoading" class="citation-dialog-skeleton" role="status">
        <span class="skeleton skeleton-shimmer"></span><span class="skeleton skeleton-shimmer"></span><span class="skeleton skeleton-shimmer"></span>
      </div>
      <p v-if="error" class="notice error">{{ error }}</p>
      <template v-if="citation">
        <div class="citation-claim"><span class="badge evidence-stamp" :class="validationClass(citation.claim?.validation_status)">{{ label(citation.claim?.validation_status) }}</span><h3>{{ chineseText(citation.claim?.statement) }}</h3><p>{{ validationExplanation(citation.claim) }}</p></div>
        <div v-if="citation.evidence?.locator_type !== 'COMPUTATION_CELL'" class="citation-source-meta"><div><span class="dialog-kicker">来源</span><a :href="safeUrl(citation.source?.canonical_url)" target="_blank" rel="noopener noreferrer">{{ chineseText(citation.source?.title) || '来源不可用' }}</a><small>{{ sourceDomain(citation.source?.canonical_url) }}</small></div><p>{{ chineseText(citation.source?.publisher) }}<br>发布时间 {{ citation.source?.published_at || '未记录' }}<br>采集时间 {{ citation.source?.retrieved_at || '未记录' }}</p></div>
        <span class="dialog-kicker">{{ citation.evidence?.locator_type === 'COMPUTATION_CELL' ? '冻结计算单元格（不是网页引文）' : '证据原文（保留来源语言）' }}</span>
        <blockquote>{{ citation.evidence?.exact_quote || citation.evidence?.excerpt || '证据原文不可用' }}</blockquote>
        <p v-if="snapshotId() && citation.evidence?.locator_type !== 'COMPUTATION_CELL'"><a :href="'/api/snapshots/' + encodeURIComponent(snapshotId()) + '?format=cleaned'" target="_blank" rel="noopener">打开完整归档正文</a></p>
        <details v-if="citation.evidence?.locator_type === 'COMPUTATION_CELL'"><summary>数值、口径与 cell hash</summary><pre>{{ JSON.stringify(citation.evidence.locator_payload, null, 2) }}</pre></details>
        <details><summary>定位与引用标识</summary><pre>{{ JSON.stringify(citation.citation.canonical_locator, null, 2) }}</pre><p class="muted">{{ citation.citation.citation_hash }}</p></details>
      </template>
    </dialog>
  </section>
</template>

<style scoped>
.report-detail { position: relative; }
.report-toolbar { align-items: flex-end; margin-block: var(--space-5); }
.report-toolbar .folio-select { flex: 1 1 calc(var(--space-32) + var(--space-32) + var(--space-16)); }
.report-toolbar > a { margin-bottom: var(--space-1); flex-shrink: 0; }
.reading-progress { position: sticky; z-index: 3; top: var(--topbar-height); height: calc(var(--space-1) / 2); overflow: hidden; border-radius: var(--radius-full); background: var(--border-default); }
.reading-progress-fill { display: block; width: 100%; height: 100%; border-radius: inherit; background: var(--accent); transform: scaleX(0); transform-origin: left center; }
.report-meta-row { display: flex; align-items: center; gap: var(--space-2); margin-block: var(--space-6); flex-wrap: wrap; }
.report-meta-note { margin-left: auto; color: var(--text-muted); font-size: var(--font-size-caption); line-height: var(--line-height-caption); }
.report-layout { display: grid; grid-template-columns: calc(var(--space-32) + var(--space-16) + var(--space-4)) minmax(0, 1fr); align-items: start; gap: var(--space-8); }
.report-outline-desktop { position: sticky; top: calc(var(--topbar-height) + var(--space-6)); max-height: calc(100vh - var(--topbar-height) - var(--space-12)); padding-right: var(--space-4); overflow-y: auto; }
.outline-kicker, .dialog-kicker, .report-section-heading > span { display: block; color: var(--text-muted); font-family: var(--font-sans); font-size: var(--font-size-overline); font-weight: var(--font-weight-overline); letter-spacing: var(--letter-spacing-overline); line-height: var(--line-height-overline); }
.report-outline-desktop nav { display: grid; gap: var(--space-1); margin-top: var(--space-4); }
.report-outline-desktop a { display: grid; grid-template-columns: calc(var(--space-20) + var(--space-3)) minmax(0, 1fr); gap: var(--space-2); padding: var(--space-2) var(--space-3); border-left: calc(var(--space-1) / 2) solid transparent; border-radius: 0 var(--radius-sm) var(--radius-sm) 0; color: var(--text-muted); font-size: var(--font-size-small); line-height: var(--line-height-small); text-decoration: none; transition: color var(--dur-sm) var(--ease-standard), border-color var(--dur-sm) var(--ease-standard), background var(--dur-sm) var(--ease-standard); }
.report-outline-desktop a span { color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-size-caption); }
.report-outline-desktop a:hover, .report-outline-desktop a.active { border-left-color: var(--accent); background: var(--accent-subtle); color: var(--text-primary); }
.report-outline-mobile { display: none; }
.report-prose { width: 100%; min-width: 0; max-width: var(--reading-max-width); margin-inline: auto; font-family: var(--font-serif); }
.report-section { max-width: none; margin: 0 0 var(--space-20); scroll-margin-top: calc(var(--topbar-height) + var(--space-8)); }
.report-section-heading { display: grid; gap: var(--space-2); margin-bottom: var(--space-8); padding-top: var(--space-4); }
.report-section-heading h2 { margin: 0; padding: 0; border: 0; color: var(--text-primary); font-size: var(--font-size-section); font-weight: var(--font-weight-section); letter-spacing: var(--letter-spacing-section); line-height: var(--line-height-section); }
.report-section-heading i { display: block; width: 100%; height: calc(var(--space-1) / 4); background: var(--border-default); }
.report-section p { margin: 0; padding-block: var(--paragraph-spacing); color: var(--text-secondary); font-family: var(--font-serif); font-size: var(--font-size-body-lg); line-height: var(--line-height-body-lg); overflow-wrap: anywhere; text-wrap: pretty; }
.report-section .report-insufficient { color: var(--text-muted); font-family: var(--font-sans); font-size: var(--font-size-small); line-height: var(--line-height-small); }
.report-appendices { margin-block: var(--space-8) var(--space-16); border-block: calc(var(--space-1) / 4) solid var(--border-default); }
.report-appendices > summary { display: flex; min-height: var(--touch-target); align-items: center; justify-content: space-between; gap: var(--space-4); padding-block: var(--space-4); color: var(--text-primary); font-family: var(--font-display); font-size: var(--font-size-h3); cursor: pointer; }
.report-appendices > summary span { color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-size-caption); }
.report-appendix-section { padding-block: var(--space-5); border-top: calc(var(--space-1) / 4) solid var(--border-default); }
.report-appendix-heading h2 { margin: 0 0 var(--space-3); color: var(--text-primary); font-family: var(--font-display); font-size: var(--font-size-h3); line-height: var(--line-height-h3); }
.report-lead::first-letter { float: left; margin: 0 var(--space-2) 0 0; color: var(--accent); font-size: var(--font-size-drop-cap); font-weight: var(--font-weight-h1); line-height: var(--line-height-display-xl); }
.citation-anchor { position: relative; display: inline-block; }
.citation-preview { position: fixed; z-index: var(--z-preview); display: grid; width: calc(var(--space-32) * 2 + var(--space-16)); max-width: calc(100vw - var(--space-6)); gap: var(--space-2); padding: var(--space-3); border: calc(var(--space-1) / 4) solid var(--border-default); border-radius: var(--radius-md); background: var(--bg-elevated); color: var(--text-secondary); font-family: var(--font-sans); font-size: var(--font-size-caption); line-height: var(--line-height-caption); box-shadow: var(--shadow-soft); pointer-events: none; }
.citation-preview-source { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.citation-favicon { position: relative; display: grid; width: var(--space-4); height: var(--space-4); flex: 0 0 var(--space-4); overflow: hidden; border: calc(var(--space-1) / 4) solid var(--border-default); border-radius: var(--radius-full); background: var(--bg-surface); color: var(--text-muted); place-items: center; }
.citation-favicon svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.citation-favicon svg { padding: calc(var(--space-1) / 2); }
.citation-preview strong { color: var(--text-primary); font-family: var(--font-display); font-size: var(--font-size-small); line-height: var(--line-height-small); }
.citation-preview small { overflow: hidden; color: var(--text-muted); font-family: var(--font-sans); text-overflow: ellipsis; white-space: nowrap; }
.citation-preview q { display: -webkit-box; overflow: hidden; color: var(--text-secondary); font-family: var(--font-serif); font-size: var(--font-size-small); line-height: var(--line-height-small); -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
.report-integrity { max-width: var(--reading-max-width); margin-inline: auto; }
.report-skeleton { display: grid; gap: var(--space-5); max-width: var(--reading-max-width); margin-inline: auto; padding-block: var(--space-12); }
.report-skeleton > span { display: block; }
.report-skeleton-kicker { width: var(--space-24); height: var(--space-3); }
.report-skeleton-title { width: calc(var(--space-32) + var(--space-32) + var(--space-20)); max-width: 100%; height: var(--space-8); }
.report-skeleton-copy { width: 100%; height: var(--space-16); }
.report-empty .empty-icon { display: grid; width: var(--space-12); height: var(--space-12); margin: 0; border: var(--stroke-thin) solid var(--border-strong); border-radius: var(--radius-sm); color: transparent; font-size: 0; place-items: center; }
.report-empty .empty-icon::before { width: var(--space-5); height: var(--space-3); border-block: var(--stroke-thin) solid var(--text-muted); content: ''; }
.report-version-enter-active, .report-version-leave-active { transition: opacity var(--dur-md) var(--ease-out-expo), transform var(--dur-md) var(--ease-out-expo); }
.report-version-enter-from { opacity: 0; transform: translateY(var(--space-2)); }
.report-version-leave-to { opacity: 0; transform: translateY(calc(var(--space-2) * -1)); }
.citation-dialog-header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); margin-bottom: var(--space-6); }
.citation-dialog-header h2 { margin: var(--space-1) 0 0; }
.citation-dialog-skeleton { display: grid; gap: var(--space-4); }
.citation-dialog-skeleton span { display: block; height: var(--space-12); }
.citation-claim { padding: var(--space-5); border-radius: var(--radius-lg); background: var(--bg-elevated); }
.evidence-stamp { border-radius: var(--radius-sm); background: transparent; font-family: var(--font-mono); letter-spacing: var(--letter-spacing-caption); transform: rotate(var(--stamp-rotation)); }
.citation-claim h3 { margin-block: var(--space-3); font-family: var(--font-display); font-size: var(--font-size-h3); line-height: var(--line-height-h3); }
.citation-source-meta { display: grid; grid-template-columns: minmax(0, 1fr) max-content; gap: var(--space-6); margin-block: var(--space-6); padding-block: var(--space-5); border-block: calc(var(--space-1) / 4) solid var(--border-default); }
.citation-source-meta div { display: grid; gap: var(--space-2); }
.citation-source-meta small { color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-size-caption); }
.citation-source-meta p { margin: 0; color: var(--text-muted); font-size: var(--font-size-caption); line-height: var(--line-height-body); text-align: right; }
.citation-dialog blockquote { border-radius: 0 var(--radius-md) var(--radius-md) 0; background: var(--bg-elevated); }

@media (width < 68.75rem) {
  .report-layout { display: block; }
  .report-outline-desktop { display: none; }
  .report-outline-mobile { display: block; margin-block: var(--space-6); }
  .report-prose { max-width: var(--reading-max-width); }
  .report-integrity { margin-inline: auto; }
}

@media (width < 48rem) {
  .reading-progress { top: var(--mobile-header-offset); }
  .report-section { scroll-margin-top: calc(var(--mobile-header-offset) + var(--space-8)); }
  .report-toolbar { align-items: stretch; }
  .report-toolbar > *, .report-toolbar > a, .report-toolbar .folio-select { width: 100%; flex-basis: auto; }
  .report-meta-note { width: 100%; margin-left: 0; }
  .report-outline-mobile select { min-height: var(--touch-target); }
  .citation-source-meta { grid-template-columns: 1fr; gap: var(--space-4); }
  .citation-source-meta p { text-align: left; }
}

@media (prefers-reduced-motion: reduce) {
  .report-version-enter-active, .report-version-leave-active { transition: none; }
  .report-version-enter-from, .report-version-leave-to { opacity: 1; transform: none; }
}
</style>
