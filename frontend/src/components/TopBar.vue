<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useTheme } from '../composables/useTheme.js'

defineProps({
  exportUrl: String,
  searchDisabled: Boolean,
  category: {
    type: String,
    default: '公共安全'
  },
  caseName: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['open-search'])
const { theme, toggleTheme } = useTheme()
const isScrolled = ref(false)
let scrollFrame = null

function updateScrollState() {
  scrollFrame = null
  isScrolled.value = window.scrollY > 8
}

function handleScroll() {
  if (scrollFrame !== null) return
  scrollFrame = window.requestAnimationFrame(updateScrollState)
}

onMounted(() => {
  updateScrollState()
  window.addEventListener('scroll', handleScroll, { passive: true })
})

onUnmounted(() => {
  window.removeEventListener('scroll', handleScroll)
  if (scrollFrame !== null) window.cancelAnimationFrame(scrollFrame)
})
</script>

<template>
  <header class="topbar" :class="{ scrolled: isScrolled }">
    <div class="case-heading">
      <h4>{{ caseName }}</h4>
      <span class="category-badge">{{ category }}</span>
    </div>

    <div class="topbar-actions">
      <button class="search-btn" :disabled="searchDisabled" @click="emit('open-search')">
        <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.35-4.35" />
        </svg>
        <span class="search-text">搜索</span>
        <kbd class="search-kbd">⌘ K</kbd>
      </button>

      <a v-if="exportUrl" class="export-btn" :href="exportUrl" download>
        导出报告
        <span class="export-arrow" aria-hidden="true">↗</span>
      </a>
      <span v-else class="report-status">尚无报告</span>

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
  </header>
</template>

<style scoped>
.topbar {
  position: sticky;
  top: 0;
  z-index: 15;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--topbar-height);
  padding: 0 var(--space-12);
  border-bottom: 1px solid transparent;
  background: transparent;
  transition: background-color var(--dur-md) var(--ease-standard),
    border-color var(--dur-md) var(--ease-standard);
}

.topbar.scrolled {
  border-bottom-color: var(--border-default);
  background: color-mix(in srgb, var(--bg-base) 80%, transparent);
  backdrop-filter: blur(var(--blur-md));
  -webkit-backdrop-filter: blur(var(--blur-md));
}

.case-heading {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-3);
}

.case-heading h4 {
  max-width: min(42vw, 36rem);
  overflow: hidden;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: var(--font-size-h4);
  font-weight: var(--font-weight-h4);
  letter-spacing: var(--letter-spacing-h4);
  line-height: var(--line-height-h4);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.category-badge {
  flex-shrink: 0;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  border: 1px solid var(--border-default);
  background: var(--bg-elevated);
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-caption);
  letter-spacing: var(--letter-spacing-caption);
  line-height: var(--line-height-caption);
}

.topbar-actions {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: nowrap;
}

.search-btn,
.export-btn,
.theme-toggle {
  min-height: var(--space-10);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  color: var(--text-secondary);
  transition: color var(--dur-sm) var(--ease-standard),
    border-color var(--dur-sm) var(--ease-standard),
    background-color var(--dur-sm) var(--ease-standard);
}

.search-btn,
.export-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  font-size: var(--font-size-small);
  font-weight: var(--font-weight-caption);
  line-height: var(--line-height-small);
  text-decoration: none;
  white-space: nowrap;
}

.search-btn:hover:not(:disabled),
.export-btn:hover,
.theme-toggle:hover {
  border-color: var(--border-strong);
  background: var(--bg-elevated);
  color: var(--text-primary);
}

.search-icon {
  width: var(--space-4);
  height: var(--space-4);
  flex-shrink: 0;
}

.search-kbd {
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--bg-elevated);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-size-overline);
  line-height: var(--line-height-overline);
}

.report-status {
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  white-space: nowrap;
}

.export-arrow {
  transition: transform var(--dur-sm) var(--ease-standard);
}

.export-btn:hover .export-arrow {
  transform: translate(var(--space-1), calc(var(--space-1) * -1));
}

.theme-toggle {
  display: grid;
  width: var(--space-10);
  padding: 0;
  place-items: center;
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
  .topbar {
    position: sticky !important;
    top: var(--touch-target) !important;
    height: var(--topbar-height) !important;
    padding: 0 var(--space-5) !important;
    flex-wrap: nowrap !important;
    gap: var(--space-3);
  }

  .case-heading h4 {
    max-width: 32vw;
  }

  .category-badge,
  .search-text,
  .search-kbd,
  .report-status {
    display: none;
  }

  .search-btn {
    width: var(--touch-target);
    padding: 0;
    justify-content: center;
  }

  .search-btn,
  .export-btn,
  .theme-toggle {
    min-height: var(--touch-target);
  }

  .export-btn {
    padding-inline: var(--space-2);
  }
}
</style>
