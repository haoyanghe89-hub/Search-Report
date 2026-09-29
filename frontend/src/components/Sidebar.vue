<script setup>
defineProps({
  loading: Boolean,
  replaying: Boolean,
  busy: Boolean,
  cases: {
    type: Array,
    required: true
  },
  activeCaseId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['select', 'new-investigation', 'refresh', 'replay'])

function statusColor(status) {
  const colors = {
    verified: 'var(--status-verified)',
    investigating: 'var(--status-probable)',
    disputed: 'var(--status-disputed)',
    draft: 'var(--status-unverified)'
  }
  return colors[status] || colors.draft
}
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-title">调查档案 <button class="refresh-archive" :disabled="loading" @click="emit('refresh')">刷新</button></div><p v-if="loading" role="status" class="sidebar-note">正在读取档案…</p><p v-else-if="!cases.length" class="sidebar-note">暂无调查档案</p>

    <div class="case-list">
      <div
        v-for="item in cases"
        :key="item.id"
        role="button"
        :tabindex="busy || replaying ? -1 : 0"
        :aria-disabled="busy || replaying"
        :aria-current="item.id === activeCaseId ? 'page' : undefined"
        @keydown.enter="emit('select', item.id)"
        @keydown.space.prevent="emit('select', item.id)"
        class="case-card"
        :class="{ active: item.id === activeCaseId }"
        @click="emit('select', item.id)"
      >
        <div class="case-id">{{ item.id }}</div>
        <div class="case-name">{{ item.name }}</div>
        <div class="case-meta">
          <div class="case-status">
            <span
              class="status-indicator"
              :style="{ backgroundColor: statusColor(item.status) }"
            ></span>
            {{ item.statusText }}
          </div>
          <span v-if="item.claimsCount > 0">{{ item.claimsCount }}项</span>
          <span v-else-if="item.tag">{{ item.tag }}</span>
        </div>
      </div>
    </div>

    <div class="sidebar-replay"><span class="eyebrow">内置案例 · 离线回放</span><p>东巴勒斯坦列车脱轨事故</p><button :disabled="replaying || busy" @click="emit('replay')">{{ replaying ? '正在回放…' : '运行案例回放 →' }}</button><small>使用归档来源与人工整理的证据关系。</small></div>
    <button class="new-case-btn" :disabled="replaying || busy" @click="emit('new-investigation')">
      <span class="plus">+</span>
      调查新主题
    </button>
  </aside>
</template>

<style scoped>
.sidebar {
  background: var(--paper-warm);
  border-right: 1px solid var(--paper-edge);
  padding: 32px 24px;
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
  z-index: 10;
}

.sidebar-title {
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  color: var(--ink-faint);
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--paper-edge);
  position: relative;
}

.sidebar-title::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 0;
  width: 24px;
  height: 1px;
  background: var(--accent);
}

.case-list {
  flex: 1;
  overflow-y: auto;
  margin: 0 -8px;
  padding: 0 8px;
}

.case-list::-webkit-scrollbar {
  width: 3px;
}

.case-list::-webkit-scrollbar-track {
  background: transparent;
}

.case-list::-webkit-scrollbar-thumb {
  background: var(--paper-edge);
  border-radius: 2px;
}

.case-card {
  padding: 16px 14px;
  margin-bottom: 2px;
  cursor: pointer;
  position: relative;
  border-radius: 4px;
  transition: all 0.4s var(--ease-out);
}

.case-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%) scaleY(0);
  width: 2px;
  height: 60%;
  background: var(--accent);
  border-radius: 1px;
  transition: transform 0.4s var(--ease-out);
  transform-origin: center;
}

.case-card:hover {
  background: var(--accent-pale);
}

.case-card:hover::before {
  transform: translateY(-50%) scaleY(1);
}

.case-card.active {
  background: var(--accent-pale);
}

.case-card.active::before {
  transform: translateY(-50%) scaleY(1);
}

.case-id {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-faint);
  letter-spacing: 0.08em;
  margin-bottom: 6px;
}

.case-name {
  font-family: var(--font-serif);
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-deep);
  line-height: 1.4;
  margin-bottom: 8px;
  transition: color 0.3s var(--ease-out);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}

.case-card.active .case-name {
  color: var(--accent);
}

.case-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  color: var(--ink-faint);
  font-family: var(--font-mono);
}

.case-status {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.new-case-btn {
  margin-top: 16px;
  padding: 12px 16px;
  border: 1px dashed var(--paper-edge);
  border-radius: 4px;
  background: transparent;
  color: var(--ink-muted);
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.35s var(--ease-out);
  text-align: left;
  display: flex;
  align-items: center;
  gap: 8px;
}

.new-case-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-pale);
}

.new-case-btn .plus {
  font-size: 16px;
  font-style: normal;
  font-weight: 400;
  transition: transform 0.35s var(--ease-out);
}

.new-case-btn:hover .plus {
  transform: rotate(90deg);
}
</style>
