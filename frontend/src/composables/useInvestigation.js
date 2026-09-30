import { ref, computed, onMounted, onUnmounted } from 'vue'
import request from '../api/request.js'
export const runningStatuses = new Set(['CREATED', 'PENDING', 'WAITING_FOR_EXECUTION', 'RUNNING', 'VERIFYING'])
const collections = ['steps', 'sources', 'evidence', 'claims', 'conflicts', 'gaps', 'timeline', 'reports']
const emptyData = () => Object.fromEntries(collections.map(key => [key, []]))
export function useInvestigation(id, { api = request, mount = onMounted, unmount = onUnmounted, schedule = setTimeout, unschedule = clearTimeout } = {}) {
  const detail = ref(null)
  const runs = ref([])
  const runId = ref('')
  const run = ref(null)
  const budget = ref(null)
  const workers = ref({})
  const data = ref(emptyData())
  const loading = ref(false)
  const starting = ref(false)
  const error = ref('')
  const running = computed(() => runningStatuses.has(run.value?.status))
  let timer
  let generation = 0
  let disposed = false
  let pollFailures = 0
  async function checkRecovery(selectedId, ticket) {
    if (disposed || ticket !== generation) return
    try {
      const info = await api('/runs/' + selectedId)
      if (disposed || ticket !== generation) return
      error.value = ''
      if (info.run.status !== run.value?.status || info.run.state_version !== run.value?.state_version) {
        await loadRun(selectedId)
        return
      }
    } catch (e) {
      if (disposed || ticket !== generation) return
      error.value = e.message
    }
    timer = schedule(() => checkRecovery(selectedId, ticket), 15000)
  }
  async function loadRun(selectedId = runId.value) {
    unschedule(timer)
    const ticket = ++generation
    if (!selectedId) return
    const changed = runId.value !== selectedId
    runId.value = selectedId
    if (changed) { data.value = emptyData(); run.value = null; budget.value = null; workers.value = {} }
    loading.value = true
    error.value = ''
    try {
      const [info, ...results] = await Promise.all([
        api('/runs/' + selectedId), ...collections.map(key => api('/runs/' + selectedId + '/' + key)),
      ])
      if (disposed || ticket !== generation) return
      run.value = info.run
      runs.value = runs.value.map(item => item.run_id === info.run.run_id ? { ...item, ...info.run } : item)
      budget.value = info.budget
      workers.value = info.workers || {}
      data.value = Object.fromEntries(collections.map((key, index) => [key, results[index]]))
      pollFailures = 0
      if (runningStatuses.has(info.run.status)) timer = schedule(() => loadRun(selectedId), 2000)
      else if (info.run.mode === 'LIVE' && ['FAILED', 'INTERRUPTED'].includes(info.run.status)) {
        // Observe server-side recovery without flashing old reports or clearing consent inputs.
        timer = schedule(() => checkRecovery(selectedId, ticket), 15000)
      }
    } catch (e) {
      if (!disposed && ticket === generation) {
        error.value = e.message
        timer = schedule(() => loadRun(selectedId), Math.min(15000, 2000 * 2 ** Math.min(pollFailures++, 3)))
      }
    } finally {
      if (!disposed && ticket === generation) loading.value = false
    }
  }
  async function load() {
    loading.value = true
    error.value = ''
    try {
      const [investigation, history] = await Promise.all([api('/investigations/' + id), api('/investigations/' + id + '/runs')])
      if (disposed) return
      detail.value = investigation
      runs.value = history
      const selected = history.find(r => r.run_id === runId.value) || history[0]
      if (selected) await loadRun(selected.run_id)
    } catch (e) { if (!disposed) error.value = e.message }
    finally { if (!disposed) loading.value = false }
  }
  async function refreshReports() {
    const ticket = generation
    const selectedId = runId.value
    if (!selectedId) return
    try {
      const reports = await api('/runs/' + selectedId + '/reports')
      if (!disposed && ticket === generation && selectedId === runId.value) {
        data.value = { ...data.value, reports }
      }
    } catch (e) { if (!disposed && ticket === generation) error.value = e.message }
  }
  async function start() {
    if (starting.value || running.value) return
    starting.value = true
    error.value = ''
    try {
      const result = await api('/investigations/' + id + '/runs', { method: 'POST' })
      if (disposed) return
      runId.value = result.run_id
      data.value = emptyData()
      run.value = null
      await load()
    } catch (e) { if (!disposed) error.value = e.message }
    finally { if (!disposed) starting.value = false }
  }
  async function cancel() {
    try {
      await api('/runs/' + runId.value + '/cancel', { method: 'POST' })
      await loadRun()
    } catch (e) { error.value = e.message }
  }
  mount(load)
  unmount(() => { disposed = true; generation++; unschedule(timer) })
  return { detail, runs, runId, run, budget, workers, data, loading, starting, error, running, load, loadRun, refreshReports, start, cancel }
}
