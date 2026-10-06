<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { tokenDuration, tokenEase, tokenLength, tokenNumber, tokenValue } from '../utils/motionTokens.js'

gsap.registerPlugin(ScrollTrigger)

const props = defineProps({
  agents: {
    type: Array,
    required: true
  }
})

const sectionRef = ref(null)
const timelineRef = ref(null)
const pathRef = ref(null)
let revealTimeline = null
let motionPreference = null
let animatedNodes = []

function preparePath(drawFromStart) {
  if (!pathRef.value) return
  const length = pathRef.value.getTotalLength()
  gsap.set(pathRef.value, {
    strokeDasharray: length,
    strokeDashoffset: drawFromStart ? length : 0
  })
}

function showFinalState() {
  animatedNodes = timelineRef.value ? [...timelineRef.value.querySelectorAll('.agent-node')] : []
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
  animatedNodes = timelineRef.value ? [...timelineRef.value.querySelectorAll('.agent-node')] : []
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
    scrollTrigger: {
      trigger: timelineRef.value,
      start: `top ${tokenValue('--scroll-trigger-start')}`,
      once: true
    }
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
  createReveal()
})

watch(() => props.agents, async () => {
  await nextTick()
  createReveal()
})

onUnmounted(() => {
  motionPreference?.removeEventListener('change', handleMotionPreference)
  destroyReveal()
})
</script>

<template>
  <section ref="sectionRef" class="agent-flow-section">
    <slot name="heading"></slot>
    <div ref="timelineRef" class="agent-timeline">
      <svg class="agent-connector" viewBox="0 0 4 100" preserveAspectRatio="none" aria-hidden="true">
        <path ref="pathRef" class="agent-connector-path" d="M 2 0 L 2 100" />
      </svg>
      <article
        v-for="agent in agents"
        :key="agent.id"
        class="agent-node"
        :class="agent.status"
      >
        <div class="agent-marker" aria-hidden="true">
          <span class="agent-dot">{{ agent.initial }}</span>
        </div>
        <div class="agent-card">
          <div class="agent-card-heading">
            <h3 class="agent-label">{{ agent.label }}</h3>
            <span class="agent-state">{{ agent.statusText }}</span>
          </div>
          <p class="agent-role">{{ agent.role }}</p>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.agent-flow-section {
  margin-bottom: var(--space-16);
}

.agent-timeline {
  position: relative;
  display: grid;
  gap: var(--space-3);
}

.agent-connector {
  position: absolute;
  z-index: 0;
  top: var(--space-5);
  bottom: var(--space-5);
  left: calc(var(--space-5) - (var(--space-1) / 2));
  width: var(--space-1);
  height: calc(100% - var(--space-10));
  overflow: visible;
}

.agent-connector-path {
  fill: none;
  stroke: var(--border-strong);
  stroke-width: var(--stroke-thin);
  vector-effect: non-scaling-stroke;
}

.agent-node {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: var(--space-10) minmax(0, 1fr);
  align-items: center;
  gap: var(--space-4);
}

.agent-marker {
  display: grid;
  place-items: center;
}

.agent-dot {
  display: grid;
  width: var(--space-10);
  height: var(--space-10);
  place-items: center;
  border: calc(var(--space-1) / 4) solid var(--border-default);
  border-radius: var(--radius-full);
  background: var(--bg-elevated);
  color: var(--text-muted);
  font-family: var(--font-display);
  font-size: var(--font-size-h4);
  font-style: italic;
  font-weight: var(--font-weight-h4);
  transition: transform var(--dur-sm) var(--ease-standard), border-color var(--dur-sm) var(--ease-standard);
}

.agent-card {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-4) var(--space-5);
  border: calc(var(--space-1) / 4) solid var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  transition: transform var(--dur-sm) var(--ease-standard), border-color var(--dur-sm) var(--ease-standard), background var(--dur-sm) var(--ease-standard);
}

.agent-card-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.agent-label {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: var(--font-size-h4);
  font-weight: var(--font-weight-h4);
  line-height: var(--line-height-h4);
}

.agent-role {
  margin: 0;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-size-caption);
  letter-spacing: var(--letter-spacing-caption);
  line-height: var(--line-height-caption);
}

.agent-state {
  display: inline-flex;
  align-items: center;
  min-height: var(--space-6);
  padding: 0 var(--space-2);
  border: calc(var(--space-1) / 4) solid currentColor;
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-caption);
  line-height: var(--line-height-caption);
  white-space: nowrap;
}

.agent-node:hover .agent-card {
  border-color: var(--border-strong);
  background: var(--bg-elevated);
}

.agent-node:hover .agent-dot {
  border-color: var(--border-strong);
}

.agent-node.completed .agent-dot,
.agent-node.completed .agent-state {
  border-color: var(--success);
  color: var(--success);
}

.agent-node.active .agent-dot,
.agent-node.active .agent-state {
  border-color: var(--accent);
  color: var(--accent);
}

.agent-node.failed .agent-dot,
.agent-node.failed .agent-state {
  border-color: var(--danger);
  color: var(--danger);
}

</style>
