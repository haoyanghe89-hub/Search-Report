<script setup>
defineProps({
  chain: {
    type: Array,
    required: true
  }
})
</script>

<template>
  <section class="evidence-chain-section">
    <slot name="heading"></slot>
    <div class="chain-book">
      <div class="chain-book-title">— Evidence Chain —</div>
      <div class="chain-numbers">
        <div
          v-for="(step, index) in chain"
          :key="index"
          class="chain-step"
        >
          <div class="step-number">{{ step.number }}</div>
          <div class="step-label">{{ step.label }}</div>
          <div class="step-sub">{{ step.sub }}</div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.evidence-chain-section {
  margin-bottom: 56px;
}

.chain-book {
  background: var(--paper-warm);
  border: 1px solid var(--paper-edge);
  padding: 36px 48px;
  position: relative;
}

.chain-book::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: linear-gradient(180deg, var(--accent-light), var(--accent));
}

.chain-book-title {
  font-family: var(--font-display);
  font-size: 13px;
  font-style: italic;
  font-weight: 500;
  color: var(--ink-muted);
  margin-bottom: 24px;
  letter-spacing: 0.05em;
}

.chain-numbers {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}

.chain-step {
  flex: 1;
  text-align: center;
  position: relative;
}

.chain-step:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 28px;
  right: -12px;
  width: 24px;
  height: 1px;
  background: var(--paper-edge);
}

.step-number {
  font-family: var(--font-display);
  font-size: 42px;
  font-weight: 500;
  color: var(--ink-black);
  line-height: 1;
  margin-bottom: 12px;
  font-variant-numeric: oldstyle-nums;
  transition: all 0.4s var(--ease-out);
}

.chain-step:hover .step-number {
  color: var(--accent);
  transform: translateY(-2px);
}

.step-label {
  font-family: var(--font-serif);
  font-weight: 600;
  color: var(--ink-soft);
  letter-spacing: 0.08em;
  font-size: 11px;
  text-transform: uppercase;
}

.step-sub {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 12px;
  color: var(--ink-faint);
  margin-top: 4px;
}
</style>
