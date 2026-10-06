<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { tokenDuration, tokenEase, tokenLength, tokenNumber, tokenValue } from '../utils/motionTokens.js'

gsap.registerPlugin(ScrollTrigger)

const props = defineProps({
  items: {
    type: Array,
    required: true
  }
})

const timelineRef = ref(null)
const pathRef = ref(null)
let revealTimeline = null
let motionPreference = null
let animatedItems = []

function preparePath(drawFromStart) {
  if (!pathRef.value) return
  const length = pathRef.value.getTotalLength()
  gsap.set(pathRef.value, { strokeDasharray: length, strokeDashoffset: drawFromStart ? length : 0 })
}

function showFinalState() {
  animatedItems = timelineRef.value ? [...timelineRef.value.querySelectorAll('.tl-item')] : []
  preparePath(false)
  if (animatedItems.length) gsap.set(animatedItems, { opacity: 1, y: 0 })
}

function destroyReveal() {
  revealTimeline?.scrollTrigger?.kill()
  revealTimeline?.kill()
  revealTimeline = null
  if (pathRef.value) gsap.killTweensOf(pathRef.value)
  if (animatedItems.length) gsap.killTweensOf(animatedItems)
}

function createReveal() {
  destroyReveal()
  animatedItems = timelineRef.value ? [...timelineRef.value.querySelectorAll('.tl-item')] : []
  if (!timelineRef.value || !pathRef.value || !animatedItems.length) {
    showFinalState()
    return
  }
  if (motionPreference?.matches) {
    showFinalState()
    return
  }

  preparePath(true)
  gsap.set(animatedItems, { opacity: 0, y: tokenLength('--motion-distance-section') })
  revealTimeline = gsap.timeline({
    scrollTrigger: { trigger: timelineRef.value, start: `top ${tokenValue('--scroll-trigger-start')}`, once: true }
  })
  revealTimeline
    .to(pathRef.value, { strokeDashoffset: 0, duration: tokenDuration('--dur-draw'), ease: tokenEase('--ease-gsap-standard') })
    .to(animatedItems, { opacity: 1, y: 0, duration: tokenDuration('--dur-section'), stagger: tokenNumber('--motion-stagger-fast'), ease: tokenEase('--ease-gsap-reveal') }, '<')
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
  createReveal()
})

watch(() => props.items, async () => {
  await nextTick()
  createReveal()
})

onUnmounted(() => {
  motionPreference?.removeEventListener('change', handleMotionPreference)
  destroyReveal()
})
</script>

<template>
  <div ref="timelineRef" class="timeline">
    <svg class="timeline-axis" viewBox="0 0 4 100" preserveAspectRatio="none" aria-hidden="true">
      <path ref="pathRef" class="timeline-axis-path" d="M 2 0 L 2 100" />
    </svg>
    <article v-for="(item, index) in items" :key="index" class="tl-item">
      <span class="tl-marker" aria-hidden="true"></span>
      <div class="tl-content">
        <div class="tl-date"><span>CASE TIME {{ String(index + 1).padStart(2, '0') }}</span><time>{{ item.date }}</time></div>
        <h3 class="tl-event">{{ item.event }}</h3>
        <p class="tl-desc">{{ item.description }}</p>
      </div>
    </article>
  </div>
</template>

<style scoped>
.timeline { position: relative; display: grid; gap: var(--space-3); }
.timeline-axis { position: absolute; z-index: 0; top: var(--space-3); bottom: var(--space-3); left: calc(var(--space-3) - (var(--space-1) / 2)); width: var(--space-1); height: calc(100% - var(--space-6)); overflow: visible; }
.timeline-axis-path { fill: none; stroke: var(--border-strong); stroke-width: var(--stroke-thin); vector-effect: non-scaling-stroke; }
.tl-item { position: relative; z-index: 1; display: grid; grid-template-columns: var(--space-6) minmax(0, 1fr); align-items: start; gap: var(--space-4); }
.tl-marker { width: var(--space-4); height: var(--space-4); margin: var(--space-2) auto 0; border: var(--stroke-thin) solid var(--border-strong); border-radius: var(--radius-full); background: var(--bg-surface); transition: border-color var(--dur-sm) var(--ease-standard), background var(--dur-sm) var(--ease-standard); }
.tl-content { padding: var(--space-4); border: calc(var(--space-1) / 4) solid var(--border-default); border-radius: var(--radius-lg); background: var(--bg-surface); transition: border-color var(--dur-sm) var(--ease-standard), background var(--dur-sm) var(--ease-standard); }
.tl-item:hover .tl-marker { border-color: var(--text-muted); background: var(--bg-elevated); }
.tl-item:hover .tl-content { border-color: var(--border-strong); background: var(--bg-elevated); }
.tl-date { display: flex; margin-bottom: var(--space-2); align-items: center; justify-content: space-between; gap: var(--space-3); color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-size-overline); letter-spacing: var(--letter-spacing-overline); line-height: var(--line-height-overline); font-variant-numeric: tabular-nums; }
.tl-date time { letter-spacing: var(--letter-spacing-caption); text-align: right; }
.tl-event { margin: 0 0 var(--space-1); color: var(--text-primary); font-family: var(--font-display); font-size: var(--font-size-h4); font-weight: var(--font-weight-h4); line-height: var(--line-height-h4); }
.tl-desc { margin: 0; color: var(--text-muted); font-family: var(--font-serif); font-size: var(--font-size-body); line-height: var(--line-height-body); }
</style>
