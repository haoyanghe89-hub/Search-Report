<script setup>
import { label, chineseText, validationExplanation } from '../composables/chinese.js'
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { clearDialogMotion, closeDialog, openDialog } from '../utils/dialogMotion.js'
import { tokenDuration, tokenEase, tokenLength, tokenNumber, tokenValue } from '../utils/motionTokens.js'
import { useInvestigation } from '../composables/useInvestigation.js'
import request from '../api/request.js'
import RunProgress from '../components/RunProgress.vue'
import RunHistory from '../components/RunHistory.vue'
import RunRecovery from '../components/RunRecovery.vue'
import TopBar from '../components/TopBar.vue'
import AgentFlow from '../components/AgentFlow.vue'
import EvidenceChain from '../components/EvidenceChain.vue'
import SectionHeading from '../components/SectionHeading.vue'
import Timeline from '../components/Timeline.vue'
import ReviewPanel from '../components/ReviewPanel.vue'
import { projectAgents, verificationSummary, resultsPending, runModeLabel, runStatusLabel, runFailureLabel } from '../composables/presentation.js'
import ReportDetail from '../components/ReportDetail.vue'

gsap.registerPlugin(ScrollTrigger)

const props = defineProps({ investigationId: { type: String, required: true }, replaying: Boolean })
const emit = defineEmits(['updated', 'replay', 'new-investigation'])
const { detail, runs, runId, run, budget, workers, quant, data, loading, starting, error, running, load, loadRun, refreshReports, start, cancel } = useInvestigation(props.investigationId)
const pending = computed(() => resultsPending({ replaying: props.replaying, starting: starting.value, running: running.value, loading: loading.value }))
const resultsVisible = ref(!pending.value)
const recoveryBusy = ref(false)
const showRecovery = computed(() => run.value?.mode === 'LIVE' && ['INTERRUPTED', 'CANCELLED', 'FAILED', 'BLOCKED', 'TIMED_OUT'].includes(run.value?.status))
async function resumed() { await loadRun(); emit('updated') }
const tab = ref('overview')
const tabs = [['overview', '概览'], ['agents', '智能体流程'], ['sources', '来源'], ['evidence', '证据'], ['claims', '声明'], ['conflicts', '冲突与缺口'], ['timeline', '时间线'], ['report', '报告'], ['review', '审核']]
const listTabs = new Set(['sources', 'evidence', 'claims', 'conflicts'])
const query = ref('')
const selectedEvidence = ref('')
const filtered = computed(() => Object.fromEntries(['sources', 'evidence', 'claims'].map(key => [key, data.value[key].filter(x => JSON.stringify(x).toLowerCase().includes(query.value.toLowerCase()))])))
const visibleEvidence = computed(() => filtered.value.evidence.filter(x => !selectedEvidence.value || x.evidence_id === selectedEvidence.value))
const showListSkeleton = computed(() => loading.value && !running.value && !starting.value && !props.replaying)
const source = id => data.value.sources.find(x => x.source_id === id)
const claim = id => data.value.claims.find(x => x.claim_id === id)
const date = value => value ? new Date(value).toLocaleString('zh-CN') : '未记录'
const modeLabel = runModeLabel
const snapshotUrl = id => '/api/snapshots/' + encodeURIComponent(id) + '?format=cleaned'
const safeUrl = value => /^https?:\/\//i.test(value || '') ? value : undefined
const sourceDomain = value => { try { return new URL(value).hostname.replace(/^www\./, '') } catch { return '来源地址未记录' } }
const validationClass = value => ({ VERIFIED: 'verified', PROBABLE: 'probable', DISPUTED: 'disputed' }[value] || 'unverified')
const eligibilityClass = value => value === true ? 'verified' : value === false ? 'disputed' : 'unverified'
const relationClass = relation => relation.stance === 'SUPPORTS' ? 'verified' : relation.stance === 'CONTRADICTS' ? 'disputed' : relation.entailment_status === 'ENTAILED' ? 'probable' : 'unverified'
const severityClass = value => value === 'HIGH' ? 'disputed' : value === 'MEDIUM' ? 'probable' : 'unverified'
const confidencePercent = value => value == null ? 0 : Math.round(Number(value) * 100)
const folioLabel = (kind, index) => `${kind} ${String(index + 1).padStart(2, '0')}`
function viewEvidence(id) { selectedEvidence.value = id; query.value = ''; tab.value = 'evidence' }
async function launch() {
  if (run.value?.workflow_version === 'quant-v1') { emit('new-investigation'); return }
  await start(); emit('updated')
}
const agents = computed(() => projectAgents(data.value.steps))
const verification = computed(() => verificationSummary(data.value.claims))
const heroStatus = computed(() => {
  if (props.replaying) return { label: '正在回放', tone: 'probable' }
  if (starting.value) return { label: '正在启动', tone: 'probable' }
  if (loading.value && !run.value) return { label: '正在读取', tone: 'probable' }

  const status = run.value?.status
  if (run.value?.workflow_version === 'quant-v1') return { label: status === 'COMPLETED' ? '报告已成稿' : quant.value?.phase || '量化运行中', tone: 'unverified' }
  const tone = ['READY_FOR_REPORT', 'COMPLETED', 'SUCCEEDED'].includes(status)
    ? 'verified'
    : ['FAILED', 'CANCELLED', 'TIMED_OUT', 'BLOCKED', 'INTERRUPTED'].includes(status)
      ? 'disputed'
      : ['CREATED', 'PENDING', 'WAITING_FOR_EXECUTION', 'RUNNING', 'VERIFYING'].includes(status)
        ? 'probable'
        : 'unverified'
  return { label: runStatusLabel(status) || '尚未运行', tone }
})
const heroTitle = computed(() => chineseText(detail.value?.title) || '正在读取调查…')
const heroTitleSize = computed(() => {
  const length = [...heroTitle.value.trim()].length
  if (length <= tokenNumber('--hero-title-short-limit')) return 'lg'
  if (length <= tokenNumber('--hero-title-medium-limit')) return 'md'
  return 'sm'
})
const heroTitleParts = computed(() => {
  const text = heroTitle.value.trim()
  if (!text) return []
  const segments = typeof Intl.Segmenter === 'function'
    ? [...new Intl.Segmenter('zh-CN', { granularity: 'word' }).segment(text)].map(item => item.segment)
    : [...text]
  const groupCount = Math.min(5, Math.max(1, Math.ceil(text.length / 5)))
  const targetLength = Math.ceil(text.length / groupCount)
  const groups = []
  let group = ''
  segments.forEach(segment => {
    if (group && group.length + segment.length > targetLength && groups.length < groupCount - 1) {
      groups.push(group)
      group = ''
    }
    group += segment
  })
  if (group) groups.push(group)
  return groups
})
const reportPreview = ref(null)
let reportPreviewVersion = 0
const executiveSummarySentences = computed(() => {
  const section = reportPreview.value?.sections?.find(item => ['EXECUTIVE_SUMMARY', 'EXECUTIVE_STATUS'].includes(item.section_type))
  const units = section?.content?.units || []
  return units
    .flatMap(unit => String(unit.text || '').match(/[^。！？!?]+[。！？!?]?/g) || [])
    .map(sentence => chineseText(sentence.trim()))
    .filter(Boolean)
    .slice(0, 5)
})
const executiveSummary = computed(() => executiveSummarySentences.value.join(' '))

