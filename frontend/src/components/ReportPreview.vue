<script setup>
defineProps({
  findings: {
    type: Array,
    required: true
  }
})
</script>

<template>
  <section class="report-preview-section">
    <slot name="heading"></slot>
    <div class="report-page">
      <div class="rp-heading">
        <div class="rp-section-num">CHAPTER III</div>
        <h2 class="rp-title">已验证关键事实</h2>
        <p class="rp-subtitle">Verified Key Findings</p>
      </div>

      <div
        v-for="(section, sIndex) in findings"
        :key="sIndex"
        class="rp-section"
      >
        <h3 class="rp-section-title">{{ section.section }}</h3>
        <div
          v-for="(finding, fIndex) in section.findings"
          :key="fIndex"
          class="finding-block"
        >
          <p class="finding-text">
            {{ finding.text }}
            <span
              v-for="cite in finding.citations"
              :key="cite"
              class="cite"
            >[{{ cite }}]</span>
          </p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.report-preview-section {
  margin-bottom: 56px;
}

.report-page {
  background: white;
  max-width: 720px;
  margin: 0 auto;
  padding: 64px 72px;
  box-shadow:
    0 1px 2px var(--paper-shadow),
    0 12px 40px rgba(60, 45, 20, 0.08);
  position: relative;
}

.report-page::before {
  content: '';
  position: absolute;
  left: 20px;
  top: 24px;
  bottom: 24px;
  width: 1px;
  background: linear-gradient(180deg, transparent, var(--paper-edge) 10%, var(--paper-edge) 90%, transparent);
}

.report-page::after {
  content: '';
  position: absolute;
  right: 20px;
  top: 24px;
  bottom: 24px;
  width: 1px;
  background: linear-gradient(180deg, transparent, var(--paper-edge) 10%, var(--paper-edge) 90%, transparent);
}

.rp-heading {
  text-align: center;
  margin-bottom: 40px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--paper-edge);
  position: relative;
}

.rp-heading::after {
  content: '';
  position: absolute;
  bottom: -5px;
  left: 50%;
  transform: translateX(-50%);
  width: 40px;
  height: 1px;
  background: var(--accent);
}

.rp-section-num {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.15em;
  color: var(--accent);
  margin-bottom: 12px;
}

.rp-title {
  font-family: var(--font-display);
  font-size: 26px;
  font-weight: 600;
  color: var(--ink-black);
  margin-bottom: 8px;
}

.rp-subtitle {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 14px;
  color: var(--ink-muted);
}

.rp-section {
  margin-bottom: 28px;
}

.rp-section:last-child {
  margin-bottom: 0;
}

.rp-section-title {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 600;
  color: var(--ink-deep);
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--paper-edge);
}

.finding-block {
  margin-bottom: 20px;
  padding: 16px 20px;
  background: var(--paper-base);
  border-left: 2px solid var(--status-verified);
  transition: all 0.35s var(--ease-out);
}

.finding-block:hover {
  background: var(--accent-pale);
  border-left-color: var(--accent);
}

.finding-text {
  font-family: var(--font-serif);
  font-size: 15px;
  line-height: 1.85;
  color: var(--ink-deep);
}

.cite {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent);
  cursor: pointer;
  vertical-align: super;
  line-height: 0;
  padding: 0 2px;
  margin: 0 1px;
  transition: all 0.25s var(--ease-out);
  position: relative;
}

.cite::after {
  content: '';
  position: absolute;
  bottom: -2px;
  left: 0;
  width: 100%;
  height: 1px;
  background: var(--accent);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 0.35s var(--ease-out);
}

.cite:hover {
  color: var(--accent);
}

.cite:hover::after {
  transform: scaleX(1);
}
</style>
