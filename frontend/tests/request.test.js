import test, { afterEach } from 'node:test'
import assert from 'node:assert/strict'
import { request, ApiError } from '../src/api/request.js'
const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })
test('preserves review CSRF headers, JSON content type and same-origin credentials', async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/review/decisions')
    assert.equal(options.credentials, 'same-origin')
    assert.equal(options.headers['Content-Type'], 'application/json')
    assert.equal(options.headers['X-Requested-With'], 'XMLHttpRequest')
    assert.equal(options.headers['Idempotency-Key'], 'test-key')
    return new Response(JSON.stringify({ ok: true }), { status: 200 })
  }
  assert.deepEqual(await request('/review/decisions', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest', 'Idempotency-Key': 'test-key' }, body: '{}' }), { ok: true })
})
test('successful 204 logout is accepted without JSON parsing', async () => {
  globalThis.fetch = async () => new Response(null, { status: 204 })
  assert.equal(await request('/review/logout', { method: 'POST' }), null)
})
test('missing live configuration surfaces server error without a fallback result', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: { code: 'LIVE_NOT_CONFIGURED', message: '请配置 DEEPSEEK_API_KEY' } }), { status: 503 })
  await assert.rejects(request('/investigations/I/runs', { method: 'POST' }), error => error instanceof ApiError && error.status === 503 && error.code === 'LIVE_NOT_CONFIGURED' && error.message === '请配置 DEEPSEEK_API_KEY')
})
test('FastAPI field validation errors remain readable', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: [{ msg: 'Title is required' }] }), { status: 422 })
  await assert.rejects(request('/investigations'), { message: 'Title is required' })
})
test('timed out requests abort rather than returning invented data', async () => {
  globalThis.fetch = async (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  })
  await assert.rejects(request('/investigations', { timeoutMs: 5 }), error => error.code === 'NETWORK_ERROR' && error.message.includes('请求超时'))
})