async function loadReportPreview(reportId) {
  const ticket = ++reportPreviewVersion
  reportPreview.value = null
  if (!reportId) return
  try {
    const result = await request('/reports/' + encodeURIComponent(reportId))
    if (ticket === reportPreviewVersion) reportPreview.value = result
  } catch {
    if (ticket === reportPreviewVersion) reportPreview.value = null
  }
}
const chain = computed(() => quant.value ? [
  { number: quant.value.input_snapshot_ids?.length || 0, label: '冻结快照', sub: '显式历史窗口' },
  { number: quant.value.evidence_count || 0, label: '计算证据', sub: '可定位单元格' },
  { number: data.value.claims.length, label: '量化观察', sub: `${verification.value.verified} 条已验证` },
  { number: data.value.reports.length, label: '投研报告', sub: '保留历史版本' },
] : [
  { number: data.value.sources.length, label: '信息来源', sub: '已记录来源' },
  { number: data.value.evidence.length, label: '证据摘录', sub: '保留原文定位' },
  { number: data.value.claims.length, label: '调查声明', sub: `${verification.value.verified} 条已验证` },
  { number: data.value.reports.length, label: '调查报告', sub: '保留历史版本' },
])
const timelinePreview = computed(() => data.value.timeline.slice(0, 5).map(e => ({ date: date(e.event_time), event: chineseText(e.description), description: label(e.validation_status) })))
const exportUrl = computed(() => !pending.value && data.value.reports[0] ? '/api/reports/' + encodeURIComponent(data.value.reports[0].report_id) + '/export?format=markdown' : '')
const searchDialog = ref(null)
const searchQuery = ref('')
const searchResults = computed(() => searchQuery.value.trim() ? ['sources', 'evidence', 'claims'].flatMap(key => data.value[key].map(x => ({ key, id: x.source_id || x.evidence_id || x.claim_id, text: x.statement || x.content || x.title }))).filter(x => x.text?.toLowerCase().includes(searchQuery.value.trim().toLowerCase())).slice(0, 40) : [])
function openSearch() { if (!pending.value) openDialog(searchDialog.value, prefersReducedMotion) }
function closeSearch() { closeDialog(searchDialog.value, prefersReducedMotion) }
function selectResult(result) { tab.value = result.key; query.value = searchQuery.value; selectedEvidence.value = ''; closeSearch() }
function shortcut(event) { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openSearch() } }
watch(pending, value => { if (value) { closeSearch(); tab.value = 'overview'; query.value = ''; selectedEvidence.value = '' } })
watch([pending, showListSkeleton], ([isPending], [wasPending, wasSkeleton]) => {
  if (isPending) resultsVisible.value = false
  else if (!(wasPending && !wasSkeleton)) resultsVisible.value = true
})

const hero = ref(null)
const tabNav = ref(null)
const tabIndicator = ref(null)
const overviewPanel = ref(null)
const listPanel = ref(null)
const resultsPanel = ref(null)
let heroRevealElements = []
let heroTitleElements = []
let heroTimeline = null
let motionPreference = null
let finePointerPreference = null
let prefersReducedMotion = false
let indicatorReady = false
let tabFrame = null
let overviewCountTrigger = null
let overviewCountTweens = []
let overviewCountStates = []
let overviewCountsPlayed = false
let listRevealTriggers = []
let listRevealTweens = []
let listRevealNodes = []
let runProgressLeaveTween = null
let runProgressLeaveDone = null
let resultsRevealTween = null

function closeRunProgress(element, done) {
  runProgressLeaveTween?.kill()
  runProgressLeaveDone?.()
  runProgressLeaveDone = done
  if (prefersReducedMotion) {
    runProgressLeaveDone = null
    resultsVisible.value = true
    done()
    return
  }
  runProgressLeaveTween = gsap.to(element, {
    opacity: 0,
    y: tokenLength('--motion-distance-live-close') * -1,
    scaleY: tokenNumber('--motion-live-close-scale'),
    transformOrigin: 'top center',
    duration: tokenDuration('--dur-live-close'),
    ease: tokenEase('--ease-gsap-standard'),
    overwrite: true,
    onComplete: () => {
      runProgressLeaveTween = null
      runProgressLeaveDone = null
      resultsVisible.value = true
      done()
    }
  })
}

function cancelRunProgressClose(element) {
  runProgressLeaveTween?.kill()
  runProgressLeaveTween = null
  runProgressLeaveDone = null
  gsap.set(element, { clearProps: 'opacity,transform' })
  resultsVisible.value = false
}

watch(resultsVisible, async visible => {
  resultsRevealTween?.kill()
  if (!visible) return
  await nextTick()
  const panel = resultsPanel.value
  if (!panel || prefersReducedMotion) return
  resultsRevealTween = gsap.fromTo(panel, { opacity: 0, y: tokenLength('--motion-distance-folio') }, {
    opacity: 1,
    y: 0,
    duration: tokenDuration('--dur-folio-open'),
    ease: tokenEase('--ease-gsap-reveal'),
    overwrite: true,
    clearProps: 'opacity,transform'
  })
})

function revealHero() {
  heroTitleElements = hero.value ? [...hero.value.querySelectorAll('[data-hero-title-part]')] : []
  heroRevealElements = hero.value ? [...hero.value.querySelectorAll('[data-hero-reveal]')] : []
  const animatedElements = [...heroTitleElements, ...heroRevealElements]
  if (!animatedElements.length) return

  heroTimeline?.kill()
  gsap.killTweensOf(animatedElements)
  if (prefersReducedMotion) {
    gsap.set(animatedElements, { opacity: 1, x: 0, y: 0, clearProps: 'transform,willChange' })
    return
  }

  const heroDuration = tokenDuration('--dur-hero')
  const secondaryDuration = tokenDuration('--dur-md')
  const secondaryDelay = tokenDuration('--motion-hero-secondary-delay')
  const distance = tokenLength('--motion-distance-hero')
  const stagger = tokenNumber('--motion-stagger-hero')
  const ease = tokenEase('--ease-gsap-reveal')
  gsap.set(animatedElements, { willChange: 'opacity, transform' })
  heroTimeline = gsap.timeline({
    onComplete: () => gsap.set(animatedElements, { clearProps: 'opacity,transform,willChange' })
  })
  heroTimeline.fromTo(
    heroTitleElements,
    { opacity: 0, y: distance },
    { opacity: 1, y: 0, duration: heroDuration, stagger, ease }
  )
  heroTimeline.fromTo(
    heroRevealElements,
    { opacity: 0, y: distance / 2 },
    { opacity: 1, y: 0, duration: secondaryDuration, stagger, ease },
    secondaryDelay
  )
}

function resetMagnetic(animate = true) {
  if (!hero.value) return
  const target = hero.value.querySelector('.hero-primary-action')
  if (!target) return
  gsap.killTweensOf(target)
  if (!animate || prefersReducedMotion) gsap.set(target, { x: 0, y: 0, clearProps: 'transform' })
  else gsap.to(target, { x: 0, y: 0, duration: tokenDuration('--dur-md'), ease: tokenEase('--ease-gsap-reveal'), overwrite: true, onComplete: () => gsap.set(target, { clearProps: 'transform' }) })
}

