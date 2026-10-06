<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import gsap from 'gsap'
import { label } from '../composables/chinese.js'
import { tokenDuration, tokenEase, tokenLength, tokenNumber } from '../utils/motionTokens.js'

const props = defineProps({
  replaying: Boolean,
  starting: Boolean,
  running: Boolean,
  quant: Boolean,
  phase: String,
  workers: { type: Object, default: () => ({}) },
  budget: Object,
  steps: { type: Array, default: () => [] }
})

const root = ref(null)
const elapsed = ref(0)
const budgetDisplay = reactive({ search: 0, fetch: 0, model: 0 })
const stepId = (step, index) => String(step.step_id || `step-${index}`)
const stepSnapshot = computed(() => props.steps.map((step, index) => ({ id: stepId(step, index), status: step.status })))
const workerSnapshot = computed(() => Object.entries(props.workers).map(([name, status]) => ({ name, status })))
const budgetSnapshot = computed(() => ({
  search: Number(props.budget?.search_calls_used) || 0,
  fetch: Number(props.budget?.fetch_calls_used) || 0,
  model: Number(props.budget?.model_calls_used) || 0
}))

const seenSteps = new Set()
const stampedSteps = new Set()
const seenWorkers = new Set()
const stampedWorkers = new Set()
const previousStepStatus = new Map()
const previousWorkerStatus = new Map()
const scanTweens = new Map()
const budgetTweens = new Map()
const pendingVisibleSteps = new Map()
const stopWatchers = []

let timer
let orbitTween
let progressTween
let phaseTween
let observer
let motionPreference
let pointerPreference
let mountedReady = false
let prefersReducedMotion = false
let allowsAmbientMotion = false
let updateGeneration = 0
let rootElement

const activeStatuses = new Set(['RUNNING', 'VERIFYING'])
const completedStatuses = new Set(['COMPLETED', 'SUCCEEDED'])
const statusClass = status => completedStatuses.has(status) ? 'verified' : ['FAILED', 'CANCELLED', 'TIMED_OUT', 'BUDGET_EXHAUSTED'].includes(status) ? 'disputed' : activeStatuses.has(status) ? 'probable' : 'unverified'
const statusText = status => ({ RUNNING: '研究中', VERIFYING: '核验中', COMPLETED: '已归档', SUCCEEDED: '已完成', FAILED: '本轮调用失败', CANCELLED: '已取消', TIMED_OUT: '已超时', BUDGET_EXHAUSTED: '预算已用尽' }[status] || label(status))
const workerName = name => ({ official: '官方资料研究员', independent: '独立报道研究员', technical: '技术研究员', counterevidence: '反证研究员' }[name] || name)
const isCurrent = status => activeStatuses.has(status)
const didComplete = (before, after) => activeStatuses.has(before) && completedStatuses.has(after)
const formatIndex = index => String(index + 1).padStart(2, '0')

function nodeMap(selector, key) {
  return new Map(root.value ? [...root.value.querySelectorAll(selector)].map(node => [node.dataset[key], node]) : [])
}

function isVisibleStep(node) {
  const rect = node.getBoundingClientRect()
  const listRect = node.closest('.progress-steps')?.getBoundingClientRect()
  const top = Math.max(0, listRect?.top ?? 0)
  const bottom = Math.min(window.innerHeight, listRect?.bottom ?? window.innerHeight)
  return rect.bottom > top && rect.top < bottom
}

function clearNodeMotion(node) {
  if (!node) return
  gsap.killTweensOf(node)
  gsap.set(node, { opacity: 1, x: 0, y: 0, rotation: 0, scale: 1, clearProps: 'transform,willChange' })
}

function animateStepEntry(node, delay = 0) {
  if (!node) return
  pendingVisibleSteps.delete(node.dataset.stepId)
  gsap.killTweensOf(node)
  if (prefersReducedMotion) {
    clearNodeMotion(node)
    return
  }
  gsap.fromTo(node, {
    opacity: 0,
    y: tokenLength('--motion-distance-live-step'),
    rotation: tokenNumber('--motion-live-entry-rotation'),
    willChange: 'opacity, transform'
  }, {
    opacity: 1,
    y: 0,
    rotation: 0,
    duration: tokenDuration('--dur-live-entry'),
    delay,
    ease: tokenEase('--ease-gsap-reveal'),
    overwrite: true,
    onComplete: () => gsap.set(node, { clearProps: 'opacity,transform,willChange' })
  })
}

