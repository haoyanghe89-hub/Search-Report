import test from 'node:test'
import assert from 'node:assert/strict'
import { createTopicLauncher } from '../src/api/topicInvestigation.js'

test('a topic creates an archive and starts its live run in one action', async () => {
  const calls = []
  const start = createTopicLauncher(async (url, options) => {
    calls.push({ url, options })
    return url === '/investigations' ? { investigation_id: 'I1' } : { run_id: 'R1' }
  })
  assert.deepEqual(await start('  五四运动  '), { investigation_id: 'I1', run_id: 'R1' })
  const payload = JSON.parse(calls[0].options.body)
  assert.equal(payload.title, '五四运动')
  assert.equal(payload.event_description, '五四运动')
  assert.ok(payload.questions.length)
  assert.equal(calls[1].url, '/investigations/I1/runs')
  assert.equal(calls[1].options.method, 'POST')
})

test('empty topics do not create an investigation', async () => {
  let calls = 0
  const start = createTopicLauncher(async () => { calls++ })
  await assert.rejects(start('  '), /请输入/)
  assert.equal(calls, 0)
})

test('overlapping submissions share a single create/start request', async () => {
  let release
  let calls = 0
  const start = createTopicLauncher(async url => {
    calls++
    if (url === '/investigations') return new Promise(resolve => { release = resolve })
    return { run_id: 'R1' }
  })
  const first = start('主题')
  const second = start('主题')
  assert.equal(first, second)
  release({ investigation_id: 'I1' })
  await first
  assert.equal(calls, 2)
})

test('a failed start reuses the archive on retry', async () => {
  let created = 0
  let starts = 0
  const start = createTopicLauncher(async (url, options) => {
    if (url === '/investigations') { created++; return { investigation_id: 'I1' } }
    if (!options) return []
    if (++starts === 1) throw new Error('模型服务未配置')
    return { run_id: 'R1' }
  })
  await assert.rejects(start('主题'), /未配置/)
  assert.equal((await start('主题')).run_id, 'R1')
  assert.equal(created, 1)
  assert.equal(starts, 2)
})

test('a lost start response recovers the existing run instead of starting twice', async () => {
  let starts = 0
  const start = createTopicLauncher(async (url, options) => {
    if (url === '/investigations') return { investigation_id: 'I1' }
    if (!options) return [{ run_id: 'R1', status: 'RUNNING' }]
    starts++
    throw new Error('请求超时')
  })
  await assert.rejects(start('主题'), /超时/)
  assert.deepEqual(await start('主题'), { investigation_id: 'I1', run_id: 'R1' })
  assert.equal(starts, 1)
})