function moveMagnetic(event) {
  if (prefersReducedMotion || !finePointerPreference?.matches) return
  const target = event.currentTarget
  const bounds = target.getBoundingClientRect()
  const max = tokenLength('--motion-magnetic-max')
  const x = ((event.clientX - bounds.left) / bounds.width - 0.5) * max * 2
  const y = ((event.clientY - bounds.top) / bounds.height - 0.5) * max * 2
  gsap.to(target, { x, y, duration: tokenDuration('--dur-sm'), ease: tokenEase('--ease-gsap-reveal'), overwrite: true })
}

function moveTabIndicator(animate = true) {
  const nav = tabNav.value
  const indicator = tabIndicator.value
  const activeTab = nav?.querySelector(`[data-tab-key="${tab.value}"]`)
  if (!nav || !indicator || !activeTab) return

  gsap.killTweensOf(indicator)
  const target = { x: activeTab.offsetLeft, width: activeTab.offsetWidth }

  if (!animate || prefersReducedMotion) {
    gsap.set(indicator, target)
    return
  }

  gsap.to(indicator, {
    ...target,
    duration: tokenDuration('--dur-md'),
    ease: tokenEase('--ease-gsap-standard'),
    overwrite: true
  })
}

function scheduleTabIndicator() {
  if (tabFrame !== null) return
  tabFrame = window.requestAnimationFrame(() => {
    tabFrame = null
    moveTabIndicator(false)
  })
}

function overviewCountNodes() {
  return overviewPanel.value ? [...overviewPanel.value.querySelectorAll('[data-overview-count]')] : []
}

function showOverviewCountFinalState() {
  overviewCountNodes().forEach(node => {
    node.textContent = String(Number(node.dataset.overviewCount) || 0)
  })
}

function destroyOverviewCounts(showFinal = false) {
  overviewCountTrigger?.kill()
  overviewCountTrigger = null
  overviewCountTweens.forEach(tween => tween.kill())
  overviewCountTweens = []
  if (overviewCountStates.length) gsap.killTweensOf(overviewCountStates)
  overviewCountStates = []
  if (showFinal) showOverviewCountFinalState()
}

function createOverviewCounts() {
  destroyOverviewCounts()
  if (overviewCountsPlayed || tab.value !== 'overview' || !overviewPanel.value) return

  const nodes = overviewCountNodes()
  const populatedNodes = nodes.filter(node => Number(node.dataset.overviewCount) > 0)
  if (!populatedNodes.length) {
    showOverviewCountFinalState()
    return
  }

  if (prefersReducedMotion) {
    overviewCountsPlayed = true
    showOverviewCountFinalState()
    return
  }

  populatedNodes.forEach(node => { node.textContent = '0' })
  const triggerElement = overviewPanel.value.querySelector('.evidence-chain-section') || overviewPanel.value
  overviewCountTrigger = ScrollTrigger.create({
    trigger: triggerElement,
    start: `top ${tokenValue('--scroll-trigger-start')}`,
    once: true,
    onEnter: () => {
      overviewCountsPlayed = true
      overviewCountTweens = populatedNodes.map(node => {
        const target = Number(node.dataset.overviewCount)
        const state = { value: 0 }
        overviewCountStates.push(state)
        return gsap.to(state, {
          value: target,
          duration: tokenDuration('--dur-count'),
          snap: { value: 1 },
          ease: tokenEase('--ease-gsap-reveal'),
          onUpdate: () => { node.textContent = String(Math.round(state.value)) },
          onComplete: () => { node.textContent = String(target) }
        })
      })
    }
  })
}

function destroyListReveal(showFinal = false) {
  listRevealTriggers.forEach(trigger => trigger.kill())
  listRevealTriggers = []
  listRevealTweens.forEach(tween => tween.kill())
  listRevealTweens = []
  if (listRevealNodes.length) {
    gsap.killTweensOf(listRevealNodes)
    if (showFinal) gsap.set(listRevealNodes, { opacity: 1, y: 0, clearProps: 'transform' })
  }
  listRevealNodes = []
}

function createListReveal() {
  destroyListReveal(true)
  if (!listTabs.has(tab.value) || listPanel.value?.dataset.panel !== tab.value) return

  listRevealNodes = [...listPanel.value.querySelectorAll('[data-list-item]')]
  if (!listRevealNodes.length || prefersReducedMotion) {
    if (listRevealNodes.length) gsap.set(listRevealNodes, { opacity: 1, y: 0 })
    return
  }

  gsap.set(listRevealNodes, { opacity: 0, y: tokenLength('--motion-distance-section'), willChange: 'opacity, transform' })
  listRevealTriggers = ScrollTrigger.batch(listRevealNodes, {
    start: `top ${tokenValue('--scroll-trigger-list-start')}`,
    once: true,
    onEnter: batch => {
      const tween = gsap.to(batch, {
        opacity: 1,
        y: 0,
        duration: tokenDuration('--dur-section'),
        stagger: tokenNumber('--motion-stagger-fast'),
        ease: tokenEase('--ease-gsap-reveal'),
        overwrite: true,
        onComplete: () => gsap.set(batch, { clearProps: 'opacity,transform,willChange' })
      })
      listRevealTweens.push(tween)
    }
  })
  ScrollTrigger.refresh()
}

function handleTabEntered() {
  if (listTabs.has(tab.value)) createListReveal()
}

function handleMotionPreference(event) {
  prefersReducedMotion = event.matches
  if (!prefersReducedMotion) return

  resultsRevealTween?.kill()
  if (resultsPanel.value) gsap.set(resultsPanel.value, { clearProps: 'opacity,transform' })
  if (runProgressLeaveDone) {
    runProgressLeaveTween?.kill()
    const done = runProgressLeaveDone
    runProgressLeaveDone = null
    runProgressLeaveTween = null
    resultsVisible.value = true
    done()
  }

  if (heroRevealElements.length) gsap.killTweensOf(heroRevealElements)
  if (heroTitleElements.length) gsap.killTweensOf(heroTitleElements)
  heroTimeline?.kill()
  heroTimeline = null
  if (tabIndicator.value) gsap.killTweensOf(tabIndicator.value)
  clearDialogMotion(searchDialog.value)
  if (searchDialog.value?.open) gsap.set(searchDialog.value, { opacity: 1, scale: 1, clearProps: 'transform' })
  if (heroRevealElements.length) gsap.set(heroRevealElements, { opacity: 1, y: 0, clearProps: 'transform,willChange' })
  if (heroTitleElements.length) gsap.set(heroTitleElements, { opacity: 1, y: 0, clearProps: 'transform,willChange' })
  resetMagnetic(false)
  moveTabIndicator(false)
  overviewCountsPlayed = true
  destroyOverviewCounts(true)
  destroyListReveal(true)
}

watch([tab, pending, resultsVisible], async ([activeTab, isPending, visible]) => {
  destroyListReveal(true)
  if (isPending || !visible) {
    indicatorReady = false
    overviewCountsPlayed = false
    destroyOverviewCounts()
    return
  }

  await nextTick()
  moveTabIndicator(indicatorReady)
  indicatorReady = true
  if (activeTab === 'overview') createOverviewCounts()
  else {
    destroyOverviewCounts()
    if (!listTabs.has(activeTab)) destroyListReveal(true)
  }
})

watch([query, selectedEvidence, data], async () => {
  if (pending.value || !listTabs.has(tab.value)) return
  await nextTick()
  createListReveal()
})

