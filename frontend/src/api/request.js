export class ApiError extends Error {
  constructor(status, code, message) {
    super(message)
    this.status = status
    this.code = code
  }
}
export async function request(path, options = {}) {
  const { timeoutMs = 30000, ...init } = options
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch('/api' + path, {
      ...init,
      credentials: 'same-origin',
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...init.headers },
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      const detail = data.detail
      const message = typeof detail === 'string' ? detail : detail?.message || (Array.isArray(detail) ? detail.map(x => x.msg).join('；') : response.statusText)
      throw new ApiError(response.status, detail?.code || 'HTTP_' + response.status, message || '请求失败')
    }
    if (response.status === 204) return null
    return await response.json()
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError(0, 'NETWORK_ERROR', error.name === 'AbortError' ? '请求超时。可刷新调查列表检查后端运行状态。' : '无法连接服务：' + error.message)
  } finally { clearTimeout(timer) }
}
export default request
