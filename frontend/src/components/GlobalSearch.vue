<script setup>
import { ref, computed, watch, onMounted } from 'vue'

const props = defineProps({
  caseData: {
    type: Object,
    default: () => ({})
  },
  investigations: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['close', 'select-case'])

const query = ref('')
const activeCategory = ref('all')
const inputRef = ref(null)

// 聚焦输入框
function focusInput() {
  setTimeout(() => {
    inputRef.value?.focus()
  }, 50)
}

// 分类
const categories = [
  { id: 'all', label: '全部' },
  { id: 'cases', label: '调查' },
  { id: 'evidence', label: '证据' },
  { id: 'sources', label: '来源' },
  { id: 'claims', label: '声明' }
]

// 高亮匹配文本
function highlight(text, q) {
  if (!q || !text) return text
  const regex = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  return text.replace(regex, '<mark class="search-highlight">$1</mark>')
}

// 搜索结果
const searchResults = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return { cases: [], evidence: [], sources: [], claims: [], total: 0 }

  const results = {
    cases: [],
    evidence: [],
    sources: [],
    claims: []
  }

  // 搜索调查
  props.investigations.forEach(c => {
    const title = c.title || ''
    const desc = c.event_description || c.description || ''
    if (title.toLowerCase().includes(q) || desc.toLowerCase().includes(q)) {
      results.cases.push({
        id: c.investigation_id || c.id,
        title,
        snippet: desc.slice(0, 80),
        status: c.status,
        type: 'case'
      })
    }
  })

  // 搜索证据
  ;(props.caseData.evidence || []).forEach(e => {
    const content = e.content || ''
    const source = e.sourceTitle || ''
    if (content.toLowerCase().includes(q) || source.toLowerCase().includes(q)) {
      results.evidence.push({
        id: e.evidence_id,
        title: e.evidence_id,
        source,
        snippet: content.slice(0, 100),
        stance: e.stance,
        type: 'evidence'
      })
    }
  })

  // 搜索来源
  ;(props.caseData.sources || []).forEach(s => {
    const title = s.title || s.titleCn || ''
    const src = s.source || ''
    if (title.toLowerCase().includes(q) || src.toLowerCase().includes(q)) {
      results.sources.push({
        id: s.id,
        title: s.titleCn || s.title,
        source: s.source,
        snippet: s.summary || s.url || '',
        type: 'source'
      })
    }
  })

  // 搜索声明
  ;(props.caseData.claims || []).forEach(cl => {
    const text = cl.text || cl.statement || ''
    if (text.toLowerCase().includes(q)) {
      results.claims.push({
        id: cl.claim_id || cl.id,
        title: `声明 ${cl.claim_id || cl.id}`,
        snippet: text.slice(0, 100),
        verification: cl.verification_status || cl.status,
        type: 'claim'
      })
    }
  })

  results.total = results.cases.length + results.evidence.length + results.sources.length + results.claims.length
  return results
})

// 过滤后的结果
const filteredResults = computed(() => {
  const cat = activeCategory.value
  const r = searchResults.value
  if (cat === 'all') {
    return [
      ...r.cases.map(i => ({ ...i, cat: 'cases' })),
      ...r.evidence.map(i => ({ ...i, cat: 'evidence' })),
      ...r.sources.map(i => ({ ...i, cat: 'sources' })),
      ...r.claims.map(i => ({ ...i, cat: 'claims' }))
    ]
  }
  return (r[cat] || []).map(i => ({ ...i, cat }))
})

// 选择结果
function selectResult(item) {
  if (item.type === 'case') {
    emit('select-case', item.id)
  }
  emit('close')
}

// 键盘导航
const selectedIndex = ref(-1)

watch(query, () => {
  selectedIndex.value = -1
})

function handleKeydown(e) {
  const items = filteredResults.value
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    selectedIndex.value = Math.min(selectedIndex.value + 1, items.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    selectedIndex.value = Math.max(selectedIndex.value - 1, -1)
  } else if (e.key === 'Enter' && selectedIndex.value >= 0) {
    e.preventDefault()
    selectResult(items[selectedIndex.value])
  } else if (e.key === 'Escape') {
    emit('close')
  }
}
onMounted(focusInput)
</script>