function queueStepEntry(node, delay = 0) {
  if (!node) return
  if (prefersReducedMotion || isVisibleStep(node)) {
    animateStepEntry(node, delay)
    return
  }
  pendingVisibleSteps.set(node.dataset.stepId, node)
  observer?.observe(node)
}

function animateStamp(node) {
  if (!node) return
  gsap.killTweensOf(node)
  if (prefersReducedMotion) {
    clearNodeMotion(node)
    return
  }
  gsap.fromTo(node, {
    opacity: 0,
    scale: tokenNumber('--motion-live-stamp-scale'),
    rotation: tokenNumber('--motion-live-stamp-rotation'),
    willChange: 'opacity, transform'
  }, {
    opacity: 1,
    scale: 1,
    rotation: 0,
    duration: tokenDuration('--dur-live-stamp'),
    ease: tokenEase('--ease-gsap-stamp'),
    overwrite: true,
    onComplete: () => gsap.set(node, { clearProps: 'opacity,transform,willChange' })
  })
}

function animateStatusChange(node) {
  if (!node || prefersReducedMotion) return
  gsap.killTweensOf(node)
  gsap.fromTo(node, {
    opacity: tokenNumber('--motion-emphasis-opacity'),
    y: tokenLength('--motion-distance-control')
  }, {
    opacity: 1,
    y: 0,
    duration: tokenDuration('--dur-sm'),
    ease: tokenEase('--ease-gsap-standard'),
    overwrite: true,
    onComplete: () => gsap.set(node, { clearProps: 'opacity,transform' })
  })
}

function stopStepScan(id) {
  scanTweens.get(id)?.kill()
  scanTweens.delete(id)
  const line = nodeMap('[data-step-id]', 'stepId').get(id)?.querySelector('.step-scan')
  if (line) gsap.set(line, { opacity: 0, xPercent: tokenNumber('--motion-live-sweep-start') })
}

function syncStepScans() {
  const nodes = nodeMap('[data-step-id]', 'stepId')
  scanTweens.forEach((_, id) => {
    const status = stepSnapshot.value.find(step => step.id === id)?.status
    if (!activeStatuses.has(status) || !props.running || !allowsAmbientMotion || !nodes.has(id) || !isVisibleStep(nodes.get(id))) stopStepScan(id)
  })
  if (!allowsAmbientMotion || !props.running) return
  stepSnapshot.value.forEach(step => {
    if (!activeStatuses.has(step.status) || scanTweens.has(step.id)) return
    const node = nodes.get(step.id)
    if (!node || !isVisibleStep(node)) return
    const line = node.querySelector('.step-scan')
    if (!line) return
    scanTweens.set(step.id, gsap.fromTo(line, {
      opacity: tokenNumber('--motion-live-scan-opacity'),
      xPercent: tokenNumber('--motion-live-sweep-start')
    }, {
      xPercent: tokenNumber('--motion-live-sweep-end'),
      duration: tokenDuration('--dur-live-scan'),
      ease: tokenEase('--ease-gsap-linear'),
      repeat: tokenNumber('--motion-live-loop-repeat')
    }))
  })
}

function syncAmbientMotion() {
  orbitTween?.kill()
  progressTween?.kill()
  orbitTween = null
  progressTween = null
  const orbit = root.value?.querySelector('.progress-orbit')
  const bar = root.value?.querySelector('.live-progress-bar')
  if (!allowsAmbientMotion || !(props.running || props.starting || props.replaying)) {
    if (orbit) gsap.set(orbit, { rotation: 0 })
    if (bar) gsap.set(bar, { xPercent: 0 })
    syncStepScans()
    return
  }
  if (orbit) orbitTween = gsap.to(orbit, { rotation: tokenNumber('--motion-live-orbit-rotation'), duration: tokenDuration('--dur-live-scan'), ease: tokenEase('--ease-gsap-linear'), repeat: tokenNumber('--motion-live-loop-repeat') })
  if (bar) progressTween = gsap.fromTo(bar, { xPercent: tokenNumber('--motion-live-sweep-start') }, { xPercent: tokenNumber('--motion-live-sweep-end'), duration: tokenDuration('--dur-live-scan'), ease: tokenEase('--ease-gsap-linear'), repeat: tokenNumber('--motion-live-loop-repeat') })
  syncStepScans()
}

