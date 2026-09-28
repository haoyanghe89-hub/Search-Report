<script setup>
defineProps({
  review: {
    type: Object,
    required: true
  }
})

function severityClass(severity) {
  const map = {
    CRITICAL: 'critical',
    WARNING: 'warning',
    INFO: 'info'
  }
  return map[severity] || 'info'
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}
</script>

<template>
  <div class="review-panel">
    <!-- 审核状态概览 -->
    <div class="review-overview">
      <div class="overview-card status-card">
        <div class="ov-label">审核状态</div>
        <div class="ov-value approved">{{ review.reviewStatusText }}</div>
        <div class="ov-note">政策版本 {{ review.policy_version }}</div>
      </div>
      <div class="overview-card release-card">
        <div class="ov-label">发布状态</div>
        <div class="ov-value released">{{ review.releaseStatusText }}</div>
        <div class="ov-note">报告 ID: {{ review.report_id }}</div>
      </div>
      <div class="overview-card findings-card">
        <div class="ov-label">审核发现</div>
        <div class="findings-count">
          <div class="count-item">
            <span class="count-num zero">{{ review.hard_finding_count }}</span>
            <span class="count-label">严重问题</span>
          </div>
          <div class="count-divider"></div>
          <div class="count-item">
            <span class="count-num">{{ review.governance_finding_count }}</span>
            <span class="count-label">治理建议</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 审核发现列表 -->
    <div class="findings-section">
      <h3 class="section-title">
        <span class="title-num">§</span>
        审核发现详情
      </h3>
      <div class="finding-list">
        <div
          v-for="finding in review.findings"
          :key="finding.finding_id"
          class="finding-card"
          :class="severityClass(finding.severity)"
        >
          <div class="finding-head">
            <div class="finding-severity" :class="severityClass(finding.severity)">
              <span class="sev-icon">
                {{ finding.severity === 'CRITICAL' ? '!' : finding.severity === 'WARNING' ? '⚠' : 'ℹ' }}
              </span>
              {{ finding.severityText }}
            </div>
            <div class="finding-validator">{{ finding.validatorText }}</div>
          </div>
          <div class="finding-code">{{ finding.code }}</div>
          <div class="finding-detail">{{ finding.detail }}</div>
        </div>
      </div>
    </div>

    <!-- 审核历史 -->
    <div class="history-section">
      <h3 class="section-title">
        <span class="title-num">§</span>
        审核历史
      </h3>
      <div class="history-timeline">
        <div
          v-for="item in review.history"
          :key="item.review_id"
          class="history-item"
        >
          <div class="history-dot"></div>
          <div class="history-content">
            <div class="history-head">
              <span class="history-decision approve">{{ item.decisionText }}</span>
              <span class="history-date">{{ formatDate(item.created_at) }}</span>
            </div>
            <div class="history-reviewer">{{ item.reviewerName }}</div>
            <div class="history-reason">{{ item.reason }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.review-panel {
  max-width: 900px;
  margin: 0 auto;
}

/* 概览卡片 */
.review-overview {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  margin-bottom: 48px;
}

.overview-card {
  padding: 28px 24px;
  background: var(--paper-warm);
  border: 1px solid var(--paper-edge);
  text-align: center;
  position: relative;
  transition: all 0.4s var(--ease-out);
}

.overview-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px var(--paper-shadow);
}

.ov-label {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-faint);
  margin-bottom: 12px;
}

.ov-value {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 600;
  margin-bottom: 8px;
}

.ov-value.approved {
  color: var(--status-verified);
}

.ov-value.released {
  color: var(--accent);
}

.ov-note {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 12px;
  color: var(--ink-faint);
}

.findings-count {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 20px;
}

.count-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.count-num {
  font-family: var(--font-display);
  font-size: 32px;
  font-weight: 600;
  color: var(--status-disputed);
  font-variant-numeric: oldstyle-nums;
}

.count-num.zero {
  color: var(--status-verified);
}

.count-label {
  font-family: var(--font-serif);
  font-size: 11px;
  color: var(--ink-muted);
}

.count-divider {
  width: 1px;
  height: 36px;
  background: var(--paper-edge);
}

/* 章节标题 */
.section-title {
  display: flex;
  align-items: baseline;
  gap: 12px;
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 600;
  color: var(--ink-black);
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--paper-edge);
}

.title-num {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--accent);
}

/* 审核发现 */
.findings-section {
  margin-bottom: 48px;
}

.finding-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.finding-card {
  padding: 20px 24px;
  border: 1px solid var(--paper-edge);
  background: var(--paper-base);
  transition: all 0.4s var(--ease-out);
  position: relative;
}

.finding-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--status-unverified);
}

.finding-card.critical::before {
  background: var(--status-disputed);
}

.finding-card.warning::before {
  background: var(--status-probable);
}

.finding-card.info::before {
  background: var(--status-verified);
}

.finding-card:hover {
  border-color: var(--accent-line);
  background: var(--accent-pale);
  transform: translateX(4px);
}

.finding-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.finding-severity {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.sev-icon {
  font-size: 14px;
  font-style: normal;
}

.finding-severity.critical {
  color: var(--status-disputed);
}

.finding-severity.warning {
  color: var(--status-probable);
}

.finding-severity.info {
  color: var(--status-verified);
}

.finding-validator {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 13px;
  color: var(--ink-muted);
}

.finding-code {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-faint);
  margin-bottom: 10px;
}

.finding-detail {
  font-family: var(--font-serif);
  font-size: 14px;
  line-height: 1.75;
  color: var(--ink-soft);
}

/* 审核历史 */
.history-timeline {
  position: relative;
  padding-left: 28px;
}

.history-timeline::before {
  content: '';
  position: absolute;
  left: 8px;
  top: 8px;
  bottom: 8px;
  width: 1px;
  background: var(--paper-edge);
}

.history-item {
  position: relative;
  padding-bottom: 28px;
}

.history-item:last-child {
  padding-bottom: 0;
}

.history-dot {
  position: absolute;
  left: -24px;
  top: 6px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--paper-base);
  border: 2px solid var(--status-verified);
  transition: all 0.35s var(--ease-out);
}

.history-item:hover .history-dot {
  background: var(--status-verified);
  transform: scale(1.2);
}

.history-content {
  padding: 16px 20px;
  background: var(--paper-warm);
  border: 1px solid var(--paper-edge);
  transition: all 0.4s var(--ease-out);
}

.history-content:hover {
  border-color: var(--accent-line);
  background: var(--accent-pale);
}

.history-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.history-decision {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 600;
}

.history-decision.approve {
  color: var(--status-verified);
}

.history-date {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-faint);
}

.history-reviewer {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 13px;
  color: var(--ink-muted);
  margin-bottom: 8px;
}

.history-reason {
  font-family: var(--font-serif);
  font-size: 14px;
  line-height: 1.7;
  color: var(--ink-soft);
}

@media (max-width: 900px) {
  .review-overview {
    grid-template-columns: 1fr;
    gap: 16px;
  }
}
</style>
