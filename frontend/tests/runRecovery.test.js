import test from 'node:test'
import assert from 'node:assert/strict'
import { useRunRecovery } from '../src/composables/useRunRecovery.js'

const info = (unknown = []) => ({ can_resume: true, state_version: 7, unknown_calls: unknown })

test('unknown consent starts empty; sends exact IDs, unchanged state and additive budget', async () => {
  const requests = []
  let resumed
  const state = useRunRecovery({ api: async (url, options) => {
    requests.push([url, options])
    return options ? { run_id: 'same' } : info([{ intent_id: 'intent-1' }])
  }, onResumed: value => { resumed = value } })
  await state.load('same')
  assert.equal(state.canSubmit.value, false)
  await state.resume()
  assert.equal(requests.length, 1)
  state.consent.value = ['intent-1']
  state.increase.value.wall_time_ms = 2
  state.increase.value.model_calls = 5
  await state.resume()
  const sent = JSON.parse(requests[1][1].body)
  assert.equal(sent.expected_state_version, 7)
  assert.deepEqual(sent.retry_unknown_intent_ids, ['intent-1'])
  assert.equal(sent.budget_increase.wall_time_ms, 120000)
  assert.equal(sent.budget_increase.model_calls, 5)
  assert.deepEqual(resumed, { run_id: 'same' })
  await state.resume()
  assert.equal(requests.length, 2)
})

test('double click cannot duplicate resume or budget topup', async () => {
  let finish
  let posts = 0
  const state = useRunRecovery({ api: async (url, options) => {
    if (!options) return info()
    posts++
    return new Promise(resolve => { finish = resolve })
  } })
  await state.load('same')
  const pending = state.resume()
  await state.resume()
  assert.equal(posts, 1)
  finish({ run_id: 'same' })
  await pending
})

test('conflict refreshes state and clears topup and consent without automatic retry', async () => {
  let gets = 0
  let posts = 0
  const state = useRunRecovery({ api: async (url, options) => {
    if (!options) { gets++; return info([{ intent_id: gets === 1 ? 'old' : 'new' }]) }
    posts++
    throw Object.assign(new Error('conflict'), { status: 409 })
  } })
  await state.load('same')
  state.consent.value = ['old']
  state.increase.value.tokens = 100
  await state.resume()
  assert.equal(gets, 2)
  assert.equal(posts, 1)
  assert.deepEqual(state.consent.value, [])
  assert.equal(state.increase.value.tokens, 0)
  assert.equal(state.canSubmit.value, false)
  assert.match(state.error.value, /重新确认/)
})

test('stale GET responses cannot transfer consent or status to a different run', async () => {
  let finish
  const state = useRunRecovery({ api: url => url.includes('old')
    ? new Promise(resolve => { finish = resolve }) : Promise.resolve(info()) })
  const pending = state.load('old')
  await state.load('new')
  finish(info([{ intent_id: 'old-call' }]))
  await pending
  assert.deepEqual(state.recovery.value.unknown_calls, [])
  state.dispose()
  assert.equal(state.canSubmit.value, false)
})

test('negative or fractional increments cannot be submitted', async () => {
  const state = useRunRecovery({ api: async () => info() })
  await state.load('same')
  for (const value of [-1, 1.2, '', Infinity]) {
    state.increase.value.model_calls = value
    assert.equal(state.canSubmit.value, false)
  }
})

test('budget rejection preserves the specific reason after refresh', async () => {
  const state = useRunRecovery({ api: async (url, options) => {
    if (!options) return info()
    throw Object.assign(new Error('研究轮次已耗尽，请追加额度。'), { status: 409, code: 'BUDGET_INCREASE_REQUIRED' })
  } })
  await state.load('same')
  await state.resume()
  assert.match(state.error.value, /研究轮次已耗尽/)
  assert.equal(state.increase.value.research_rounds, 0)
})