function animateBudget(key, target) {
  budgetTweens.get(key)?.kill()
  const current = Number(budgetDisplay[key]) || 0
  if (prefersReducedMotion || target <= current) {
    budgetDisplay[key] = target
    return
  }
  const state = { value: current }
  const numberNode = root.value?.querySelector(`[data-budget-key="${key}"]`)
  if (numberNode) {
    gsap.killTweensOf(numberNode)
    gsap.fromTo(numberNode, { opacity: tokenNumber('--motion-emphasis-opacity'), y: tokenLength('--motion-distance-live-number') }, {
      opacity: 1,
      y: 0,
      duration: tokenDuration('--dur-live-counter'),
      ease: tokenEase('--ease-gsap-reveal'),
      overwrite: true,
      onComplete: () => gsap.set(numberNode, { clearProps: 'opacity,transform' })
    })
  }
  const tween = gsap.to(state, {
    value: target,
    snap: { value: 1 },
    duration: tokenDuration('--dur-live-counter'),
    ease: tokenEase('--ease-gsap-standard'),
    onUpdate: () => { budgetDisplay[key] = Math.round(state.value) },
    onComplete: () => {
      budgetDisplay[key] = target
      budgetTweens.delete(key)
    }
  })
  budgetTweens.set(key, tween)
}

function animatePhase() {
  const node = root.value?.querySelector('.phase-value')
  phaseTween?.kill()
  if (!node || prefersReducedMotion) {
    if (node) clearNodeMotion(node)
    return
  }
  phaseTween = gsap.fromTo(node, {
    opacity: 0,
    y: tokenLength('--motion-distance-tab'),
    willChange: 'opacity, transform'
  }, {
    opacity: 1,
    y: 0,
    duration: tokenDuration('--dur-live-phase'),
    ease: tokenEase('--ease-gsap-reveal'),
    overwrite: true,
    onComplete: () => gsap.set(node, { clearProps: 'opacity,transform,willChange' })
  })
}

function resetDataset() {
  updateGeneration++
  observer?.disconnect()
  pendingVisibleSteps.clear()
  scanTweens.forEach(tween => tween.kill())
  scanTweens.clear()
  seenSteps.clear()
  stampedSteps.clear()
  previousStepStatus.clear()
}

async function handleSteps(next, previous = []) {
  if (!mountedReady) return
  const previousIds = new Set(previous.map(step => step.id))
  if (previousIds.size && next.length && !next.some(step => previousIds.has(step.id))) resetDataset()
  const generation = updateGeneration
  const newIds = next.filter(step => !seenSteps.has(step.id)).map(step => step.id)
  newIds.forEach(id => seenSteps.add(id))
  const changes = next.map(step => ({ ...step, before: previousStepStatus.get(step.id) }))
  next.forEach(step => previousStepStatus.set(step.id, step.status))
  await nextTick()
  if (!mountedReady || generation !== updateGeneration) return
  const nodes = nodeMap('[data-step-id]', 'stepId')
  pendingVisibleSteps.forEach((node, id) => {
    if (!nodes.has(id)) { observer?.unobserve(node); pendingVisibleSteps.delete(id) }
  })
  nodes.forEach(node => observer?.observe(node))
  let entryIndex = 0
  newIds.forEach(id => {
    const node = nodes.get(id)
    const delay = node && isVisibleStep(node) ? entryIndex++ * tokenNumber('--motion-stagger-fast') : 0
    queueStepEntry(node, delay)
  })
  changes.forEach(step => {
    const node = nodes.get(step.id)
    const badge = node?.querySelector('.step-status')
    if (didComplete(step.before, step.status) && !stampedSteps.has(step.id)) {
      stampedSteps.add(step.id)
      if (node && isVisibleStep(node)) animateStamp(badge)
    } else if (node && isVisibleStep(node) && step.before && step.before !== step.status) animateStatusChange(badge)
  })
  syncStepScans()
}

async function handleWorkers(next) {
  if (!mountedReady) return
  const changes = next.map(worker => ({ ...worker, before: previousWorkerStatus.get(worker.name) }))
  next.forEach(worker => previousWorkerStatus.set(worker.name, worker.status))
  await nextTick()
  if (!mountedReady) return
  const nodes = nodeMap('[data-worker-name]', 'workerName')
  changes.forEach(worker => {
    const card = nodes.get(worker.name)
    const badge = card?.querySelector('.worker-status')
    if (!seenWorkers.has(worker.name)) {
      seenWorkers.add(worker.name)
      if (activeStatuses.has(worker.status) && card && !prefersReducedMotion) {
        gsap.fromTo(card, { opacity: 0, y: tokenLength('--motion-distance-tab') }, { opacity: 1, y: 0, duration: tokenDuration('--dur-live-phase'), ease: tokenEase('--ease-gsap-reveal'), clearProps: 'opacity,transform' })
      }
    }
    if (didComplete(worker.before, worker.status) && !stampedWorkers.has(worker.name)) {
      stampedWorkers.add(worker.name)
      animateStamp(badge)
    } else if (worker.before && worker.before !== worker.status) animateStatusChange(badge)
  })
}

