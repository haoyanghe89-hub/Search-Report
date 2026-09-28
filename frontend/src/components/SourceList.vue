<script setup>
defineProps({
  sources: {
    type: Array,
    required: true
  }
})
</script>

<template>
  <section class="sources-section">
    <slot name="heading"></slot>
    <ol class="reference-list">
      <li
        v-for="source in sources"
        :key="source.id"
        class="ref-item"
      >
        <div class="ref-title">{{ source.titleCn }}</div>
        <div class="ref-source">{{ source.source }} · {{ source.sourceEn }}</div>
        <div class="ref-meta">
          <span class="ref-tag">{{ source.typeText }}</span>
          <span class="ref-quality">{{ source.quality }}</span>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.sources-section {
  margin-bottom: 0;
}

.reference-list {
  counter-reset: reference;
  list-style: none;
  padding: 0;
}

.ref-item {
  counter-increment: reference;
  padding: 20px 0 20px 52px;
  border-bottom: 1px solid var(--paper-edge);
  position: relative;
  cursor: pointer;
  transition: all 0.35s var(--ease-out);
}

.ref-item:last-child {
  border-bottom: none;
}

.ref-item::before {
  content: '[' counter(reference) ']';
  position: absolute;
  left: 0;
  top: 22px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--accent);
  font-weight: 500;
}

.ref-item:hover {
  padding-left: 58px;
}

.ref-item:hover::before {
  color: var(--ink-black);
  font-weight: 600;
}

.ref-title {
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 600;
  color: var(--ink-deep);
  margin-bottom: 6px;
  line-height: 1.5;
}

.ref-source {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 13px;
  color: var(--ink-muted);
  margin-bottom: 8px;
}

.ref-meta {
  display: flex;
  align-items: center;
  gap: 16px;
}

.ref-tag {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 2px 8px;
  border: 1px solid var(--paper-edge);
  color: var(--ink-muted);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  border-radius: 2px;
}

.ref-quality {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 12px;
  color: var(--ink-faint);
}
</style>
