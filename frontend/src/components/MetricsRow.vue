<script setup>
import { ref, onMounted, watch } from 'vue'

const props = defineProps({
  metrics: {
    type: Object,
    required: true
  }
})

const animatedValues = ref({})
const isVisible = ref(false)
const rowRef = ref(null)

function animateNumbers() {
  const keys = ['sources', 'evidence', 'claims', 'conflicts']
  const targets = {}

  keys.forEach(key => {
    targets[key] = props.metrics[key]
    animatedValues.value[key] = 0
  })

  // 置信度特殊处理
  if (props.metrics.confidence) {
    const confNum = parseInt(props.metrics.confidence)
    animatedValues.value.confidence = 0
    targets.confidence = confNum
  }

  const duration = 1200
  const startTime = performance.now()

  function update(now) {
    const progress = Math.min((now - startTime) / duration, 1)
    const eased = 1 - Math.pow(1 - progress, 3)

    keys.forEach(key => {
      animatedValues.value[key] = Math.round(targets[key] * eased)
    })

    if (props.metrics.confidence) {
      animatedValues.value.confidence = Math.round(targets.confidence * eased) + '%'
    }

    if (progress < 1) {
      requestAnimationFrame(update)
    }
  }

  requestAnimationFrame(update)
}

onMounted(() => {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting && !isVisible.value) {
        isVisible.value = true
        animateNumbers()
      }
    })
  }, { threshold: 0.5 })

  if (rowRef.value) {
    observer.observe(rowRef.value)
  }
})

watch(() => props.metrics, () => {
  if (isVisible.value) {
    animateNumbers()
  }
})
</script>

<template>
  <div class="metrics-row" ref="rowRef">
    <div class="metric-col">
      <div class="metric-big">{{ animatedValues.sources ?? metrics.sources }}</div>
      <div class="metric-name">有效来源</div>
      <div class="metric-note">{{ metrics.sourcesNote }}</div>
    </div>
    <div class="metric-col">
      <div class="metric-big">{{ animatedValues.evidence ?? metrics.evidence }}</div>
      <div class="metric-name">证据片段</div>
      <div class="metric-note">{{ metrics.evidenceNote }}</div>
    </div>
    <div class="metric-col">
      <div class="metric-big">{{ animatedValues.claims ?? metrics.claims }}</div>
      <div class="metric-name">事实声明</div>
      <div class="metric-note">{{ metrics.claimsNote }}</div>
    </div>
    <div class="metric-col">
      <div class="metric-big">{{ animatedValues.conflicts ?? metrics.conflicts }}</div>
      <div class="metric-name">冲突记录</div>
      <div class="metric-note">{{ metrics.conflictsNote }}</div>
    </div>
    <div class="metric-col">
      <div class="metric-big">{{ animatedValues.confidence ?? metrics.confidence }}</div>
      <div class="metric-name">平均置信度</div>
      <div class="metric-note">{{ metrics.confidenceNote }}</div>
    </div>
  </div>
</template>

<style scoped>
.metrics-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 0;
  margin-bottom: 56px;
  border-top: 1px solid var(--paper-edge);
  border-bottom: 1px solid var(--paper-edge);
}

.metric-col {
  padding: 32px 24px;
  text-align: center;
  position: relative;
  cursor: pointer;
  transition: background 0.4s var(--ease-out);
}

.metric-col:not(:last-child)::after {
  content: '';
  position: absolute;
  right: 0;
  top: 24px;
  bottom: 24px;
  width: 1px;
  background: var(--paper-edge);
  transition: all 0.4s var(--ease-out);
}

.metric-col:hover {
  background: var(--accent-pale);
}

.metric-col:hover::after {
  background: var(--accent-line);
}

.metric-big {
  font-family: var(--font-display);
  font-size: 56px;
  font-weight: 500;
  line-height: 1;
  color: var(--ink-black);
  margin-bottom: 12px;
  font-variant-numeric: oldstyle-nums;
  font-variation-settings: "opsz" 144;
  transition: transform 0.4s var(--ease-out), color 0.4s var(--ease-out);
}

.metric-col:hover .metric-big {
  transform: scale(1.05);
  color: var(--accent);
}

.metric-name {
  font-family: var(--font-serif);
  font-size: 13px;
  color: var(--ink-muted);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 6px;
}

.metric-note {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 12px;
  color: var(--ink-faint);
}
</style>
