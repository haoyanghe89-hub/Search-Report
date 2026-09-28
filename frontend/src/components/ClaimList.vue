<script setup>
defineProps({
  claims: {
    type: Array,
    required: true
  }
})

function statusClass(status) {
  return `status-text ${status}`
}

function confidencePercent(confidence) {
  return (confidence * 100).toFixed(0) + '%'
}
</script>

<template>
  <div class="claim-list">
    <div
      v-for="claim in claims"
      :key="claim.id"
      class="claim-card"
    >
      <div class="claim-head">
        <span class="claim-type">{{ claim.typeEn }}</span>
        <span :class="statusClass(claim.status)">{{ claim.statusText }}</span>
      </div>
      <div class="claim-statement">{{ claim.statement }}</div>
      <div class="claim-foot">
        <span class="claim-evidence">{{ claim.evidenceCount }}份支持证据</span>
        <div class="confidence">
          <div class="confidence-bar">
            <div
              class="confidence-fill"
              :style="{ width: confidencePercent(claim.confidence) }"
            ></div>
          </div>
          <span class="confidence-val">{{ claim.confidence.toFixed(2) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.claim-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.claim-card {
  padding: 20px 24px;
  border: 1px solid var(--paper-edge);
  background: var(--paper-base);
  cursor: pointer;
  transition: all 0.4s var(--ease-out);
  position: relative;
}

.claim-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 2px;
  background: transparent;
  transition: all 0.4s var(--ease-out);
}

.claim-card:hover {
  border-color: var(--accent-line);
  background: var(--accent-pale);
  transform: translateX(4px);
}

.claim-card:hover::before {
  background: var(--accent);
}

.claim-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.claim-type {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ink-faint);
}

.claim-statement {
  font-family: var(--font-serif);
  font-size: 15px;
  line-height: 1.7;
  color: var(--ink-deep);
  margin-bottom: 14px;
}

.claim-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 12px;
  border-top: 1px solid var(--paper-edge);
}

.claim-evidence {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-muted);
}

.confidence {
  display: flex;
  align-items: center;
  gap: 10px;
}

.confidence-bar {
  width: 60px;
  height: 2px;
  background: var(--paper-edge);
  position: relative;
}

.confidence-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.6s var(--ease-out);
}

.confidence-val {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-muted);
}

.status-text {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 3px 8px;
  border: 1px solid;
  border-radius: 2px;
}

.status-text.verified {
  color: var(--status-verified);
  border-color: currentColor;
}

.status-text.probable {
  color: var(--status-probable);
  border-color: currentColor;
}

.status-text.disputed {
  color: var(--status-disputed);
  border-color: currentColor;
}

.status-text.unverified {
  color: var(--status-unverified);
  border-color: currentColor;
}
</style>
