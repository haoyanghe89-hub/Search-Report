import test from 'node:test'
import assert from 'node:assert/strict'
import { useInvestigation } from '../src/composables/useInvestigation.js'
import { runFailureLabel } from '../src/composables/presentation.js'

function harness() {
  let status = 'RUNNING'
  let fail = false
  let dispose
  let next
  const model = useInvestigation('I1', {
    mount: () => {}, unmount: fn => { dispose = fn },
    schedule: fn => { next = fn; return 1 }, unschedule: () => { next = null },
    api: async url => {
      if (fail) throw new Error('network unavailable')
      if (url === '/investigations/I1') return { title: 'test' }
      if (url === '/investigations/I1/runs') return [{ run_id: 'R1', status: 'RUNNING' }]
      if (url === '/runs/R1') return { run: { run_id: 'R1', status }, budget: {}, workers: {} }
      return []
    },
  })
  return { model, setStatus: s => { status = s }, fail: s => { fail = s }, tick: () => next?.(), dispose: () => dispose(), pending: () => Boolean(next) }
}

test('terminal poll updates both detail and run-history label', async () => {
  const h = harness()
  await h.model.load()
  assert.equal(h.model.runs.value[0].status, 'RUNNING')
  h.setStatus('FAILED')
  await h.tick()
  assert.equal(h.model.run.value.status, 'FAILED')
  assert.equal(h.model.runs.value[0].status, 'FAILED')
  assert.equal(h.model.running.value, false)
  assert.equal(h.pending(), false)
})

test('temporary network loss retries and recovers without leaving stale running state', async () => {
  const h = harness()
  await h.model.load()
  h.fail(true)
  await h.tick()
  assert.match(h.model.error.value, /network/)
  assert.equal(h.pending(), true)
  h.fail(false)
  h.setStatus('FAILED')
  await h.tick()
  assert.equal(h.model.error.value, '')
  assert.equal(h.model.runs.value[0].status, 'FAILED')
})

test('leaving the page cancels pending retry', async () => {
  const h = harness()
  await h.model.load()
  h.dispose()
  assert.equal(h.pending(), false)
})

test('model schema failures explain what failed without claiming a configuration error', () => {
  const label = runFailureLabel('InvalidProviderResponseError: inspect configuration and retry')
  assert.match(label, /模型返回/)
  assert.doesNotMatch(label, /inspect configuration/)
})