function handleMotionPreference() {
  prefersReducedMotion = motionPreference.matches
  const lowPower = Boolean(navigator.connection?.saveData) || (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4)
  allowsAmbientMotion = !prefersReducedMotion && Boolean(pointerPreference?.matches) && !lowPower
  if (prefersReducedMotion && root.value) {
    budgetTweens.forEach(tween => tween.kill())
    budgetTweens.clear()
    Object.assign(budgetDisplay, budgetSnapshot.value)
    gsap.killTweensOf(root.value.querySelectorAll('*'))
    root.value.querySelectorAll('[data-step-id], [data-worker-name], .badge, .phase-value, [data-budget-key]').forEach(clearNodeMotion)
    pendingVisibleSteps.clear()
  }
  syncAmbientMotion()
}

onMounted(async () => {
  rootElement = root.value
  motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
  pointerPreference = window.matchMedia('(hover: hover) and (pointer: fine)')
  prefersReducedMotion = motionPreference.matches
  const lowPower = Boolean(navigator.connection?.saveData) || (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4)
  allowsAmbientMotion = !prefersReducedMotion && pointerPreference.matches && !lowPower
  motionPreference.addEventListener('change', handleMotionPreference)
  pointerPreference.addEventListener('change', handleMotionPreference)
  observer = new IntersectionObserver(entries => {
    let entryIndex = 0
    entries.forEach(entry => {
      if (entry.isIntersecting && pendingVisibleSteps.has(entry.target.dataset.stepId)) animateStepEntry(entry.target, entryIndex++ * tokenNumber('--motion-stagger-fast'))
    })
    syncStepScans()
  }, { threshold: tokenNumber('--motion-live-visible-threshold') })

  stepSnapshot.value.forEach(step => {
    seenSteps.add(step.id)
    previousStepStatus.set(step.id, step.status)
  })
  workerSnapshot.value.forEach(worker => {
    seenWorkers.add(worker.name)
    previousWorkerStatus.set(worker.name, worker.status)
  })
  Object.assign(budgetDisplay, budgetSnapshot.value)
  mountedReady = true
  const began = Date.now()
  timer = window.setInterval(() => { elapsed.value = Math.floor((Date.now() - began) / 1000) }, 1000)
  await nextTick()
  if (!mountedReady) return
  nodeMap('[data-step-id]', 'stepId').forEach(node => observer.observe(node))
  syncAmbientMotion()

  stopWatchers.push(
    watch(stepSnapshot, handleSteps, { flush: 'post' }),
    watch(workerSnapshot, handleWorkers, { flush: 'post' }),
    watch(budgetSnapshot, next => Object.entries(next).forEach(([key, value]) => animateBudget(key, value)), { flush: 'post' }),
    watch(() => props.phase, (next, previous) => { if (next !== previous) nextTick(() => { if (mountedReady) animatePhase() }) }, { flush: 'post' }),
    watch(() => props.running, syncAmbientMotion, { flush: 'post' })
  )
})

onBeforeUnmount(() => {
  mountedReady = false
  if (rootElement) gsap.killTweensOf(rootElement.querySelectorAll('*'))
})

onUnmounted(() => {
  mountedReady = false
  updateGeneration++
  window.clearInterval(timer)
  stopWatchers.forEach(stop => stop())
  motionPreference?.removeEventListener('change', handleMotionPreference)
  pointerPreference?.removeEventListener('change', handleMotionPreference)
  observer?.disconnect()
  orbitTween?.kill()
  progressTween?.kill()
  phaseTween?.kill()
  scanTweens.forEach(tween => tween.kill())
  budgetTweens.forEach(tween => tween.kill())
  pendingVisibleSteps.clear()
  if (rootElement) gsap.killTweensOf(rootElement.querySelectorAll('*'))
  rootElement = null
})
</script>