watch(() => data.value.reports[0]?.report_id || '', loadReportPreview, { immediate: true })

onMounted(async () => {
  window.addEventListener('keydown', shortcut)
  window.addEventListener('resize', scheduleTabIndicator, { passive: true })
  motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
  finePointerPreference = window.matchMedia('(hover: hover) and (pointer: fine)')
  prefersReducedMotion = motionPreference.matches
  motionPreference.addEventListener('change', handleMotionPreference)

  await nextTick()
  revealHero()
  moveTabIndicator(false)
  indicatorReady = Boolean(tabIndicator.value)
  createOverviewCounts()
})

onUnmounted(() => {
  window.removeEventListener('keydown', shortcut)
  window.removeEventListener('resize', scheduleTabIndicator)
  motionPreference?.removeEventListener('change', handleMotionPreference)
  if (tabFrame !== null) window.cancelAnimationFrame(tabFrame)
  if (heroRevealElements.length) gsap.killTweensOf(heroRevealElements)
  if (heroTitleElements.length) gsap.killTweensOf(heroTitleElements)
  heroTimeline?.kill()
  heroTimeline = null
  resetMagnetic(false)
  if (tabIndicator.value) gsap.killTweensOf(tabIndicator.value)
  clearDialogMotion(searchDialog.value)
  reportPreviewVersion++
  resultsRevealTween?.kill()
  runProgressLeaveTween?.kill()
  runProgressLeaveDone?.()
  runProgressLeaveTween = null
  runProgressLeaveDone = null
  if (resultsPanel.value) gsap.killTweensOf(resultsPanel.value)
  destroyOverviewCounts(true)
  destroyListReveal(true)
})
</script>
<template>
  <div class="investigation-view">
    <TopBar :case-name="chineseText(detail?.title) || '读取中'" :category="run?.workflow_version === 'quant-v1' ? '量化投研' : run ? modeLabel(run) : '新建事件'" :export-url="exportUrl" :search-disabled="pending" @open-search="openSearch" />
    <div class="content-area">
    <header ref="hero" class="hero">
      <div class="hero-title-row">
        <div class="hero-heading">
          <div class="hero-heading-line">
            <h1 class="hero-title" :class="`hero-title--${heroTitleSize}`" :aria-label="heroTitle">
              <span v-for="(part, index) in heroTitleParts" :key="`${part}-${index}`" class="hero-title-part" data-hero-title-part>{{ part }}</span>
            </h1>
            <span class="badge hero-status" :class="heroStatus.tone" data-hero-reveal>{{ heroStatus.label }}</span>
          </div>
          <p class="hero-lede" data-hero-reveal>{{ chineseText(detail?.investigation_goal) || '重建事件经过，追溯证据与结论之间的联系。' }}</p>
        </div>
        <div class="hero-primary-action" data-hero-reveal @pointermove="moveMagnetic" @pointerleave="resetMagnetic()">
          <button v-if="data.reports.length && !pending" class="btn btn-primary" @click="tab = 'report'">阅读报告</button>
          <button v-else-if="investigationId === 'INV-EAST-PALESTINE-2023'" class="btn btn-primary" :disabled="pending" @click="emit('replay')">{{ replaying ? '正在回放…' : '运行回放调查' }}</button>
          <button v-else-if="run?.workflow_version !== 'quant-v1'" class="btn btn-primary" :disabled="starting || running || loading || recoveryBusy" @click="launch">{{ starting ? '正在启动…' : '启动联网调查' }}</button>
        </div>
      </div>
      <div class="hero-meta-row" data-hero-reveal>
        <span class="archive-id" :title="investigationId">编号 {{ investigationId }}</span>
        <span class="meta-separator" aria-hidden="true">·</span>
        <span>{{ pending ? '声明验证中' : verification.label }}</span>
        <span class="meta-separator" aria-hidden="true">·</span>
        <span>{{ quant ? (quant.input_snapshot_ids?.length || 0) + ' 个冻结快照' : pending ? '来源收集中' : data.sources.length + ' 个来源' }}</span>
      </div>
    </header>

    <section v-if="executiveSummary" class="execution-summary card" aria-labelledby="execution-summary-title">
      <span id="execution-summary-title" class="summary-label">FOLIO BRIEF / 执行摘要</span>
      <p>{{ executiveSummary }}</p>
      <button class="summary-link" @click="tab = 'report'">阅读完整报告 →</button>
    </section>

    <div v-if="resultsVisible" ref="resultsPanel" class="results-panel">
    <nav ref="tabNav" class="section-nav" aria-label="调查内容" @scroll.passive="scheduleTabIndicator">
      <button
        v-for="[key, tabLabel] in tabs"
        :key="key"
        class="nav-tab"
        :class="{ active: tab === key }"
        :data-tab-key="key"
        :aria-current="tab === key ? 'page' : undefined"
        @click="tab = key"
      >
        {{ tabLabel }}
        <span v-if="Array.isArray(data[key])" class="tab-count">{{ data[key].length }}</span>
      </button>
      <span ref="tabIndicator" class="tab-indicator" aria-hidden="true"></span>
    </nav>
    <div class="tab-stage">
    <Transition name="tab-content" mode="out-in" @after-enter="handleTabEntered">
    <div :key="tab" class="tab-panel">
    <section v-if="tab === 'overview'" ref="overviewPanel">
      <AgentFlow :agents="agents"><template #heading><SectionHeading section-num="01" section-name="智能体协作" section-desc="执行记录驱动" /></template></AgentFlow>
      <EvidenceChain :chain="chain"><template #heading><SectionHeading section-num="02" section-name="证据链概览" section-desc="由来源到结论" /></template></EvidenceChain>
      <div v-if="run" class="overview-columns">
        <section><SectionHeading section-num="03" section-name="事件时间线" /><Timeline :items="timelinePreview" /><p v-if="!timelinePreview.length" class="empty">尚无有证据关联的事件。</p><button class="quiet-button" @click="tab = 'timeline'">查看完整时间线 →</button></section>
        <section><SectionHeading section-num="04" section-name="关键声明" /><article v-for="(c, index) in data.claims.slice(0, 4)" :key="c.claim_id" class="claim-preview"><span class="folio-index-label">{{ folioLabel('CLAIM', index) }}</span><span class="badge evidence-stamp" :class="c.validation_status.toLowerCase()">{{ label(c.validation_status) }}</span><p>{{ chineseText(c.statement) }}</p></article><p v-if="!data.claims.length" class="empty">尚无调查声明。</p><button class="quiet-button" @click="tab = 'claims'">查看声明与验证依据 →</button></section>
      </div>
      <SectionHeading section-num="05" section-name="调查范围" /><p class="prose">{{ chineseText(detail?.event_description) }}</p>
      <ul class="questions"><li v-for="q in detail?.questions" :key="q.question_id">{{ chineseText(q.text) }}</li></ul>
      <p v-if="!run" class="empty">尚无运行记录。启动联网调查后，这里会显示实际执行步骤。</p>
    </section>
    <section v-if="tab === 'agents'">
      <AgentFlow :agents="agents"><template #heading><SectionHeading section-num="01" section-name="智能体流程" section-desc="实际持久化步骤" /></template></AgentFlow>
        <h2>执行记录 <small>{{ label(run?.current_phase) }}</small></h2>
        <div class="table-wrap"><table><thead><tr><th>角色 / 阶段</th><th>步骤</th><th>状态</th><th>耗时</th></tr></thead><tbody><tr v-for="s in data.steps" :key="s.step_id"><td>{{ label(s.agent_role) }}<small>{{ label(s.phase) }}</small></td><td>{{ label(s.step_type) }}<details><summary>步骤标识</summary>{{ s.logical_step_key }}</details><small v-if="s.error_code">{{ s.error_code }}</small></td><td>{{ label(s.status) }}</td><td>{{ (s.active_elapsed_ms / 1000).toFixed(1) }} 秒</td></tr></tbody></table></div>
        <p v-if="!data.steps.length" class="empty">尚无持久化执行步骤。</p>
        <p v-if="budget" class="notice">已用预算：搜索 {{ budget.search_calls_used }}/{{ budget.max_search_calls }}，抓取 {{ budget.fetch_calls_used }}/{{ budget.max_fetch_calls }}，模型 {{ budget.model_calls_used }}/{{ budget.max_model_calls }}，Token {{ budget.tokens_used }}/{{ budget.max_tokens }}。</p>
    </section>
    <label v-if="['sources','evidence','claims'].includes(tab)" class="filter">筛选当前记录<input v-model="query" type="search" placeholder="输入关键词" /></label>
    <section v-if="tab === 'sources'" ref="listPanel" class="record-list" data-panel="sources">
      <div v-if="!filtered.sources.length" class="empty">
        <span class="empty-icon" aria-hidden="true">◇</span><h3>没有匹配的来源</h3><p>调整筛选关键词，或清空输入查看全部来源。</p>
      </div>
      <article v-for="(s, index) in filtered.sources" :key="s.source_id" class="record source-record folio-index-card is-interactive" data-list-item>
        <span class="folio-index-label">{{ folioLabel('SOURCE', index) }}</span>
        <div class="record-heading">
          <div class="record-title-group">
            <span class="record-domain">{{ sourceDomain(s.canonical_url) }}</span>
            <h2><a :href="safeUrl(s.canonical_url)" target="_blank" rel="noopener noreferrer">{{ chineseText(s.title) }}</a></h2>
          </div>
          <div class="badge-row">
            <span v-if="s.is_official" class="badge probable">官方来源</span>
            <span v-if="s.is_first_hand" class="badge verified">一手来源</span>
            <span class="badge" :class="eligibilityClass(s.evidence_eligible)">{{ s.evidence_eligible === true ? '可用于取证' : s.evidence_eligible === false ? '不可用于取证' : '待检查' }}</span>
          </div>
        </div>
        <div class="record-meta"><span>{{ chineseText(s.publisher || s.organization) || '发布机构未知' }}</span><span>{{ label(s.source_type) }}</span><span>{{ s.parse_status ? label(s.parse_status) : '尚未解析' }}</span></div>
        <p class="muted">发布于 {{ date(s.published_at) }}，采集于 {{ date(s.retrieved_at) }}</p>
        <div class="record-footer"><span class="record-id">来源家族：{{ s.family_id || '尚未确认' }}</span><a v-if="s.snapshot_id" :href="snapshotUrl(s.snapshot_id)" target="_blank" rel="noopener">打开归档正文</a></div>
      </article>
    </section>
    <section v-if="tab === 'evidence'" ref="listPanel" class="record-list" data-panel="evidence">
      <button v-if="selectedEvidence" class="quiet-button list-reset" @click="selectedEvidence = ''">显示全部证据</button>
      <div v-if="!visibleEvidence.length" class="empty">
        <span class="empty-icon" aria-hidden="true">◇</span><h3>没有匹配的证据</h3><p>调整筛选关键词，或从声明卡片重新选择一条证据。</p>
      </div>
      <article v-for="(e, index) in visibleEvidence" :key="e.evidence_id" class="record evidence-record folio-index-card is-interactive" data-list-item>
        <span class="folio-index-label">{{ folioLabel('EXHIBIT', index) }}</span>
        <div class="record-heading">
          <div class="record-title-group"><span class="record-kicker">证据摘录</span><h2>{{ chineseText(source(e.source_id)?.title) || e.evidence_id }}</h2></div>
          <div class="badge-row"><span v-if="!e.relations.length" class="badge evidence-stamp unverified">尚未关联声明</span><span v-for="r in e.relations" :key="r.claim_id" class="badge evidence-stamp" :class="relationClass(r)">{{ label(r.stance) }} · {{ label(r.entailment_status) }}</span></div>
        </div>
        <blockquote class="evidence-quote">{{ e.content }}</blockquote>
        <div class="record-meta"><span>{{ e.evidence_id }}</span><span>{{ label(e.locator_type) }}</span><span>提取于 {{ date(e.extracted_at) }}</span></div>
        <div class="record-footer"><a :href="snapshotUrl(e.snapshot_id)" target="_blank" rel="noopener">查看归档正文与定位上下文</a></div>
        <details><summary>精确定位数据</summary><pre>{{ JSON.stringify(e.locator_payload, null, 2) }}</pre></details>
        <ul v-if="e.relations.length" class="relation-list"><li v-for="r in e.relations" :key="r.claim_id"><span class="badge evidence-stamp" :class="relationClass(r)">{{ label(r.stance) }}</span><span>{{ chineseText(claim(r.claim_id)?.statement) || r.claim_id }}</span></li></ul>
      </article>
    </section>
    <section v-if="tab === 'claims'" ref="listPanel" class="record-list" data-panel="claims">
      <div v-if="!filtered.claims.length" class="empty">
        <span class="empty-icon" aria-hidden="true">◇</span><h3>没有匹配的声明</h3><p>尝试更短的关键词，或清空筛选查看全部调查声明。</p>
      </div>
      <article v-for="(c, index) in filtered.claims" :key="c.claim_id" class="record claim-record is-interactive" data-list-item>
        <span class="folio-index-label">{{ folioLabel('CLAIM', index) }}</span>
        <div class="record-heading"><div class="badge-row"><span class="badge evidence-stamp" :class="validationClass(c.validation_status)">{{ label(c.validation_status) }}</span><span v-if="c.is_critical" class="badge evidence-stamp disputed">关键声明</span></div><span class="record-type">{{ label(c.claim_type) }} / {{ label(c.importance) }}</span></div>
        <h2>{{ chineseText(c.statement) }}</h2>
        <p class="claim-explanation">{{ validationExplanation(c) }}</p>
        <div class="claim-metrics">
          <div><span class="metric-value verified-text">{{ c.supporting_evidence_ids.length }}</span><span class="metric-label">支持证据</span></div>
          <div><span class="metric-value disputed-text">{{ c.contradicting_evidence_ids.length }}</span><span class="metric-label">反驳证据</span></div>
          <div class="confidence-metric"><div class="confidence-heading"><span class="metric-label">规则置信度</span><span class="metric-value confidence-value">{{ c.confidence == null ? '未评估' : confidencePercent(c.confidence) + '%' }}</span></div><div v-if="c.confidence != null" class="progress" :style="{ '--progress-value': confidencePercent(c.confidence) + '%' }"><span class="progress-bar" role="progressbar" :aria-valuenow="confidencePercent(c.confidence)" aria-valuemin="0" aria-valuemax="100"></span></div></div>
        </div>
        <details><summary>详细验证记录</summary><p>{{ chineseText(c.validation_basis) || '尚无验证依据' }}</p><p class="muted">规则评分：{{ c.confidence ?? '未评估' }}（不是事实成立的概率）。{{ c.confidence_basis }}</p></details>
        <div class="actions claim-actions"><button v-for="id in c.supporting_evidence_ids" :key="id" class="btn btn-ghost" @click="viewEvidence(id)">支持证据 {{ data.evidence.findIndex(e => e.evidence_id === id) + 1 }}</button><button v-for="id in c.contradicting_evidence_ids" :key="id" class="btn btn-ghost" @click="viewEvidence(id)">反证 {{ data.evidence.findIndex(e => e.evidence_id === id) + 1 }}</button></div>
      </article>
    </section>
    <section v-if="tab === 'conflicts'" ref="listPanel" class="record-list conflict-list" data-panel="conflicts">
      <SectionHeading section-num="01" section-name="冲突" section-desc="并置检查相互矛盾的记录" />
      <div v-if="!data.conflicts.length" class="empty">
        <span class="empty-icon" aria-hidden="true">◇</span><h3>当前没有已记录冲突</h3><p>这不代表已经排除所有矛盾，后续证据仍可能形成新的冲突集。</p>
      </div>
      <article v-for="c in data.conflicts" :key="c.conflict_id" class="record conflict-record is-interactive" data-list-item>
        <div class="record-heading"><div class="badge-row"><span class="badge" :class="severityClass(c.severity)">{{ label(c.severity) }}</span><span class="badge disputed">{{ label(c.conflict_type) }}</span></div><span class="record-type">{{ label(c.status) }} / {{ label(c.resolution_status) }}</span></div>
        <div v-if="c.competing_values.length" class="conflict-compare"><div v-for="(value, index) in c.competing_values" :key="value.evidence_id || index" class="conflict-side"><span class="record-kicker">记录 {{ index + 1 }}</span><p>{{ chineseText(value.statement) || JSON.stringify(value) }}</p><small v-if="value.scope || value.definition">{{ value.scope || value.definition }}</small></div></div>
        <ul v-else class="conflict-claims"><li v-for="id in c.claim_ids" :key="id">{{ chineseText(claim(id)?.statement) || id }}</li></ul>
        <div class="notice" :class="c.status === 'RESOLVED' ? 'verified' : 'disputed'"><strong>{{ chineseText(c.resolution_summary) || '尚无解决结论' }}</strong><p>{{ chineseText(c.resolution_basis) }}</p><p v-for="reason in c.possible_explanations" :key="reason">{{ chineseText(reason) }}</p></div>
        <details><summary>冲突值与可能原因</summary><pre>{{ JSON.stringify({ values: c.competing_values, causes: c.possible_causes }, null, 2) }}</pre></details>
      </article>
      <SectionHeading section-num="02" section-name="研究缺口" section-desc="尚需补足的证据与行动" />
      <div v-if="!data.gaps.length" class="notice probable gap-empty"><span class="empty-icon" aria-hidden="true">◇</span><div><strong>暂无已记录研究缺口</strong><p>当前运行没有生成缺口记录；这不等于调查已经穷尽所有问题。</p></div></div>
      <article v-for="g in data.gaps" :key="g.gap_id" class="record gap-record is-interactive" data-list-item>
        <div class="record-heading"><div class="badge-row"><span class="badge" :class="severityClass(g.severity)">{{ label(g.severity) }}</span><span class="badge unverified">{{ label(g.gap_type) }}</span></div><span class="record-type">{{ label(g.status) }}</span></div>
        <h3>{{ chineseText(g.reason) }}</h3><p class="gap-action">{{ chineseText(g.suggested_action) }}</p><ul v-if="g.suggested_actions.length"><li v-for="action in g.suggested_actions" :key="action">{{ chineseText(action) }}</li></ul>
      </article>
    </section>
    <section v-if="tab === 'timeline'">
      <p v-if="!data.timeline.length" class="empty">暂无有证据关联的时间线记录。</p>
      <article v-for="(event, index) in data.timeline" :key="event.timeline_event_id" class="record timeline-record"><span class="folio-index-label">{{ folioLabel('CASE TIME', index) }}</span><time>{{ date(event.event_time) }}</time><h2>{{ chineseText(event.description) }}</h2><p>{{ label(event.time_precision) }} · {{ label(event.validation_status) }}</p><button v-for="id in event.evidence_ids" :key="id" @click="viewEvidence(id)">查看事件证据</button></article>
    </section>
    <ReportDetail v-if="tab === 'report'" :reports="data.reports" :evidence="data.evidence" :run-id="runId" :run-status="run?.status" :show-review="false" @updated="refreshReports()" />
    <section v-if="tab === 'review'"><ReviewPanel v-if="data.reports.length" :key="data.reports[0].report_id" :report-id="data.reports[0].report_id" @updated="loadRun()" /><p v-else class="empty">当前运行尚未生成报告。</p></section>
    </div>
    </Transition>
    </div>
    </div>

    <details class="process-panel" :open="Boolean(error) || pending || !resultsVisible">
      <summary class="process-summary">
        <span>调查过程</span>
        <span class="badge" :class="heroStatus.tone">{{ heroStatus.label }}</span>
      </summary>
      <div class="process-content">
        <p v-if="error" class="notice error" role="alert">{{ error }} <button @click="load">重新加载</button></p>
        <p class="muted">联网调查使用服务端模型配置，可能产生调用费用。离线案例请使用左侧回放入口。</p>
        <div v-if="runs.length" class="run-bar"><RunHistory :runs="runs" :model-value="runId" :disabled="pending || recoveryBusy" @update:model-value="loadRun" /></div>
        <div v-if="showListSkeleton" class="record-list loading-records" role="status" aria-label="正在加载调查记录">
          <article v-for="index in 3" :key="index" class="record skeleton-record">
            <span class="skeleton skeleton-shimmer skeleton-kicker">正在加载</span>
            <span class="skeleton skeleton-shimmer skeleton-title">正在加载记录标题</span>
            <span class="skeleton skeleton-shimmer skeleton-copy">正在加载记录内容</span>
          </article>
        </div>
        <Transition :css="false" @leave="closeRunProgress" @leave-cancelled="cancelRunProgressClose">
          <RunProgress v-if="pending && !showListSkeleton" :key="runId || 'starting'" :replaying="replaying" :starting="starting" :running="running" :phase="quant?.phase || run?.current_phase" :quant="Boolean(quant)" :workers="workers" :budget="budget" :steps="data.steps" />
        </Transition>
        <p v-if="run?.interruption_reason" class="notice">运行说明：{{ runFailureLabel(run.interruption_reason) }}</p>
        <RunRecovery v-if="showRecovery" :run-id="runId" :busy="pending" @busy="recoveryBusy = $event" @resumed="resumed" />
        <div class="process-actions">
          <button v-if="data.reports.length && investigationId === 'INV-EAST-PALESTINE-2023'" class="btn btn-ghost" :disabled="pending" @click="emit('replay')">{{ replaying ? '正在回放…' : '运行回放调查' }}</button>
          <button v-else-if="data.reports.length && run?.workflow_version !== 'quant-v1'" class="btn btn-ghost" :disabled="starting || running || loading || recoveryBusy" @click="launch">{{ starting ? '正在启动…' : '启动联网调查' }}</button>
          <button class="btn btn-ghost" @click="emit('new-investigation')">调查新主题</button>
          <button v-if="running" class="btn btn-ghost" @click="cancel">取消运行</button>
          <button class="quiet-button" :disabled="pending || recoveryBusy" @click="load">刷新</button>
        </div>
      </div>
    </details>
    </div>
    <dialog ref="searchDialog" class="search-dialog" aria-labelledby="search-title" @cancel.prevent="closeSearch"><div class="row"><h2 id="search-title">搜索当前调查</h2><button @click="closeSearch">关闭</button></div><label>来源、证据与声明<input v-model="searchQuery" type="search" placeholder="输入关键词" autofocus /></label><p v-if="!searchQuery.trim()" class="muted">在当前运行的真实记录中检索。</p><p v-else-if="!searchResults.length" class="empty">没有匹配记录。</p><button v-for="(result, index) in searchResults" :key="index" class="search-result" @click="selectResult(result)"><small>{{ {sources: '来源', evidence: '证据', claims: '声明'}[result.key] }}</small>{{ result.text }}</button></dialog>
  </div>
