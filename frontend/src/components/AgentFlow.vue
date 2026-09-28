<script setup>
import { ref, onMounted } from 'vue'

defineProps({
  agents: {
    type: Array,
    required: true
  }
})

const timelineRef = ref(null)

// 数字计数动画（如果需要的话）
</script>

<template>
  <section class="agent-flow-section">
    <slot name="heading"></slot>
    <div class="agent-timeline" ref="timelineRef">
      <div
        v-for="agent in agents"
        :key="agent.id"
        class="agent-node"
        :class="agent.status"
      >
        <div class="agent-dot">{{ agent.initial }}</div>
        <div class="agent-label">{{ agent.label }}</div>
        <div class="agent-role">{{ agent.role }}</div>
        <div class="agent-state">{{ agent.statusText }}</div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.agent-flow-section {
  margin-bottom: 56px;
}

.agent-timeline {
  display: flex;
  align-items: stretch;
  position: relative;
  padding: 24px 0;
}

.agent-timeline::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 40px;
  right: 40px;
  height: 1px;
  background: var(--paper-edge);
}

.agent-node {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  cursor: pointer;
}

.agent-dot {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: var(--paper-base);
  border: 1px solid var(--paper-edge);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
  transition: all 0.5s var(--ease-out);
  position: relative;
  z-index: 1;
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 600;
  font-size: 18px;
  color: var(--ink-muted);
}

.agent-node:hover .agent-dot {
  transform: scale(1.08);
  border-color: var(--accent-light);
  color: var(--accent);
  box-shadow: 0 4px 20px var(--paper-shadow);
}

.agent-node.completed .agent-dot {
  background: var(--paper-warm);
  border-color: var(--status-verified);
  color: var(--status-verified);
}

.agent-node.active .agent-dot {
  background: var(--accent-pale);
  border-color: var(--accent);
  color: var(--accent);
  animation: gentlePulse 3s ease-in-out infinite;
}

@keyframes gentlePulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(139, 90, 43, 0.15); }
  50% { box-shadow: 0 0 0 10px rgba(139, 90, 43, 0); }
}

.agent-label {
  font-family: var(--font-serif);
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-deep);
  margin-bottom: 4px;
  text-align: center;
}

.agent-role {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 12px;
  color: var(--ink-faint);
  text-align: center;
}

.agent-state {
  margin-top: 8px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-faint);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.agent-node.active .agent-state {
  color: var(--accent);
}

.agent-node.completed .agent-state {
  color: var(--status-verified);
}
</style>