<template>
  <div class="search-overlay" @click.self="emit('close')">
    <div class="search-modal">
      <!-- 搜索输入 -->
      <div class="search-input-wrap">
        <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.35-4.35" />
        </svg>
        <input
          ref="inputRef"
          v-model="query"
          type="text"
          class="search-input"
          placeholder="搜索调查、证据、来源、声明..."
          @keydown="handleKeydown"
        />
        <kbd class="search-kbd">ESC</kbd>
      </div>

      <!-- 分类标签 -->
      <div v-if="query" class="search-cats">
        <button
          v-for="cat in categories"
          :key="cat.id"
          class="cat-btn"
          :class="{ active: activeCategory === cat.id }"
          @click="activeCategory = cat.id"
        >
          {{ cat.label }}
          <span class="cat-count">
            {{ cat.id === 'all' ? searchResults.total : (searchResults[cat.id]?.length || 0) }}
          </span>
        </button>
      </div>

      <!-- 搜索结果 -->
      <div class="search-results">
        <template v-if="query">
          <div v-if="filteredResults.length === 0" class="search-empty">
            <div class="empty-icon">∅</div>
            <p>未找到与「{{ query }}」相关的结果</p>
          </div>
          <div v-else class="results-list">
            <div
              v-for="(item, index) in filteredResults"
              :key="item.id + '-' + index"
              class="result-item"
              :class="{ selected: index === selectedIndex }"
              @click="selectResult(item)"
              @mouseenter="selectedIndex = index"
            >
              <div class="result-type-badge">
                <template v-if="item.cat === 'cases'">调查</template>
                <template v-else-if="item.cat === 'evidence'">证据</template>
                <template v-else-if="item.cat === 'sources'">来源</template>
                <template v-else-if="item.cat === 'claims'">声明</template>
              </div>
              <div class="result-content">
                <div class="result-title" v-html="highlight(item.title, query)"></div>
                <div v-if="item.source" class="result-source">{{ item.source }}</div>
                <div v-if="item.snippet" class="result-snippet" v-html="highlight(item.snippet, query)"></div>
              </div>
              <div class="result-meta">
                <span v-if="item.status" class="meta-tag">{{ item.status }}</span>
                <span v-if="item.stance" class="meta-tag stance">{{ item.stance }}</span>
                <span v-if="item.verification" class="meta-tag verify">{{ item.verification }}</span>
              </div>
            </div>
          </div>
        </template>

        <!-- 快捷操作（无输入时） -->
        <div v-else class="search-shortcuts">
          <h4 class="shortcuts-title">快捷操作</h4>
          <div class="shortcut-list">
            <div class="shortcut-item">
              <span class="shortcut-key">↑↓</span>
              <span class="shortcut-text">上下导航</span>
            </div>
            <div class="shortcut-item">
              <span class="shortcut-key">↵</span>
              <span class="shortcut-text">打开选中项</span>
            </div>
            <div class="shortcut-item">
              <span class="shortcut-key">ESC</span>
              <span class="shortcut-text">关闭搜索</span>
            </div>
          </div>
          <h4 class="shortcuts-title">可搜索内容</h4>
          <div class="shortcut-cats">
            <span class="sc-cat">调查案件</span>
            <span class="sc-cat">证据片段</span>
            <span class="sc-cat">信息来源</span>
            <span class="sc-cat">事实声明</span>
          </div>
        </div>
      </div>

      <!-- 底部提示 -->
      <div v-if="query && filteredResults.length > 0" class="search-footer">
        共 {{ searchResults.total }} 条结果 · 按 <kbd>↑↓</kbd> 导航，<kbd>↵</kbd> 打开
      </div>
    </div>
  </div>
</template>

<style scoped>
.search-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(35, 25, 15, 0.4);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
  animation: fadeIn 0.25s var(--ease-out);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.search-modal {
  width: 680px;
  max-width: 90vw;
  background: white;
  box-shadow:
    0 4px 12px rgba(60, 45, 20, 0.1),
    0 32px 64px rgba(60, 45, 20, 0.18);
  animation: slideDown 0.3s var(--ease-out);
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-16px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

/* 搜索输入 */
.search-input-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 24px;
  border-bottom: 1px solid var(--paper-edge);
  position: relative;
}

.search-icon {
  width: 20px;
  height: 20px;
  color: var(--ink-faint);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  border: none;
  outline: none;
  font-family: var(--font-serif);
  font-size: 18px;
  color: var(--ink-deep);
  background: transparent;
  padding: 4px 0;
}