</template>

<style scoped>
.investigation-view {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.content-area {
  flex: 1;
  width: 100%;
  max-width: var(--content-max-width);
  margin: 0 auto;
  padding: var(--space-12) var(--space-16) var(--space-20);
}

/* Hero */
.hero {
  margin-bottom: var(--space-12);
}

.hero-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-8);
}

.hero-heading {
  min-width: 0;
  flex: 1;
}

.hero-heading-line {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.hero-title {
  margin: 0;
  overflow-wrap: break-word;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: var(--font-size-display-xl);
  font-weight: var(--font-weight-display-xl);
  letter-spacing: var(--letter-spacing-display-xl);
  line-height: var(--line-height-display-xl);
  text-wrap: balance;
  word-break: break-word;
}

.hero-title-part {
  display: inline-block;
  max-width: 100%;
  white-space: pre-wrap;
}

.hero-title--lg { font-size: var(--font-size-hero-lg); }
.hero-title--md { font-size: var(--font-size-hero-md); }
.hero-title--sm { font-size: var(--font-size-hero-sm); line-height: var(--line-height-hero-long); }

.hero-status {
  margin-top: var(--space-2);
  flex-shrink: 0;
}

.hero-lede {
  max-width: var(--measure-intimate);
  margin-top: var(--space-4);
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: var(--font-size-body-lg);
  line-height: var(--line-height-body-lg);
}

.hero-primary-action {
  flex-shrink: 0;
}

.hero-meta-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-8);
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  flex-wrap: wrap;
}

