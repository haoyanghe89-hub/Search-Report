<script setup>
defineProps({
  items: {
    type: Array,
    required: true
  }
})
</script>

<template>
  <div class="timeline">
    <div
      v-for="(item, index) in items"
      :key="index"
      class="tl-item"
    >
      <div class="tl-date">{{ item.date }}</div>
      <div class="tl-event">{{ item.event }}</div>
      <div class="tl-desc">{{ item.description }}</div>
    </div>
  </div>
</template>

<style scoped>
.timeline {
  position: relative;
  padding-left: 32px;
}

.timeline::before {
  content: '';
  position: absolute;
  left: 10px;
  top: 8px;
  bottom: 8px;
  width: 1px;
  background: var(--paper-edge);
}

.tl-item {
  position: relative;
  padding-bottom: 28px;
}

.tl-item:last-child {
  padding-bottom: 0;
}

.tl-item::before {
  content: '';
  position: absolute;
  left: -28px;
  top: 6px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--paper-base);
  border: 1.5px solid var(--accent);
  transition: all 0.35s var(--ease-out);
}

.tl-item:hover::before {
  background: var(--accent);
  transform: scale(1.2);
}

.tl-date {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent);
  letter-spacing: 0.05em;
  margin-bottom: 6px;
}

.tl-event {
  font-family: var(--font-serif);
  font-size: 16px;
  font-weight: 600;
  color: var(--ink-deep);
  margin-bottom: 6px;
}

.tl-desc {
  font-family: var(--font-serif);
  font-size: 14px;
  color: var(--ink-muted);
  line-height: 1.7;
}
</style>