.search-input::placeholder {
  color: var(--ink-faint);
  font-style: italic;
}

.search-kbd {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 3px 8px;
  background: var(--paper-warm);
  border: 1px solid var(--paper-edge);
  color: var(--ink-soft);
  border-radius: 3px;
}

/* 分类标签 */
.search-cats {
  display: flex;
  gap: 4px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--paper-edge);
  background: var(--paper-warm);
}

.cat-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid transparent;
  background: transparent;
  font-family: var(--font-serif);
  font-size: 13px;
  color: var(--ink-soft);
  cursor: pointer;
  transition: all 0.25s var(--ease-out);
  border-radius: 2px;
}

.cat-btn:hover {
  color: var(--accent);
  background: var(--paper-base);
}

.cat-btn.active {
  color: var(--accent);
  background: white;
  border-color: var(--accent-line);
}

.cat-count {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 1px 6px;
  background: var(--paper-warm);
  color: var(--ink-muted);
  border-radius: 2px;
}

.cat-btn.active .cat-count {
  background: var(--accent-pale);
  color: var(--accent);
}

/* 搜索结果 */
.search-results {
  max-height: 480px;
  overflow-y: auto;
}

.results-list {
  padding: 8px 0;
}

.result-item {
  display: flex;
  gap: 16px;
  padding: 14px 24px;
  cursor: pointer;
  transition: all 0.2s var(--ease-out);
  border-left: 3px solid transparent;
}

.result-item:hover,
.result-item.selected {
  background: var(--accent-pale);
  border-left-color: var(--accent);
}

.result-type-badge {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--accent);
  padding: 2px 8px;
  background: var(--paper-warm);
  border: 1px solid var(--accent-line);
  height: fit-content;
  flex-shrink: 0;
  white-space: nowrap;
}

.result-content {
  flex: 1;
  min-width: 0;
}

.result-title {
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 600;
  color: var(--ink-deep);
  margin-bottom: 4px;
  line-height: 1.4;
}

.result-source {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-muted);
  margin-bottom: 4px;
}

.result-snippet {
  font-family: var(--font-serif);
  font-size: 13px;
  color: var(--ink-soft);
  line-height: 1.6;
}

.result-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-end;
  flex-shrink: 0;
}

.meta-tag {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 2px 6px;
  background: var(--paper-warm);
  color: var(--ink-soft);
  border-radius: 2px;
}

:deep(.search-highlight) {
  background: #fef3c7;
  color: var(--ink-deep);
  padding: 0 2px;
  border-radius: 2px;
  font-weight: 600;
}

/* 空状态 */
.search-empty {
  text-align: center;
  padding: 48px 24px;
  color: var(--ink-muted);
}

.empty-icon {
  font-size: 32px;
  margin-bottom: 12px;
  opacity: 0.4;
}

.search-empty p {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 14px;
}

/* 快捷操作 */
.search-shortcuts {
  padding: 24px;
}

.shortcuts-title {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ink-faint);
  margin-bottom: 12px;
  margin-top: 20px;
}

.shortcuts-title:first-child {
  margin-top: 0;
}

.shortcut-list {
  display: flex;
  gap: 24px;
}

.shortcut-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.shortcut-key {
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 4px 8px;
  background: var(--paper-warm);
  border: 1px solid var(--paper-edge);
  color: var(--ink-deep);
  min-width: 32px;
  text-align: center;
}

.shortcut-text {
  font-family: var(--font-serif);
  font-size: 13px;
  color: var(--ink-soft);
}

.shortcut-cats {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.sc-cat {
  font-family: var(--font-serif);
  font-size: 12px;
  padding: 4px 12px;
  background: var(--paper-warm);
  color: var(--ink-muted);
  border: 1px solid var(--paper-edge);
}

/* 底部 */
.search-footer {
  padding: 12px 24px;
  border-top: 1px solid var(--paper-edge);
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-faint);
  background: var(--paper-warm);
  text-align: center;
}

.search-footer kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 1px 5px;
  background: white;
  border: 1px solid var(--paper-edge);
  color: var(--ink-soft);
  border-radius: 2px;
  margin: 0 2px;
}

@media (max-width: 768px) {
  .search-overlay {
    padding-top: 0;
    align-items: stretch;
  }

  .search-modal {
    width: 100%;
    max-width: 100%;
    box-shadow: none;
  }

  .search-results {
    max-height: calc(100vh - 200px);
  }
}
</style>
