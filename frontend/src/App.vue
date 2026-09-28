<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import Sidebar from './components/Sidebar.vue'
import InvestigationView from './views/InvestigationView.vue'
import NewInvestigationModal from './components/NewInvestigationModal.vue'
import GlobalSearch from './components/GlobalSearch.vue'

import { caseList, eastPalestineCase } from './data/cases.js'
import { fetchInvestigations } from './api/index.js'

// 调查列表 - 优先从 API 加载，失败则用 mock
const investigations = ref([])
const loading = ref(false)
const apiError = ref(null)

// 当前选中的调查
const activeCaseId = ref('EP-2023-001')

// 新建调查弹窗
const showNewModal = ref(false)

// 打开新建调查
function openNewInvestigation() {
  showNewModal.value = true
}

// 关闭新建调查
function closeNewInvestigation() {
  showNewModal.value = false
}

// 调查创建成功
async function onInvestigationCreated(result) {
  console.log('调查创建成功:', result)
  const newId = result.investigation_id
  // 先切换到新调查
  if (newId) {
    activeCaseId.value = newId
  }
  // 重新加载列表（不重置 activeCaseId）
  await loadInvestigations(false)
  // 再次确保选中新调查
  if (newId) {
    activeCaseId.value = newId
  }
}

// 全局搜索
const showSearch = ref(false)

function openSearch() {
  showSearch.value = true
}

function closeSearch() {
  showSearch.value = false
}

function onSearchSelectCase(id) {
  activeCaseId.value = id
}

// 键盘快捷键
function handleKeydown(e) {
  // Ctrl/Cmd + K 打开搜索
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault()
    openSearch()
  }
  // ESC 关闭
  if (e.key === 'Escape') {
    closeSearch()
  }
}

onMounted(() => {
  loadInvestigations()
  window.addEventListener('keydown', handleKeydown)
})

// 加载调查列表
async function loadInvestigations(setDefault = true) {
  loading.value = true
  apiError.value = null
  try {
    const data = await fetchInvestigations()
    if (data && data.length > 0) {
      investigations.value = data.map(item => ({
        id: item.investigation_id,
        name: item.title,
        category: '调查',
        status: item.run_count > 0 ? 'verified' : 'draft',
        statusText: item.run_count > 0 ? '有运行记录' : '新建',
        claimsCount: 0,
        tag: item.run_count > 0 ? `${item.run_count}次运行` : '',
        isBuiltin: false,
        run_count: item.run_count
      }))
      // 只有 setDefault 为 true 且当前没有选中项时才默认选中第一个
      if (setDefault && (!activeCaseId.value || !data.find(d => d.investigation_id === activeCaseId.value))) {
        activeCaseId.value = data[0].investigation_id
      }
    } else {
      // API 返回空，用 mock 数据
      investigations.value = caseList
      apiError.value = 'NO_DATA'
      if (setDefault) {
        activeCaseId.value = 'EP-2023-001'
      }
    }
  } catch (e) {
    console.warn('API 不可用，使用本地 mock 数据:', e.message)
    investigations.value = caseList
    apiError.value = e
    if (setDefault) {
      activeCaseId.value = 'EP-2023-001'
    }
  } finally {
    loading.value = false
  }
}

// 选择调查
function selectCase(id) {
  activeCaseId.value = id
}

// 当前调查详情
const activeCase = computed(() => {
  // 东巴勒斯坦内置案例用详细 mock 数据
  if (activeCaseId.value === 'EP-2023-001') {
    return eastPalestineCase
  }
  // 其他案例：返回基础信息，不填充 mock 数据
  const item = investigations.value.find(i => i.id === activeCaseId.value)
  if (item) {
    return {
      id: item.id,
      investigation_id: item.id,
      title: item.name,
      name: item.name,
      category: item.category || '调查',
      status: item.status,
      statusText: item.statusText,
      run_count: item.run_count || 0,
      isBuiltin: item.isBuiltin,
      // 空数据结构
      description: '',
      event_date: null,
      location: '',
      sources: [],
      evidence: [],
      claims: [],
      conflicts: [],
      gaps: [],
      timeline: [],
      report: null,
      review: null
    }
  }
  return eastPalestineCase
})
</script>

<template>
  <div class="app-wrapper">
    <Sidebar
      :cases="investigations"
      :active-case-id="activeCaseId"
      :loading="loading"
      @select="selectCase"
      @new-investigation="openNewInvestigation"
    />
    <main class="main-content">
      <InvestigationView
        v-if="activeCase"
        :case-data="activeCase"
        :api-error="apiError"
        @open-search="openSearch"
      />
    </main>

    <!-- 新建调查弹窗 -->
    <NewInvestigationModal
      v-if="showNewModal"
      @close="closeNewInvestigation"
      @created="onInvestigationCreated"
    />

    <!-- 全局搜索弹窗 -->
    <GlobalSearch
      v-if="showSearch"
      :case-data="activeCase || {}"
      :investigations="investigations"
      @close="closeSearch"
      @select-case="onSearchSelectCase"
    />
  </div>
</template>

<style scoped>
.app-wrapper {
  display: grid;
  grid-template-columns: var(--sidebar-width) 1fr;
  min-height: 100vh;
}

.main-content {
  min-width: 0;
  display: flex;
  flex-direction: column;
}
</style>
