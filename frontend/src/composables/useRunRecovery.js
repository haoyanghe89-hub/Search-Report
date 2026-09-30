import { ref, computed } from 'vue'
import request from '../api/request.js'

export const recoveryBudgetFields = [
  { key: 'search_calls', label: '搜索次数', used: 'search_calls_used' },
  { key: 'fetch_calls', label: '抓取次数', used: 'fetch_calls_used' },
  { key: 'model_calls', label: '模型调用次数', used: 'model_calls_used' },
  { key: 'tokens', label: 'Token', used: 'tokens_used' },
  { key: 'wall_time_ms', label: '执行时间（分钟）', used: 'consumed_wall_time_ms', scale: 60000 },
  { key: 'sources', label: '来源数量', used: 'sources_used' },
  { key: 'research_rounds', label: '研究轮次', used: 'research_rounds_used' },
]
const emptyIncrease = () => Object.fromEntries(recoveryBudgetFields.map(({ key }) => [key, 0]))

export function useRunRecovery({ api = request, onResumed = () => {} } = {}) {
  const runId = ref('')
  const recovery = ref(null)
  const loading = ref(false)
  const submitting = ref(false)
  const accepted = ref(false)
  const error = ref('')
  const consent = ref([])
  const increase = ref(emptyIncrease())
  let generation = 0
  let disposed = false
  const validIncrease = computed(() => recoveryBudgetFields.every(({ key, scale = 1 }) => {
    const value = Number(increase.value[key])
    return increase.value[key] !== '' && Number.isSafeInteger(value) && value >= 0 && Number.isSafeInteger(value * scale)
  }))
  const allAcknowledged = computed(() => (recovery.value?.unknown_calls || []).every(call => consent.value.includes(call.intent_id)))
  const canSubmit = computed(() => Boolean(recovery.value?.can_resume && !loading.value && !submitting.value && !accepted.value && validIncrease.value && allAcknowledged.value))
  const current = ticket => !disposed && ticket === generation

  async function load(id = runId.value) {
    if (disposed || submitting.value) return
    const ticket = ++generation
    runId.value = id
    recovery.value = null
    consent.value = []
    increase.value = emptyIncrease()
    accepted.value = false
    error.value = ''
    loading.value = Boolean(id)
    if (!id) return
    try {
      const result = await api(`/runs/${encodeURIComponent(id)}/recovery`)
      if (current(ticket)) recovery.value = result
    } catch (e) {
      if (current(ticket)) error.value = e.message
    } finally {
      if (current(ticket)) loading.value = false
    }
  }

  // Invalidate in-flight responses and consent when switching runs or leaving the page.
  function clear() {
    generation++
    runId.value = ''
    recovery.value = null
    consent.value = []
    increase.value = emptyIncrease()
    loading.value = false
    submitting.value = false
    accepted.value = false
    error.value = ''
  }
  function dispose() { clear(); disposed = true }

  async function resume() {
    if (!canSubmit.value) return
    const ticket = generation
    const id = runId.value
    const body = {
      expected_state_version: recovery.value.state_version,
      retry_unknown_intent_ids: (recovery.value.unknown_calls || []).map(call => call.intent_id),
      budget_increase: Object.fromEntries(recoveryBudgetFields.map(({ key, scale = 1 }) => [key, Number(increase.value[key]) * scale])),
    }
    submitting.value = true
    error.value = ''
    try {
      const result = await api(`/runs/${encodeURIComponent(id)}/resume`, { method: 'POST', body: JSON.stringify(body) })
      if (!current(ticket)) return
      accepted.value = true
      consent.value = []
      onResumed(result)
    } catch (e) {
      if (!current(ticket)) return
      submitting.value = false
      // Never silently retry a stale or indeterminate resume request, including its top-up.
      await load(id)
      if (!disposed && id === runId.value) {
        error.value = e.status === 409 && (!e.code || ['STALE_RUN_STATE', 'RUN_STILL_ACTIVE'].includes(e.code))
          ? '运行状态已变化，已重新检查恢复条件。请重新确认追加额度和未知调用，再继续。'
          : `${e.message}；请根据最新恢复状态确认后再操作。`
      }
    } finally {
      if (current(ticket)) submitting.value = false
    }
  }
  return { recovery, loading, submitting, accepted, error, consent, increase, validIncrease, allAcknowledged, canSubmit, load, clear, dispose, resume }
}
