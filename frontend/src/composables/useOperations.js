import { ref } from 'vue'
import request from '../api/request.js'

export function useOperations({ api = request, schedule = setTimeout, unschedule = clearTimeout } = {}) {
  const status = ref(null)
  const error = ref('')
  let stopped = false
  let timer
  let generation = 0
  async function refresh() {
    if (stopped) return
    unschedule(timer)
    const ticket = ++generation
    try {
      const result = await api('/ops/status')
      if (!stopped && ticket === generation) { status.value = result; error.value = '' }
    } catch (e) {
      if (!stopped && ticket === generation) error.value = '无法检查运行守护状态：' + e.message
    } finally {
      if (!stopped && ticket === generation) timer = schedule(refresh, 15000)
    }
  }
  function stop() { stopped = true; generation++; unschedule(timer) }
  return { status, error, refresh, stop }
}
