<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { tokenDuration, tokenEase, tokenLength, tokenValue } from '../utils/motionTokens.js'

gsap.registerPlugin(ScrollTrigger)

defineProps({
  sectionNum: {
    type: String,
    required: true
  },
  sectionName: {
    type: String,
    required: true
  },
  sectionDesc: {
    type: String,
    default: ''
  }
})

const headingRef = ref(null)
const headingContentRef = ref(null)
const ruleRef = ref(null)
let revealTimeline = null
let motionPreference = null

function showFinalState() {
  if (headingContentRef.value) gsap.set(headingContentRef.value, { opacity: 1, y: 0 })
  if (ruleRef.value) gsap.set(ruleRef.value, { scaleX: 1 })
}

function destroyReveal() {
  revealTimeline?.scrollTrigger?.kill()
  revealTimeline?.kill()
  revealTimeline = null
  if (headingContentRef.value) gsap.killTweensOf(headingContentRef.value)
  if (ruleRef.value) gsap.killTweensOf(ruleRef.value)
}

function createReveal() {
  destroyReveal()
  if (!headingRef.value || !headingContentRef.value || !ruleRef.value) return

  if (motionPreference?.matches) {
    showFinalState()
    return
  }

  gsap.set(headingContentRef.value, { opacity: 0, y: tokenLength('--motion-distance-section') })
  gsap.set(ruleRef.value, { scaleX: 0, transformOrigin: 'left center' })
  revealTimeline = gsap.timeline({
    defaults: { overwrite: 'auto' },
    scrollTrigger: {
      trigger: headingRef.value,
      start: `top ${tokenValue('--scroll-trigger-start')}`,
      once: true
    }
  })
  revealTimeline
    .to(headingContentRef.value, { opacity: 1, y: 0, duration: tokenDuration('--dur-section'), ease: tokenEase('--ease-gsap-reveal') })
    .to(ruleRef.value, { scaleX: 1, duration: tokenDuration('--dur-section'), ease: tokenEase('--ease-gsap-standard') }, '<')
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

onUnmounted(() => {
  motionPreference?.removeEventListener('change', handleMotionPreference)
  destroyReveal()
})
</script>

<template>
  <header ref="headingRef" class="section-heading">
    <div ref="headingContentRef" class="section-heading-content">
      <span class="section-kicker">SECTION {{ sectionNum }}</span>
      <div class="section-heading-row">
        <h2 class="section-name">{{ sectionName }}</h2>
        <p v-if="sectionDesc" class="section-desc">{{ sectionDesc }}</p>
      </div>
    </div>
    <span ref="ruleRef" class="section-rule" aria-hidden="true"></span>
  </header>
</template>

<style scoped>
.section-heading {
  display: grid;
  gap: var(--space-4);
  margin-bottom: var(--space-8);
}

.section-heading-content {
  display: grid;
  gap: var(--space-3);
}

.section-kicker {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-size-overline);
  font-weight: var(--font-weight-overline);
  letter-spacing: var(--letter-spacing-overline);
  line-height: var(--line-height-overline);
}

.section-heading-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-4);
}

.section-name {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: var(--font-size-section);
  font-weight: var(--font-weight-section);
  letter-spacing: var(--letter-spacing-section);
  line-height: var(--line-height-section);
}

.section-desc {
  margin: 0 0 0 auto;
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.section-rule {
  display: block;
  width: 100%;
  height: calc(var(--space-1) / 4);
  background: var(--border-default);
  transform-origin: left center;
}

</style>
