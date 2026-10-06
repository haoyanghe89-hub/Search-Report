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
      if (url === '/runs/R1') return { run: { run_id: 'R1', mode: 'LIVE', status }, budget: {}, workers: {} }
      return []
    },
  })
  return { model, setStatus: s => { status = s }, fail: s => { fail = s }, tick: () => next?.(), dispose: () => dispose(), pending: () => Boolean(next) }
}

test('terminal poll updates both detail and run-history label', async () => {
  const h = harness()
  await h.model.load()
  assert.equal(h.model.runs.value[0].status, 'RUNNING')
  h.setStatus('BLOCKED')
  await h.tick()
  assert.equal(h.model.run.value.status, 'BLOCKED')
  assert.equal(h.model.runs.value[0].status, 'BLOCKED')
  assert.equal(h.model.running.value, false)
  assert.equal(h.pending(), false)
})

test('interrupted run observes automatic recovery without a page refresh', async () => {
  const h = harness()
  h.setStatus('INTERRUPTED')
  await h.model.load()
  assert.equal(h.pending(), true)
  const checking = h.tick()
  assert.equal(h.model.loading.value, false)
  await checking
  assert.equal(h.model.run.value.status, 'INTERRUPTED')
  h.setStatus('RUNNING')
  await h.tick()
  assert.equal(h.model.running.value, true)
  assert.equal(h.model.runs.value[0].status, 'RUNNING')
  h.setStatus('BLOCKED')
  await h.tick()
  assert.equal(h.pending(), false)
  h.dispose()
})

test('leaving an interrupted run stops recovery observation', async () => {
  const h = harness()
  h.setStatus('FAILED')
  await h.model.load()
  assert.equal(h.pending(), true)
  h.dispose()
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

test('refreshing report versions keeps results visible and never restarts the run', async () => {
  const calls = []
  let resolveReports
  const model = useInvestigation('I1', {
    mount: () => {}, unmount: () => {}, schedule: () => 1, unschedule: () => {},
    api: url => { calls.push(url); return new Promise(resolve => { resolveReports = resolve }) },
  })
  model.runId.value = 'R1'
  model.data.value.claims = [{ claim_id: 'C1' }]
  const refreshing = model.refreshReports()
  assert.equal(model.loading.value, false)
  assert.equal(model.data.value.claims.length, 1)
  resolveReports([{ report_id: 'P2' }])
  await refreshing
  assert.deepEqual(calls, ['/runs/R1/reports'])
  assert.equal(model.data.value.reports[0].report_id, 'P2')
})

test('a late report response cannot overwrite a different selected run', async () => {
  let finish
  const model = useInvestigation('I1', {
    mount: () => {}, unmount: () => {}, schedule: () => 1, unschedule: () => {},
    api: () => new Promise(resolve => { finish = resolve }),
  })
  model.runId.value = 'R1'
  const pending = model.refreshReports()
  model.runId.value = 'R2'
  finish([{ report_id: 'P1' }])
  await pending
  assert.deepEqual(model.data.value.reports, [])
})

test('quant continues polling during durable report finalization; web ready remains terminal', async () => {
  let status = 'READY_FOR_REPORT', workflow = 'quant-v1', next
  const model = useInvestigation('I1', {
    mount: () => {}, unmount: () => {},
    schedule: fn => { next = fn; return 1 }, unschedule: () => { next = null },
    api: async url => url === '/runs/R1'
      ? { run: { run_id: 'R1', status, workflow_version: workflow }, budget: {} }
      : url === '/quant/runs/R1' ? { phase: '成稿', report_id: null } : [],
  })
  await model.loadRun('R1')
  assert.equal(model.running.value, true)
  assert.equal(typeof next, 'function')
  status = 'BLOCKED'
  await next()
  assert.equal(model.running.value, true)
  status = 'COMPLETED'
  await next()
  assert.equal(model.running.value, false)
  assert.equal(next, null)
  workflow = 'web-v1'; status = 'READY_FOR_REPORT'
  await model.loadRun('R1')
  assert.equal(model.running.value, false)
  assert.equal(next, null)
})

test('quant terminal status reconciles an earlier parallel report response', async () => {
  let reads = 0
  const model = useInvestigation('I1', {
    mount: () => {}, unmount: () => {}, schedule: () => 1, unschedule: () => {},
    api: async url => {
      if (url === '/runs/R1') return { run: { run_id: 'R1', status: 'COMPLETED', workflow_version: 'quant-v1' } }
      if (url === '/quant/runs/R1') return { report_id: 'P1', phase: '成稿' }
      if (url === '/runs/R1/reports') return ++reads === 1 ? [] : [{ report_id: 'P1' }]
      return []
    },
  })
  await model.loadRun('R1')
  assert.equal(model.data.value.reports[0]?.report_id, 'P1')
  assert.equal(reads, 2)
})
