<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { chineseText } from '../composables/chinese.js'
import { useTheme } from '../composables/useTheme.js'

const props = defineProps({
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

const emit = defineEmits(['select', 'new-investigation', 'create-investigation', 'delete-investigation', 'refresh', 'replay'])
const { theme, toggleTheme } = useTheme()
const mobileOpen = ref(false)

function closeMobile() {
  mobileOpen.value = false
}

function selectCase(id) {
  if (props.busy || props.replaying) return
  emit('select', id)
  closeMobile()
}

function onKeydown(event) {
  if (event.key === 'Escape') closeMobile()
}

watch(() => props.activeCaseId, closeMobile)
watch(mobileOpen, (open) => {
  document.documentElement.style.overflow = open ? 'hidden' : ''
})
onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  document.documentElement.style.overflow = ''
})

function statusColor(status) {
  const colors = {
    verified: 'var(--success)',
    investigating: 'var(--warning)',
    disputed: 'var(--danger)',
    draft: 'var(--text-muted)'
  }
  return colors[status] || colors.draft
}
</script>

<template>
  <aside class="sidebar" :class="{ 'drawer-open': mobileOpen }">
    <div class="mobile-sidebar-bar">
      <button class="mobile-menu-trigger" type="button" :aria-expanded="mobileOpen" aria-controls="folio-sidebar-panel" aria-label="打开调查档案" @click="mobileOpen = true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
      </button>
      <span>数字卷宗</span>
    </div>
    <button v-if="mobileOpen" class="sidebar-backdrop" type="button" aria-label="关闭调查档案" @click="closeMobile"></button>
    <div id="folio-sidebar-panel" class="sidebar-panel">
      <button class="mobile-drawer-close quiet-button" type="button" aria-label="关闭调查档案" @click="closeMobile">关闭</button>
      <header class="sidebar-brand">
      <span class="brand-index" aria-hidden="true">DF / ARCHIVE</span>
      <p class="brand-title">数字卷宗</p>
      <p class="brand-subtitle">Digital Folio</p>
      </header>

    <div class="archive-heading">
      <span>调查档案</span>
      <button class="refresh-archive" :disabled="busy || replaying" @click="emit('create-investigation'); closeMobile()">新建调查</button>
      <button class="refresh-archive" :disabled="loading" @click="emit('refresh')">刷新</button>
    </div>
    <p v-if="loading" role="status" class="sidebar-note">正在读取档案…</p>
    <p v-else-if="!cases.length" class="sidebar-note">暂无调查档案</p>

    <div class="case-list">
      <div
        v-for="item in cases"
        :key="item.id"
        class="case-card"
        :class="{ active: item.id === activeCaseId }"
      >
        <button class="case-select" :disabled="busy || replaying" :aria-current="item.id === activeCaseId ? 'page' : undefined" @click="selectCase(item.id)">
        <div class="case-id">{{ item.id }}</div>
        <div class="case-name">{{ chineseText(item.name) }}</div>
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
        </button>
        <button class="case-delete" type="button" :aria-label="`删除卷宗：${chineseText(item.name)}`" :disabled="busy || replaying" @click="emit('delete-investigation', item); closeMobile()">删除卷宗</button>
      </div>
    </div>

    <div class="sidebar-replay">
      <span class="replay-kicker">内置案例 · 离线回放</span>
      <p>东巴勒斯坦列车脱轨事故</p>
      <button :disabled="replaying || busy" @click="emit('replay')">
        {{ replaying ? '正在回放…' : '运行案例回放 →' }}
      </button>
      <small>使用归档来源与人工整理的证据关系。</small>
    </div>

    <div class="sidebar-footer">
      <button class="new-case-btn" :disabled="replaying || busy" @click="emit('new-investigation')">
        <span class="plus" aria-hidden="true">+</span>
        新对话
      </button>
      <button
        class="theme-toggle"
        type="button"
        :aria-label="theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'"
        :title="theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'"
        @click="toggleTheme"
      >
        <span class="theme-icons" aria-hidden="true">
          <svg class="theme-icon sun-icon" :class="{ active: theme === 'dark' }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="12" cy="12" r="3.5" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.65 17.65l1.42 1.42M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.65 6.35l1.42-1.42" />
          </svg>
          <svg class="theme-icon moon-icon" :class="{ active: theme === 'light' }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M20.2 15.2A8.5 8.5 0 0 1 8.8 3.8 8.5 8.5 0 1 0 20.2 15.2Z" />
          </svg>
        </span>
      </button>
    </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  flex-direction: column;
  height: 100vh;
  padding: var(--space-5) var(--space-4);
  overflow: hidden;
  background: var(--bg-surface);
  border-right: 1px solid var(--border-default);
}

