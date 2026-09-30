import test from 'node:test'
import assert from 'node:assert/strict'
import { useOperations } from '../src/composables/useOperations.js'

test('polls persisted alerts and cancels polling when leaving', async () => {
  let callback
  let cancelled = 0
  const state = useOperations({ api: async () => ({ healthy: true, alerts: [{ message: '需要确认未知费用' }] }), schedule: fn => { callback = fn; return 42 }, unschedule: () => { cancelled++ } })
  await state.refresh()
  assert.equal(state.status.value.alerts.length, 1)
  assert.equal(typeof callback, 'function')
  state.stop()
  assert.ok(cancelled >= 2)
})

test('failed monitoring surfaces an error and keeps its retry scheduled', async () => {
  let scheduled = 0
  const state = useOperations({ api: async () => { throw new Error('离线') }, schedule: () => { scheduled++; return 1 }, unschedule: () => {} })
  await state.refresh()
  assert.match(state.error.value, /离线/)
  assert.equal(scheduled, 1)
})

test('late response after stop cannot update status or schedule another poll', async () => {
  let finish
  let scheduled = 0
  const state = useOperations({ api: () => new Promise(resolve => { finish = resolve }), schedule: () => { scheduled++; return 1 }, unschedule: () => {} })
  const pending = state.refresh()
  state.stop()
  finish({ healthy: true, alerts: [] })
  await pending
  assert.equal(state.status.value, null)
  assert.equal(scheduled, 0)
})
