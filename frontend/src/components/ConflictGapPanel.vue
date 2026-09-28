<script setup>
defineProps({
  conflicts: {
    type: Array,
    required: true
  },
  gaps: {
    type: Array,
    default: () => []
  }
})

function severityClass(severity) {
  const map = {
    HIGH: 'high',
    MODERATE: 'moderate',
    LOW: 'low'
  }
  return map[severity] || 'low'
}

function statusClass(status) {
  const map = {
    RESOLVED: 'resolved',
    OPEN: 'open',
    IN_PROGRESS: 'progress'
  }
  return map[status] || 'open'
}
</script>

<template>
  <div class="conflicts-gaps">
    <!-- 冲突记录 -->
    <div class="section-block">
      <h3 class="block-title">
        <span class="block-num">A</span>
        冲突记录
      </h3>
      <div class="conflict-list">
        <div
          v-for="conflict in conflicts"
          :key="conflict.conflict_id"
          class="conflict-card"
        >
          <div class="conflict-head">
            <div class="conflict-ids">
              <span class="conflict-id">{{ conflict.conflict_id }}</span>
              <span class="conflict-type">{{ conflict.conflictTypeText }}</span>
            </div>
            <span
              class="status-badge"
              :class="statusClass(conflict.status)"
            >
              {{ conflict.statusText }}
            </span>
          </div>
          <div class="conflict-desc">{{ conflict.description || '存在来源间的信息不一致' }}</div>
          <div class="conflict-severity">
            <span class="sev-label">严重程度</span>
            <span class="sev-dots">
              <span
                v-for="i in 3"
                :key="i"
                class="sev-dot"
                :class="{ active: i <= (conflict.severity === 'HIGH' ? 3 : conflict.severity === 'MODERATE' ? 2 : 1), [severityClass(conflict.severity)]: true }"
              ></span>
            </span>
            <span class="sev-text">{{ conflict.severityText }}</span>
          </div>
          <div v-if="conflict.resolution_summary" class="resolution-box">
            <div class="resolution-label">解决方案</div>
            <div class="resolution-text">{{ conflict.resolution_summary }}</div>
          </div>
          <div class="conflict-foot">
            <div class="possible-causes">
              <span class="causes-label">可能原因：</span>
              <span v-for="(cause, i) in conflict.possible_causes" :key="i" class="cause-tag">
                {{ cause }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 研究缺口 -->
    <div class="section-block">
      <h3 class="block-title">
        <span class="block-num">B</span>
        研究缺口
      </h3>
      <div class="gap-list">
        <div
          v-for="gap in gaps"
          :key="gap.gap_id"
          class="gap-card"
        >
          <div class="gap-head">
            <span class="gap-type">{{ gap.gapTypeText }}</span>
            <span class="gap-status" :class="statusClass(gap.status)">
              {{ gap.statusText }}
            </span>
          </div>
          <div class="gap-reason">{{ gap.reason }}</div>
          <div class="gap-suggestions">
            <div class="suggestions-label">建议行动</div>
            <ul class="suggestions-list">
              <li v-for="(action, i) in gap.suggested_actions" :key="i">
                {{ action }}
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.conflicts-gaps {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 48px;
}

.section-block {
  margin-bottom: 0;
}

.block-title {
  display: flex;
  align-items: center;
  gap: 14px;
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 600;
  color: var(--ink-black);
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--paper-edge);
}

.block-num {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--accent-pale);
  color: var(--accent);
  font-family: var(--font-display);
  font-style: italic;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 冲突卡片 */
.conflict-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.conflict-card {
  padding: 24px 28px;
  border: 1px solid var(--paper-edge);
  background: var(--paper-base);
  transition: all 0.4s var(--ease-out);
}

.conflict-card:hover {
  border-color: var(--accent-line);
  background: var(--accent-pale);
}

.conflict-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}

.conflict-ids {
  display: flex;
  align-items: center;
  gap: 12px;
}

.conflict-id {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent);
  font-weight: 600;
}

.conflict-type {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 13px;
  color: var(--ink-muted);
}

.status-badge {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 3px 10px;
  border: 1px solid;
  border-radius: 2px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.status-badge.resolved {
  color: var(--status-verified);
  border-color: currentColor;
}

.status-badge.open {
  color: var(--status-disputed);
  border-color: currentColor;
}

.status-badge.progress {
  color: var(--status-probable);
  border-color: currentColor;
}

.conflict-desc {
  font-family: var(--font-serif);
  font-size: 15px;
  line-height: 1.75;
  color: var(--ink-deep);
  margin-bottom: 16px;
}

.conflict-severity {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.sev-label {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-faint);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.sev-dots {
  display: flex;
  gap: 4px;
}

.sev-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--paper-edge);
  transition: all 0.3s var(--ease-out);
}

.sev-dot.active.high {
  background: var(--status-disputed);
}

.sev-dot.active.moderate {
  background: var(--status-probable);
}

.sev-dot.active.low {
  background: var(--status-verified);
}

.sev-text {
  font-family: var(--font-serif);
  font-size: 12px;
  color: var(--ink-muted);
}

.resolution-box {
  padding: 14px 18px;
  background: var(--paper-warm);
  border-left: 2px solid var(--status-verified);
  margin-bottom: 14px;
}

.resolution-label {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--status-verified);
  margin-bottom: 6px;
}

.resolution-text {
  font-family: var(--font-serif);
  font-size: 13px;
  color: var(--ink-soft);
  line-height: 1.7;
}

.conflict-foot {
  padding-top: 12px;
  border-top: 1px solid var(--paper-edge);
}

.possible-causes {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.causes-label {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 12px;
  color: var(--ink-faint);
}

.cause-tag {
  font-family: var(--font-serif);
  font-size: 12px;
  padding: 2px 8px;
  background: var(--paper-warm);
  color: var(--ink-soft);
  border-radius: 2px;
}

/* 缺口卡片 */
.gap-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.gap-card {
  padding: 24px 28px;
  border: 1px solid var(--paper-edge);
  background: var(--paper-base);
  transition: all 0.4s var(--ease-out);
}

.gap-card:hover {
  border-color: var(--accent-line);
  background: var(--accent-pale);
}

.gap-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.gap-type {
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 600;
  color: var(--ink-deep);
}

.gap-status {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 3px 10px;
  border: 1px solid;
  border-radius: 2px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.gap-status.open {
  color: var(--status-disputed);
  border-color: currentColor;
}

.gap-status.progress {
  color: var(--status-probable);
  border-color: currentColor;
}

.gap-reason {
  font-family: var(--font-serif);
  font-size: 14px;
  line-height: 1.75;
  color: var(--ink-soft);
  margin-bottom: 16px;
  font-style: italic;
}

.gap-suggestions {
  padding-top: 12px;
  border-top: 1px solid var(--paper-edge);
}

.suggestions-label {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
  margin-bottom: 8px;
}

.suggestions-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.suggestions-list li {
  font-family: var(--font-serif);
  font-size: 13px;
  color: var(--ink-soft);
  padding: 4px 0 4px 16px;
  position: relative;
  line-height: 1.6;
}

.suggestions-list li::before {
  content: '→';
  position: absolute;
  left: 0;
  color: var(--accent);
  font-size: 11px;
}

@media (max-width: 900px) {
  .conflicts-gaps {
    grid-template-columns: 1fr;
    gap: 40px;
  }
}
</style>