.sidebar-panel {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
}

.mobile-sidebar-bar,
.mobile-drawer-close,
.sidebar-backdrop {
  display: none;
}

.sidebar-brand {
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--border-default);
}

.brand-index {
  display: block;
  margin-bottom: var(--space-2);
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: var(--font-size-overline);
  font-weight: var(--font-weight-overline);
  letter-spacing: var(--letter-spacing-overline);
  line-height: var(--line-height-overline);
}

.brand-title {
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: var(--font-size-h3);
  font-weight: var(--font-weight-h3);
  letter-spacing: var(--letter-spacing-h3);
  line-height: var(--line-height-h3);
}

.brand-subtitle,
.archive-heading,
.replay-kicker {
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: var(--font-size-overline);
  font-weight: var(--font-weight-overline);
  letter-spacing: var(--letter-spacing-overline);
  line-height: var(--line-height-overline);
}

.brand-subtitle {
  margin-top: var(--space-1);
  color: var(--text-muted);
}

.archive-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin: var(--space-5) 0 var(--space-2);
}

.refresh-archive {
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-caption);
  letter-spacing: var(--letter-spacing-caption);
  line-height: var(--line-height-caption);
  text-transform: none;
  transition: color var(--dur-sm) var(--ease-standard),
    background-color var(--dur-sm) var(--ease-standard);
}

.refresh-archive:hover:not(:disabled) {
  background: var(--bg-elevated);
  color: var(--text-primary);
}

.sidebar-note {
  margin-bottom: var(--space-3);
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.case-list {
  flex: 1;
  min-height: 0;
  margin-inline: calc(var(--space-2) * -1);
  padding-inline: var(--space-2);
  overflow-y: auto;
}

.case-card {
  position: relative;
  margin-bottom: var(--space-1);
  padding: var(--space-2) var(--space-3);
  overflow: hidden;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: color var(--dur-md) var(--ease-standard),
    background-color var(--dur-md) var(--ease-standard);
}

.case-select { display: block; width: 100%; padding: 0; text-align: left; min-height: var(--touch-target); }
.case-delete { display: block; min-height: var(--touch-target); margin-left: auto; color: var(--text-muted); font-size: var(--font-size-caption); }
.case-delete:hover:not(:disabled) { color: var(--danger); }

.case-card::before {
  position: absolute;
  top: var(--space-2);
  bottom: var(--space-2);
  left: 0;
  width: 2px;
  border-radius: var(--radius-full);
  background: var(--accent);
  content: '';
  opacity: 0;
  transform: scaleY(0.4);
  transform-origin: center;
  transition: opacity var(--dur-md) var(--ease-standard),
    transform var(--dur-md) var(--ease-standard);
}

.case-card:hover {
  background: var(--bg-elevated);
}

.case-card.active {
  background: var(--accent-subtle);
  color: var(--text-primary);
}

.case-card.active::before {
  opacity: 1;
  transform: scaleY(1);
}

.case-id {
  margin-bottom: var(--space-1);
  overflow: hidden;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-size-overline);
  letter-spacing: var(--letter-spacing-caption);
  line-height: var(--line-height-overline);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.case-name {
  display: -webkit-box;
  margin-bottom: var(--space-1);
  overflow: hidden;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: var(--font-size-small);
  font-weight: var(--font-weight-h4);
  line-height: var(--line-height-h4);
  word-break: break-word;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.case-card.active .case-name {
  color: var(--text-primary);
}

.case-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.case-status {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.status-indicator {
  width: var(--radius-sm);
  height: var(--radius-sm);
  border-radius: var(--radius-full);
}

.sidebar-replay {
  margin-top: var(--space-5);
  padding-top: var(--space-5);
  border-top: 1px solid var(--border-default);
}

.replay-kicker {
  color: var(--text-muted);
}

.sidebar-replay p {
  margin: var(--space-2) 0;
  color: var(--text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}

.sidebar-replay button {
  padding: var(--space-2) 0;
  color: var(--text-secondary);
  font-size: var(--font-size-small);
  line-height: var(--line-height-small);
  transition: color var(--dur-sm) var(--ease-standard);
}

.sidebar-replay button:hover:not(:disabled) {
  color: var(--text-primary);
}

.sidebar-replay small {
  display: block;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-small);
}

.sidebar-footer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--space-10);
  gap: var(--space-2);
  margin-top: var(--space-4);
}

.new-case-btn,
.theme-toggle {
  min-height: var(--space-10);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-secondary);
  transition: color var(--dur-sm) var(--ease-standard),
    border-color var(--dur-sm) var(--ease-standard),
    background-color var(--dur-sm) var(--ease-standard);
}