<template>
  <section ref="root" class="run-progress card" aria-busy="true" aria-label="调查加载过程">
    <header class="progress-heading">
      <span class="progress-orbit" aria-hidden="true"><span></span></span>
      <span class="progress-kicker">{{ replaying ? '档案回放' : running || starting ? '调查进行中' : '读取档案' }}</span>
      <span class="elapsed">已等待 {{ elapsed }} 秒</span>
    </header>
    <h2 role="status">{{ replaying ? '正在回放调查档案' : starting ? '正在启动调查' : running ? '调查正在进行' : '正在读取调查记录' }}</h2>
    <p class="progress-description">{{ replaying ? '正在读取归档来源并重建证据与引用，完成后展示本次结果。' : starting ? '正在提交调查任务，等待服务端确认。' : running ? '正在收集与验证材料，调查结束后展示证据链与报告。' : '正在加载所选运行的来源、证据和报告。' }}</p>

    <div class="progress live-progress" aria-hidden="true"><span class="live-progress-bar"></span></div>

    <div v-if="starting || (running && !replaying && !steps.length)" class="waiting-docket" role="status">
      <span class="waiting-index">CASE INTAKE</span>
      <div class="waiting-rule"></div><div class="waiting-rule waiting-rule-short"></div>
      <p>{{ quant ? '正在处理冻结材料；已完成内容会在收尾时归入报告。' : starting ? '正在登记调查任务…' : '档案已建立，等待首条研究记录归入。' }}</p>
    </div>

    <div v-if="running && !replaying && Object.keys(workers).length" class="worker-grid">
      <article v-for="(status, name, index) in workers" :key="name" class="record worker-record" :class="{ active: isCurrent(status) }" :data-worker-name="name">
        <span class="record-copy"><span class="record-index">AGENT {{ formatIndex(index) }}</span>{{ workerName(name) }}</span>
        <span class="badge worker-status" :class="statusClass(status)">{{ statusText(status) }}</span>
      </article>
    </div>

    <dl v-if="running && !replaying && budget" class="progress-budget" aria-label="本次调查预算使用情况">
      <div><dt>搜索</dt><dd><span data-budget-key="search">{{ budgetDisplay.search }}</span> / {{ budget.max_search_calls }}</dd></div>
      <div><dt>抓取</dt><dd><span data-budget-key="fetch">{{ budgetDisplay.fetch }}</span> / {{ budget.max_fetch_calls }}</dd></div>
      <div><dt>模型调用</dt><dd><span data-budget-key="model">{{ budgetDisplay.model }}</span> / {{ budget.max_model_calls }}</dd></div>
    </dl>
    <template v-if="running && !replaying && !starting">
      <div class="phase-row"><span>当前阶段</span><span class="badge probable phase-value" aria-live="polite">{{ phase ? label(phase) : '等待执行' }}</span></div>
      <ol v-if="quant" class="quant-phases" aria-label="量化执行阶段"><li v-for="name in ['取数','冻结快照','确定性计算','证据核验','成稿']" :key="name" :aria-current="phase === name ? 'step' : undefined">{{ name }}</li></ol>
      <ol v-if="steps.length" class="progress-steps">
        <li v-for="(step, index) in steps" :key="step.step_id" class="record progress-step" :class="{ current: isCurrent(step.status) }" :data-step-id="stepId(step, index)">
          <span class="step-scan" aria-hidden="true"></span>
          <span class="record-copy"><span class="record-index">EXHIBIT {{ formatIndex(index) }}</span>{{ label(step.agent_role) }} · {{ label(step.step_type) }}</span>
          <span class="badge step-status" :class="statusClass(step.status)">{{ statusText(step.status) }}</span>
        </li>
      </ol>
    </template>
    <small>结果将在本次运行结束后自动更新。</small>
  </section>
</template>

