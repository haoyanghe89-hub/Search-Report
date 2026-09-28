/**
 * API 请求封装
 * 统一处理请求、错误、超时
 */

const BASE_URL = '/api'

/**
 * 通用请求方法
 */
async function request(url, options = {}) {
  const fullUrl = url.startsWith('http') ? url : `${BASE_URL}${url}`
  
  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    },
    ...options
  }

  try {
    const response = await fetch(fullUrl, config)
    
    if (!response.ok) {
      let errorData = null
      try {
        errorData = await response.json()
      } catch {
        // 忽略 JSON 解析错误
      }
      
      const message = errorData?.detail?.message || errorData?.detail || response.statusText
      const code = errorData?.detail?.code || errorData?.code || `HTTP_${response.status}`
      
      throw new ApiError(response.status, code, message, errorData)
    }
    
    return await response.json()
  } catch (error) {
    if (error instanceof ApiError) {
      throw error
    }
    // 网络错误
    throw new ApiError(0, 'NETWORK_ERROR', error.message || '网络连接失败')
  }
}

/**
 * API 错误类
 */
class ApiError extends Error {
  constructor(status, code, message, data = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.data = data
  }
}

export { request, ApiError }
export default request