.hero-meta-row .archive-id {
  max-width: min(100%, calc(var(--space-32) + var(--space-32)));
}

.meta-separator {
  color: var(--border-strong);
}

.execution-summary {
  margin-bottom: var(--space-12);
}

.execution-summary .summary-label {
  display: block;
  margin-bottom: var(--space-3);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-caption);
  letter-spacing: var(--letter-spacing-overline);
  line-height: var(--line-height-caption);
}

.execution-summary p {
  max-width: var(--measure-body);
  color: var(--text-primary);
  font-family: var(--font-serif);
  font-size: var(--font-size-body-lg);
  line-height: var(--line-height-body-lg);
}

.summary-link {
  margin-top: var(--space-4);
  padding: 0;
  color: var(--text-secondary);
  font-size: var(--font-size-small);
  font-weight: var(--font-weight-caption);
  line-height: var(--line-height-small);
  text-decoration: underline;
  text-decoration-color: var(--border-strong);
  text-underline-offset: var(--space-1);
}

.summary-link:hover {
  color: var(--text-primary);
  text-decoration-color: currentColor;
}

/* 章节导航 Tabs */
.section-nav {
  position: relative;
  display: flex;
  gap: 0;
  margin-bottom: var(--space-12);
  overflow-x: auto;
  border-bottom: 1px solid var(--border-default);
  scrollbar-width: none;
}