<style scoped>
.run-progress { margin-block: var(--space-8); overflow: hidden; }
.progress-heading, .phase-row, .worker-record, .progress-step { display: flex; align-items: center; gap: var(--space-3); }
.progress-heading { margin-bottom: var(--space-5); }
.progress-orbit { display: grid; width: var(--space-5); height: var(--space-5); place-items: center; border: var(--stroke-thin) solid var(--border-strong); border-top-color: var(--accent); border-radius: var(--radius-full); }
.progress-orbit > span { width: var(--space-1); height: var(--space-1); border-radius: var(--radius-full); background: var(--accent); }
.progress-kicker, .record-index, .waiting-index { color: var(--accent); font-family: var(--font-mono); font-size: var(--font-size-overline); font-weight: var(--font-weight-overline); letter-spacing: var(--letter-spacing-overline); }
.elapsed { margin-left: auto; color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-size-caption); font-variant-numeric: tabular-nums; }
h2 { margin: 0 0 var(--space-3); font-family: var(--font-display); font-size: var(--font-size-h2); font-weight: var(--font-weight-h2); line-height: var(--line-height-h2); }
.progress-description { max-width: var(--reading-max-width); color: var(--text-secondary); font-family: var(--font-serif); font-size: var(--font-size-body-lg); line-height: var(--line-height-body-lg); }
.live-progress { height: var(--live-progress-height); margin-block: var(--space-6); border-radius: 0; }
.live-progress::before, .live-progress::after { position: absolute; inset-block: 0; width: var(--stroke-thin); background: var(--border-strong); content: ''; }
.live-progress::before { left: var(--space-8); }
.live-progress::after { right: var(--space-8); }
.live-progress-bar { display: block; width: var(--live-progress-sweep-width); height: 100%; background: var(--accent); }
.waiting-docket { display: grid; gap: var(--space-2); margin-block: var(--space-6); padding: var(--space-5); border: var(--stroke-thin) solid var(--border-default); background: var(--bg-surface); }
.waiting-docket p { margin: var(--space-2) 0 0; color: var(--text-secondary); font-family: var(--font-serif); }
.waiting-rule { width: 100%; height: var(--stroke-thin); background: var(--border-default); }
.waiting-rule-short { width: var(--live-progress-sweep-width); }
.worker-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(calc(var(--space-32) + var(--space-16)), 1fr)); gap: var(--space-3); margin-block: var(--space-6); }
.worker-record, .progress-step { position: relative; justify-content: space-between; min-width: 0; padding: var(--space-3) var(--space-4); overflow: hidden; }
.worker-record.active, .progress-step.current { border-color: var(--border-strong); background: var(--bg-elevated); }
.worker-record + .worker-record, .progress-step + .progress-step { margin-top: 0; }
.record-copy { min-width: 0; color: var(--text-secondary); font-size: var(--font-size-small); line-height: var(--line-height-small); overflow-wrap: anywhere; }
.record-index { display: block; margin-bottom: var(--space-1); color: var(--text-muted); font-size: var(--font-size-caption); }
.progress-budget { display: flex; flex-wrap: wrap; gap: var(--space-3) var(--space-6); margin: 0; color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-size-caption); font-variant-numeric: tabular-nums; line-height: var(--line-height-caption); }
.progress-budget div { display: flex; gap: var(--space-2); }
.progress-budget dt, .progress-budget dd { margin: 0; }
.progress-budget dd { color: var(--text-secondary); }
.progress-budget [data-budget-key] { display: inline-block; min-width: var(--space-4); text-align: right; }
.phase-row { justify-content: space-between; margin-block: var(--space-5) var(--space-3); color: var(--text-muted); font-size: var(--font-size-small); }
.phase-value { display: inline-block; }
.quant-phases { display:flex; flex-wrap:wrap; gap:var(--space-3); padding:0; list-style:none; color:var(--text-muted); font-size:var(--font-size-small); }
.quant-phases li[aria-current='step'] { color:var(--accent); border-bottom:1px solid currentColor; }
.progress-steps { display: grid; max-height: calc(var(--space-32) + var(--space-32)); gap: var(--space-2); margin: 0 0 var(--space-5); padding: 0; overflow-y: auto; list-style: none; }
.step-scan { position: absolute; bottom: 0; left: 0; width: var(--live-progress-sweep-width); height: var(--live-progress-height); background: var(--accent); opacity: 0; pointer-events: none; }
small { color: var(--text-muted); font-size: var(--font-size-caption); font-style: italic; }
@media (max-width: 47.999rem) {
  .run-progress { margin-block: var(--space-6); }
  .progress-heading { flex-wrap: wrap; }
  .elapsed { width: 100%; margin-left: calc(var(--space-5) + var(--space-3)); }
  .worker-grid { grid-template-columns: minmax(0, 1fr); }
  .worker-record, .progress-step { align-items: flex-start; }
  .progress-budget { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (prefers-reduced-motion: reduce) {
  .run-progress, .run-progress * { transition: none !important; }
  .live-progress-bar { width: var(--live-progress-complete-width); }
  .step-scan { display: none; }
}
</style>
