<script setup>
defineProps({
  evidence: {
    type: Array,
    required: true
  }
})

function stanceText(stance) {
  const map = {
    SUPPORTS: '支持',
    CONTRADICTS: '反驳',
    NEUTRAL: '中性'
  }
  return map[stance] || stance
}

function stanceClass(stance) {
  const map = {
    SUPPORTS: 'support',
    CONTRADICTS: 'contradict',
    NEUTRAL: 'neutral'
  }
  return map[stance] || 'neutral'
}

function entailmentText(status) {
  const map = {
    ENTAILED: '蕴含',
    PARTIAL: '部分支持',
    CONTRADICTORY: '矛盾',
    UNRELATED: '无关'
  }
  return map[status] || status
}
</script>

<template>
  <div class="evidence-list">
    <div
      v-for="item in evidence"
      :key="item.evidence_id"
      class="evidence-card"
    >
      <div class="evidence-head">
        <span class="evidence-id">{{ item.evidence_id }}</span>
        <span class="evidence-source">{{ item.sourceTitle }}</span>
      </div>
      <div class="evidence-content">{{ item.content }}</div>
      <div class="evidence-foot">
        <div class="evidence-meta">
          <span class="meta-tag" :class="stanceClass(item.stance)">
            {{ stanceText(item.stance) }}
          </span>
          <span class="meta-tag subtle">
            {{ entailmentText(item.entailment_status) }}
          </span>
          <span class="meta-tag light">
            {{ item.extractor_name }}
          </span>
        </div>
        <div class="evidence-confidence">
          <span class="conf-label">置信度</span>
          <div class="conf-bar">
            <div
              class="conf-fill"
              :style="{ width: (item.confidence * 100).toFixed(0) + '%' }"
            ></div>
          </div>
          <span class="conf-value">{{ item.confidence.toFixed(2) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.evidence-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.evidence-card {
  padding: 24px 28px;
  border: 1px solid var(--paper-edge);
  background: var(--paper-base);
  transition: all 0.4s var(--ease-out);
  position: relative;
}

.evidence-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--status-verified);
  transition: all 0.4s var(--ease-out);
}

.evidence-card:hover {
  border-color: var(--accent-line);
  transform: translateX(4px);
  background: var(--accent-pale);
}

.evidence-card:hover::before {
  width: 4px;
  background: var(--accent);
}

.evidence-head {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 14px;
}

.evidence-id {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  letter-spacing: 0.05em;
}

.evidence-source {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 13px;
  color: var(--ink-muted);
}

.evidence-content {
  font-family: var(--font-serif);
  font-size: 15px;
  line-height: 1.8;
  color: var(--ink-deep);
  margin-bottom: 16px;
  padding-left: 16px;
  border-left: 2px solid var(--paper-edge);
}

.evidence-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 14px;
  border-top: 1px solid var(--paper-edge);
}

.evidence-meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.meta-tag {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 3px 10px;
  border: 1px solid;
  border-radius: 2px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.meta-tag.support {
  color: var(--status-verified);
  border-color: currentColor;
}

.meta-tag.contradict {
  color: var(--status-disputed);
  border-color: currentColor;
}

.meta-tag.neutral {
  color: var(--status-unverified);
  border-color: currentColor;
}

.meta-tag.subtle {
  color: var(--ink-muted);
  border-color: var(--paper-edge);
  text-transform: none;
  letter-spacing: 0;
}

.meta-tag.light {
  color: var(--ink-faint);
  border-color: var(--paper-edge);
  font-style: italic;
  text-transform: none;
  letter-spacing: 0;
}

.evidence-confidence {
  display: flex;
  align-items: center;
  gap: 10px;
}

.conf-label {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-faint);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.conf-bar {
  width: 80px;
  height: 2px;
  background: var(--paper-edge);
  position: relative;
}

.conf-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.6s var(--ease-out);
}

.conf-value {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-muted);
  min-width: 36px;
  text-align: right;
}
</style>