.section-nav::-webkit-scrollbar {
  display: none;
}

.nav-tab {
  position: relative;
  display: inline-flex;
  min-width: calc(var(--space-20) + var(--space-2));
  min-height: var(--space-10);
  flex: 1 0 calc(100% / 9);
  align-items: center;
  justify-content: center;
  padding: 0 var(--space-2);
  border: 0;
  background: transparent;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: var(--font-size-small);
  font-weight: var(--font-weight-caption);
  line-height: var(--line-height-small);
  white-space: nowrap;
  cursor: pointer;
  transition: color var(--dur-sm) var(--ease-standard);
}

.nav-tab:hover {
  color: var(--text-primary);
}

.nav-tab.active {
  color: var(--text-primary);
  font-weight: var(--font-weight-h4);
}

.tab-indicator {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 0;
  height: 2px;
  border-radius: var(--radius-full);
  background: var(--accent);
  pointer-events: none;
  will-change: width, transform;
}

.tab-count {
  margin-left: var(--space-1);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-size-overline);
  font-weight: var(--font-weight-body);
  line-height: var(--line-height-overline);
}

.tab-stage {
  min-height: var(--space-32);
}

.tab-panel {
  width: 100%;
}

.tab-content-enter-active {
  transition: opacity var(--dur-md) var(--ease-out-expo),
    transform var(--dur-md) var(--ease-out-expo);
}

.tab-content-leave-active {
  transition: opacity var(--dur-tab-out) var(--ease-standard),
    transform var(--dur-tab-out) var(--ease-standard);
}

.tab-content-enter-from {
  opacity: 0;
  transform: translateY(var(--space-2));
}

.tab-content-leave-to {
  opacity: 0;
  transform: translateY(calc(var(--space-2) * -1));
}

/* Low-priority process and operations area */
.process-panel {
  margin: var(--space-16) 0 0;
  overflow: hidden;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
}

.process-summary {
  display: flex;
  min-height: var(--space-12);
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  color: var(--text-secondary);
  font-size: var(--font-size-small);
  font-weight: var(--font-weight-caption);
  line-height: var(--line-height-small);
  list-style: none;
}

.process-summary::-webkit-details-marker {
  display: none;
}

.process-content {
  padding: var(--space-6);
  border-top: 1px solid var(--border-default);
}

.process-content > :first-child {
  margin-top: 0;
}

.process-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-6);
  flex-wrap: wrap;
}

/* Stage 5 · record lists */
.record-list {
  display: grid;
  gap: var(--space-4);
}

.record-list > .record {
  margin-top: 0;
}

.record.is-interactive {
  cursor: pointer;
  transition: border-color var(--dur-sm) var(--ease-standard),
    background-color var(--dur-sm) var(--ease-standard),
    transform var(--dur-sm) var(--ease-standard);
}

@media (hover: hover) and (pointer: fine) {
  .record.is-interactive:hover {
    border-color: var(--border-strong);
    background: var(--bg-elevated);
    transform: translateY(calc(var(--motion-distance-card) * -1));
  }
}

.record-heading,
.record-footer,
.badge-row,
.record-meta,
.confidence-heading {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.folio-index-label {
  display: block;
  margin-bottom: var(--space-3);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-size-overline);
  font-weight: var(--font-weight-overline);
  letter-spacing: var(--letter-spacing-overline);
  line-height: var(--line-height-overline);
}