.new-case-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  font-size: var(--font-size-small);
  font-weight: var(--font-weight-caption);
  line-height: var(--line-height-small);
}

.plus {
  color: var(--text-secondary);
  font-size: var(--font-size-h4);
  line-height: var(--line-height-h4);
}

.theme-toggle {
  display: grid;
  width: var(--space-10);
  padding: 0;
  place-items: center;
}

.new-case-btn:hover:not(:disabled),
.theme-toggle:hover:not(:disabled) {
  border-color: var(--border-strong);
  background: var(--bg-elevated);
  color: var(--text-primary);
}

.theme-icons {
  position: relative;
  display: block;
  width: var(--space-5);
  height: var(--space-5);
}

.theme-icon {
  position: absolute;
  inset: 0;
  width: var(--space-5);
  height: var(--space-5);
  opacity: 0;
  transform: scale(0.72) rotate(-24deg);
  transition: opacity var(--dur-md) var(--ease-standard),
    transform var(--dur-md) var(--ease-standard);
}

.theme-icon.active {
  opacity: 1;
  transform: scale(1) rotate(0);
}

@media (width < 48rem) {
  .sidebar {
    position: sticky;
    top: 0;
    z-index: var(--z-sidebar);
    display: block;
    width: 100%;
    height: var(--touch-target);
    padding: 0;
    overflow: visible;
    border-right: 0;
    background: var(--bg-surface);
  }

  .mobile-sidebar-bar {
    display: flex;
    height: var(--touch-target);
    align-items: center;
    gap: var(--space-3);
    padding-inline: var(--space-4);
    border-bottom: 1px solid var(--border-default);
    color: var(--text-primary);
    font-size: var(--font-size-small);
    font-weight: var(--font-weight-caption);
  }

  .mobile-menu-trigger,
  .mobile-drawer-close {
    min-width: var(--touch-target);
    min-height: var(--touch-target);
  }

  .mobile-menu-trigger {
    display: grid;
    margin-left: calc(var(--space-3) * -1);
    place-items: center;
  }

  .mobile-menu-trigger svg {
    width: var(--space-5);
    height: var(--space-5);
  }

  .mobile-drawer-close {
    display: inline-flex;
    align-self: flex-end;
  }

  .sidebar-backdrop {
    position: fixed;
    z-index: var(--z-backdrop);
    display: block;
    inset: 0;
    width: 100%;
    height: 100dvh;
    background: color-mix(in srgb, var(--text-primary) 45%, transparent);
  }

  .sidebar-panel {
    position: fixed;
    z-index: var(--z-sidebar);
    top: 0;
    bottom: 0;
    left: 0;
    width: min(calc(100vw - var(--space-12)), var(--drawer-width));
    max-height: 100dvh;
    padding: var(--space-4);
    overflow-y: auto;
    border-right: 1px solid var(--border-default);
    background: var(--bg-surface);
    visibility: hidden;
    transform: translateX(-100%);
    transition: transform var(--dur-md) var(--ease-standard), visibility var(--dur-md) step-end;
  }

  .drawer-open .sidebar-panel {
    visibility: visible;
    transform: translateX(0);
    transition-timing-function: var(--ease-standard), step-start;
  }

  .case-list {
    display: block;
    max-height: none;
  }

  .case-card {
    min-height: var(--touch-target);
  }

  .sidebar-replay {
    display: none;
  }

  .new-case-btn,
  .theme-toggle {
    min-height: var(--touch-target);
  }
}

@media (max-height: 30rem) and (orientation: landscape) {
  .sidebar-panel {
    max-height: 100dvh;
  }
}

@media (width >= 48rem) and (max-height: 30rem) and (orientation: landscape) {
  .sidebar {
    height: 100dvh;
    overflow-y: auto;
  }

  .sidebar-panel {
    min-height: max-content;
    flex: none;
    overflow: visible;
  }

  .case-list {
    max-height: calc(var(--space-32) + var(--space-32));
    flex: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .sidebar-panel {
    transition: none;
  }
}
</style>
