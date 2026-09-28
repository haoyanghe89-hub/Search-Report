<script setup>
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
</script>

<template>
  <div class="section-heading">
    <span class="section-number">{{ sectionNum }}</span>
    <span class="section-name">{{ sectionName }}</span>
    <span v-if="sectionDesc" class="section-desc">{{ sectionDesc }}</span>
  </div>
</template>

<style scoped>
.section-heading {
  display: flex;
  align-items: baseline;
  gap: 16px;
  margin-bottom: 32px;
}

.section-number {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--accent);
  letter-spacing: 0.1em;
}

.section-name {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 600;
  color: var(--ink-black);
  letter-spacing: -0.01em;
}

.section-desc {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 14px;
  color: var(--ink-faint);
  margin-left: auto;
}
</style>
