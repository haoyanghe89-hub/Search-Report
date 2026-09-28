/**
 * 调查数据组合式函数
 */
import { ref, onMounted } from 'vue'
import {
  fetchInvestigations,
  fetchInvestigationDetail,
  fetchInvestigationRuns,
  fetchRunDetail,
  fetchRunSources,
  fetchRunEvidence,
  fetchRunClaims,
  fetchRunConflicts,
  fetchRunTimeline,
  fetchRunReports
} from '@/api/index.js'

/**
 * 使用调查列表
 */
export function useInvestigations() {
  const investigations = ref([])
  const loading = ref(false)
  const error = ref(null)

  async function load() {
    loading.value = true
    error.value = null
    try {
      const data = await fetchInvestigations()
      investigations.value = data
    } catch (e) {
      error.value = e
      console.error('加载调查列表失败:', e)
    } finally {
      loading.value = false
    }
  }

  onMounted(load)

  return { investigations, loading, error, reload: load }
}

/**
 * 使用调查详情
 */
export function useInvestigationDetail(investigationId) {
  const detail = ref(null)
  const loading = ref(false)
  const error = ref(null)

  async function load(id = investigationId.value) {
    if (!id) return
    loading.value = true
    error.value = null
    try {
      const data = await fetchInvestigationDetail(id)
      detail.value = data
    } catch (e) {
      error.value = e
      console.error('加载调查详情失败:', e)
    } finally {
      loading.value = false
    }
  }

  return { detail, loading, error, reload: load }
}

/**
 * 使用运行数据
 */
export function useRunData(runId) {
  const run = ref(null)
  const sources = ref([])
  const evidence = ref([])
  const claims = ref([])
  const conflicts = ref([])
  const timeline = ref([])
  const reports = ref([])
  const loading = ref(false)
  const error = ref(null)

  async function loadAll(id = runId.value) {
    if (!id) return
    loading.value = true
    error.value = null
    try {
      const [
        runData,
        sourcesData,
        evidenceData,
        claimsData,
        conflictsData,
        timelineData,
        reportsData
      ] = await Promise.all([
        fetchRunDetail(id),
        fetchRunSources(id),
        fetchRunEvidence(id),
        fetchRunClaims(id),
        fetchRunConflicts(id),
        fetchRunTimeline(id),
        fetchRunReports(id)
      ])
      run.value = runData
      sources.value = sourcesData
      evidence.value = evidenceData
      claims.value = claimsData
      conflicts.value = conflictsData
      timeline.value = timelineData
      reports.value = reportsData
    } catch (e) {
      error.value = e
      console.error('加载运行数据失败:', e)
    } finally {
      loading.value = false
    }
  }

  return {
    run,
    sources,
    evidence,
    claims,
    conflicts,
    timeline,
    reports,
    loading,
    error,
    reload: loadAll
  }
}
