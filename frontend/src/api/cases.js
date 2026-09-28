/**
 * 内置案例相关 API
 */
import request from './request.js'

/**
 * 获取内置案例列表
 */
export function fetchBuiltInCases() {
  return request('/cases')
}

/**
 * 运行东巴勒斯坦案例回放
 */
export function runEastPalestineReplay() {
  return request('/cases/east-palestine-2023/replay', {
    method: 'POST'
  })
}