.folio-index-card {
  position: relative;
  border-width: var(--stroke-thin);
}

.evidence-stamp {
  border-radius: var(--radius-sm);
  background: transparent;
  font-family: var(--font-mono);
  letter-spacing: var(--letter-spacing-caption);
  transform: rotate(var(--stamp-rotation));
}

.timeline-record {
  position: relative;
  padding-left: var(--space-8);
  border-left-width: var(--stroke-thin);
}

.timeline-record::before {
  position: absolute;
  top: var(--space-6);
  bottom: calc(var(--space-5) * -1);
  left: var(--space-3);
  width: var(--stroke-thin);
  background: var(--border-strong);
  content: '';
}

.timeline-record::after {
  position: absolute;
  top: var(--space-5);
  left: calc(var(--space-3) - var(--space-1));
  width: var(--space-2);
  height: var(--space-2);
  border: var(--stroke-thin) solid var(--border-strong);
  border-radius: var(--radius-full);
  background: var(--bg-surface);
  content: '';
}

.timeline-record:last-child::before {
  bottom: var(--space-6);
}

.timeline-record time {
  display: block;
  margin-bottom: var(--space-2);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-size-caption);
  font-variant-numeric: tabular-nums;
  line-height: var(--line-height-caption);
}

.record-heading,
.record-footer,
.confidence-heading {
  justify-content: space-between;
}

.record-title-group {
  min-width: 0;
  flex: 1;
}

.record-title-group h2,
.claim-record > h2 {
  margin: var(--space-1) 0 0;
}

.record-domain,
.record-kicker,
.record-id,
.record-type,
.record-meta,
.metric-label {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.record-domain,
.record-kicker {
  color: var(--text-muted);
  font-size: var(--font-size-overline);
  font-weight: var(--font-weight-overline);
  letter-spacing: var(--letter-spacing-overline);
}

.record-meta {
  margin-top: var(--space-4);
}

.record-meta span:not(:last-child) {
  padding-right: var(--space-3);
  border-right: calc(var(--space-1) / 4) solid var(--border-default);
}

.record-footer {
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: calc(var(--space-1) / 4) solid var(--border-default);
}

.evidence-quote {
  margin: var(--space-5) 0;
  border-left-color: var(--border-strong);
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  background: var(--bg-elevated);
}

.relation-list {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-4);
  padding-left: 0;
  list-style: none;
}

.relation-list li {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  align-items: start;
  gap: var(--space-3);
  padding-top: var(--space-3);
  border-top: calc(var(--space-1) / 4) solid var(--border-default);
}

.claim-explanation {
  color: var(--text-secondary);
  font-family: var(--font-serif);
  font-size: var(--font-size-body-lg);
  line-height: var(--line-height-body-lg);
}

.claim-metrics {
  display: flex;
  align-items: stretch;
  gap: var(--space-3);
  margin-block: var(--space-5);
  flex-wrap: wrap;
}

.claim-metrics > div {
  display: grid;
  min-width: var(--space-24);
  gap: var(--space-1);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--bg-elevated);
}

.metric-value {
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: var(--font-size-h3);
  font-weight: var(--font-weight-h3);
  font-variant-numeric: tabular-nums;
  line-height: var(--line-height-h3);
}

.verified-text {
  color: var(--text-primary);
}

.disputed-text {
  color: var(--text-primary);
}

.claim-metrics .confidence-metric {
  min-width: calc(var(--space-32) + var(--space-16));
  flex: 1;
}

.confidence-value {
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.claim-actions {
  margin-top: var(--space-4);
}

.claim-actions .btn {
  min-height: var(--space-8);
  padding-inline: var(--space-3);
  font-size: var(--font-size-caption);
}

.conflict-list > .section-heading:not(:first-child) {
  margin-top: var(--space-12);
}

.conflict-compare {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, calc(var(--space-32) + var(--space-32))), 1fr));
  gap: var(--space-3);
  margin-block: var(--space-5);
}

.conflict-side {
  padding: var(--space-4);
  border-left: var(--space-1) solid var(--border-strong);
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  background: var(--bg-elevated);
}

.conflict-side:nth-child(even) {
  border-left-color: var(--border-default);
  background: var(--bg-surface);
}

.conflict-side p {
  margin-block: var(--space-2);
  color: var(--text-primary);
  font-family: var(--font-serif);
  font-size: var(--font-size-body-lg);
  line-height: var(--line-height-body-lg);
}

.conflict-side small {
  color: var(--text-muted);
}

.conflict-claims {
  margin-block: var(--space-4);
}

.gap-action {
  color: var(--text-secondary);
}

.gap-empty {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.gap-empty p {
  margin: var(--space-1) 0 0;
}

.record-list .empty-icon,
.gap-empty .empty-icon {
  display: grid;
  width: var(--space-10);
  height: var(--space-10);
  margin: 0;
  place-items: center;
  border: var(--stroke-thin) solid var(--border-strong);
  border-radius: var(--radius-sm);
  color: transparent;
  font-size: 0;
  opacity: 1;
}

.record-list .empty-icon::before,
.gap-empty .empty-icon::before {
  width: var(--space-5);
  height: var(--space-3);
  border-block: var(--stroke-thin) solid var(--text-muted);
  content: '';
}

.list-reset {
  justify-self: start;
}

.loading-records {
  margin-top: var(--space-8);
}

.skeleton-record {
  display: grid;
  gap: var(--space-4);
}

.skeleton-record::before {
  color: var(--text-muted);
  content: 'CASE FILE';
  font-family: var(--font-mono);
  font-size: var(--font-size-overline);
  font-weight: var(--font-weight-overline);
  letter-spacing: var(--letter-spacing-overline);
  line-height: var(--line-height-overline);
}

.skeleton-record > span {
  display: block;
}

.skeleton-kicker {
  width: var(--space-20);
  height: var(--space-3);
}

.skeleton-title {
  width: calc(var(--space-32) + var(--space-32) + var(--space-12));
  max-width: 100%;
  height: var(--space-6);
}

.skeleton-copy {
  width: 100%;
  height: var(--space-16);
}

/* 响应式 */
@media (max-width: 1200px) {
  .content-area {
    padding: var(--space-10) var(--space-10) var(--space-16);
  }
}

@media (max-width: 56.25rem) {
  .hero-title-row {
    flex-direction: column;
    gap: var(--space-4);
  }

  .hero-primary-action {
    align-self: flex-start;
  }

  .section-nav {
    margin-bottom: var(--space-8);
  }
}

@media (width < 48rem) {
  .hero-primary-action {
    width: 100%;
  }

  .hero-primary-action .btn,
  .process-actions .btn,
  .claim-actions .btn,
  .list-reset {
    width: 100%;
  }

  .section-nav {
    margin-inline: calc(var(--space-4) * -1);
    padding-inline: var(--space-4);
    overflow-x: auto;
    overscroll-behavior-inline: contain;
    scrollbar-width: none;
  }

  .section-nav::-webkit-scrollbar {
    display: none;
  }

  .section-nav button {
    min-width: max-content;
  }

  .process-content {
    padding: var(--space-4);
  }
}

@media (prefers-reduced-motion: reduce) {
  .tab-content-enter-active,
  .tab-content-leave-active {
    transition: none;
  }

  .tab-content-enter-from,
  .tab-content-leave-to {
    opacity: 1;
    transform: none;
  }
}
</style>
