<script setup>


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


</script>

<template>
  <header class="topbar">
    <div class="breadcrumb">
      <span class="breadcrumb-item">调查档案</span>
      <span class="breadcrumb-sep">/</span>
      <span class="breadcrumb-item">{{ category }}</span>
      <span class="breadcrumb-sep">/</span>
      <span class="breadcrumb-item current">{{ caseName }}</span>
    </div>
    <div class="topbar-actions">
      <button class="search-btn" :disabled="searchDisabled" @click="emit('open-search')">
        <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.35-4.35" />
        </svg>
        <span class="search-text">搜索</span>
        <kbd class="search-kbd">Ctrl K</kbd>
      </button>
      <div class="topbar-divider"></div>
      <span class="reading-label">阅读</span>
      <a v-if="exportUrl" class="export-btn" :href="exportUrl" download>导出报告 <span class="export-arrow">↗</span></a>
      <span v-else class="reading-label">尚无报告</span>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  height: var(--topbar-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 48px;
  position: sticky;
  top: 0;
  z-index: 15;
  background: rgba(247, 243, 236, 0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--paper-edge);
}

.breadcrumb {
  display: flex;
  align-items: baseline;
  gap: 14px;
  font-family: var(--font-serif);
}

.breadcrumb-item {
  font-size: 13px;
  color: var(--ink-faint);
  font-style: italic;
}

.breadcrumb-item.current {
  font-size: 16px;
  font-weight: 600;
  color: var(--ink-deep);
  font-style: normal;
}

.breadcrumb-sep {
  color: var(--paper-edge);
  font-size: 14px;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 20px;
}

.search-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 14px;
  background: var(--paper-warm);
  border: 1px solid var(--paper-edge);
  cursor: pointer;
  transition: all 0.3s var(--ease-out);
  font-family: var(--font-serif);
  font-size: 13px;
  color: var(--ink-soft);
}

.search-btn:hover {
  background: var(--accent-pale);
  border-color: var(--accent-line);
  color: var(--accent);
}

.search-btn .search-icon {
  width: 15px;
  height: 15px;
  color: var(--ink-faint);
  transition: color 0.3s var(--ease-out);
}

.search-btn:hover .search-icon {
  color: var(--accent);
}

.search-btn .search-kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 2px 6px;
  background: white;
  border: 1px solid var(--paper-edge);
  color: var(--ink-muted);
  margin-left: 4px;
}

.topbar-divider {
  width: 1px;
  height: 24px;
  background: var(--paper-edge);
}

.mode-toggle {
  display: flex;
  gap: 2px;
  padding: 3px;
  background: var(--paper-warm);
  border-radius: 4px;
  border: 1px solid var(--paper-edge);
}

.mode-btn {
  padding: 4px 10px;
  border: none;
  background: transparent;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-muted);
  cursor: pointer;
  border-radius: 2px;
  transition: all 0.3s var(--ease-out);
  letter-spacing: 0.05em;
}

.mode-btn.active {
  background: var(--paper-base);
  color: var(--ink-deep);
  box-shadow: 0 1px 3px var(--paper-shadow);
}

.export-btn {
  padding: 8px 16px;
  border: 1px solid var(--paper-edge);
  background: transparent;
  font-family: var(--font-serif);
  font-size: 13px;
  color: var(--ink-soft);
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.35s var(--ease-out);
  display: flex;
  align-items: center;
  gap: 8px;
}

.export-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-pale);
}

.export-arrow {
  font-style: normal;
}
</style>
