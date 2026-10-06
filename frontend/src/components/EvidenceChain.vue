<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { tokenDuration, tokenEase, tokenLength, tokenNumber, tokenValue } from '../utils/motionTokens.js'

gsap.registerPlugin(ScrollTrigger)

defineProps({
  chain: {
    type: Array,
    required: true
  }
})

const sectionRef = ref(null)
const trackRef = ref(null)
const lineRef = ref(null)
const pathRef = ref(null)
let revealTimeline = null
let motionPreference = null
let animatedNodes = []
let resizeFrame = null

function positionLine() {
  const markers = trackRef.value ? [...trackRef.value.querySelectorAll('.chain-marker')] : []
  if (!lineRef.value || markers.length < 2) return
  const trackBounds = trackRef.value.getBoundingClientRect()
  const firstBounds = markers[0].getBoundingClientRect()
  const lastBounds = markers.at(-1).getBoundingClientRect()
  const left = firstBounds.left + firstBounds.width / 2 - trackBounds.left
  const right = lastBounds.left + lastBounds.width / 2 - trackBounds.left
  gsap.set(lineRef.value, { left, width: right - left })
}

function scheduleLinePosition() {
  if (resizeFrame !== null) return
  resizeFrame = window.requestAnimationFrame(() => {
    resizeFrame = null
    positionLine()
    ScrollTrigger.refresh()
  })
}

function preparePath(drawFromStart) {
  if (!pathRef.value) return
  const length = pathRef.value.getTotalLength()
  gsap.set(pathRef.value, { strokeDasharray: length, strokeDashoffset: drawFromStart ? length : 0 })
}

function showFinalState() {
  animatedNodes = trackRef.value ? [...trackRef.value.querySelectorAll('.chain-step')] : []
  positionLine()
  preparePath(false)
  if (animatedNodes.length) gsap.set(animatedNodes, { opacity: 1, y: 0 })
}

function destroyReveal() {
  revealTimeline?.scrollTrigger?.kill()
  revealTimeline?.kill()
  revealTimeline = null
  if (pathRef.value) gsap.killTweensOf(pathRef.value)
  if (animatedNodes.length) gsap.killTweensOf(animatedNodes)
}

function createReveal() {
  destroyReveal()
  positionLine()
  animatedNodes = trackRef.value ? [...trackRef.value.querySelectorAll('.chain-step')] : []
  if (!sectionRef.value || !pathRef.value || !animatedNodes.length) {
    showFinalState()
    return
  }
  if (motionPreference?.matches) {
    showFinalState()
    return
  }

  preparePath(true)
  gsap.set(animatedNodes, { opacity: 0, y: tokenLength('--motion-distance-section') })
  revealTimeline = gsap.timeline({
    scrollTrigger: { trigger: trackRef.value, start: `top ${tokenValue('--scroll-trigger-start')}`, once: true }
  })
  revealTimeline
    .to(pathRef.value, { strokeDashoffset: 0, duration: tokenDuration('--dur-draw'), ease: tokenEase('--ease-gsap-standard') })
    .to(animatedNodes, { opacity: 1, y: 0, duration: tokenDuration('--dur-section'), stagger: tokenNumber('--motion-stagger-fast'), ease: tokenEase('--ease-gsap-reveal') }, '<')
}

function handleMotionPreference() {
  if (motionPreference.matches) {
    destroyReveal()
    showFinalState()
    return
  }
  createReveal()
}

onMounted(() => {
  motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
  motionPreference.addEventListener('change', handleMotionPreference)
  window.addEventListener('resize', scheduleLinePosition, { passive: true })
  createReveal()
})

onUnmounted(() => {
  motionPreference?.removeEventListener('change', handleMotionPreference)
  window.removeEventListener('resize', scheduleLinePosition)
  if (resizeFrame !== null) window.cancelAnimationFrame(resizeFrame)
  destroyReveal()
  if (lineRef.value) gsap.killTweensOf(lineRef.value)
})
</script>

<template>
  <section ref="sectionRef" class="evidence-chain-section">
    <slot name="heading"></slot>
    <div class="chain-book">
      <div class="chain-book-title">Evidence chain · source to conclusion</div>
      <div class="chain-viewport">
        <div ref="trackRef" class="chain-track">
          <svg ref="lineRef" class="chain-line" viewBox="0 0 100 4" preserveAspectRatio="none" aria-hidden="true">
            <path ref="pathRef" class="chain-path" d="M 0 2 L 100 2" />
          </svg>
          <article v-for="(step, index) in chain" :key="index" class="chain-step">
            <span class="chain-marker" aria-hidden="true"></span>
            <strong class="step-number" :data-overview-count="step.number">{{ step.number }}</strong>
            <span class="step-label">{{ step.label }}</span>
            <span class="step-sub" :class="{ badge: index === 2, verified: index === 2 }">{{ step.sub }}</span>
          </article>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.evidence-chain-section { margin-bottom: var(--space-16); }
.chain-book { padding: var(--space-8); border: calc(var(--space-1) / 4) solid var(--border-default); border-radius: var(--radius-xl); background: var(--bg-surface); }
.chain-book-title { margin-bottom: var(--space-6); color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-size-overline); font-weight: var(--font-weight-overline); letter-spacing: var(--letter-spacing-overline); line-height: var(--line-height-overline); }
.chain-viewport { overflow-x: auto; padding-bottom: var(--space-2); }
.chain-track { position: relative; display: grid; min-width: calc(var(--space-32) * 4); grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-4); }
.chain-line { position: absolute; z-index: 0; top: calc(var(--space-3) - (var(--space-1) / 2)); height: var(--space-1); overflow: visible; }
.chain-path { fill: none; stroke: var(--border-strong); stroke-width: var(--stroke-thin); vector-effect: non-scaling-stroke; }
.chain-step { position: relative; z-index: 1; display: grid; justify-items: center; gap: var(--space-2); text-align: center; }
.chain-marker { width: var(--space-6); height: var(--space-6); border: var(--stroke-thin) solid var(--border-strong); border-radius: var(--radius-full); background: var(--bg-surface); }
.step-number { margin-top: var(--space-2); color: var(--text-primary); font-family: var(--font-display); font-size: var(--font-size-h1); font-weight: var(--font-weight-h1); font-variant-numeric: tabular-nums; letter-spacing: var(--letter-spacing-h1); line-height: var(--line-height-h1); transition: color var(--dur-sm) var(--ease-standard), transform var(--dur-sm) var(--ease-standard); }
.chain-step:hover .step-number { color: var(--text-primary); }
.step-label { color: var(--text-secondary); font-family: var(--font-sans); font-size: var(--font-size-overline); font-weight: var(--font-weight-overline); letter-spacing: var(--letter-spacing-overline); line-height: var(--line-height-overline); }
.step-sub { color: var(--text-muted); font-family: var(--font-serif); font-size: var(--font-size-caption); font-style: italic; line-height: var(--line-height-caption); }
.step-sub.badge { background: transparent; font-family: var(--font-sans); font-style: normal; }
</style>
