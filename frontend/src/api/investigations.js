/**
 * 调查相关 API
 */
import request from './request.js'

/**
 * 获取调查列表
 */
export function fetchInvestigations() {
  return request('/investigations')
}

/**
 * 获取调查详情
 */
export function fetchInvestigationDetail(investigationId) {
  return request(`/investigations/${investigationId}`)
}

/**
 * 创建调查
 */
export function createInvestigation(payload) {
  return request('/investigations', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

/**
 * 更新调查
 */
export function updateInvestigation(investigationId, payload) {
  return request(`/investigations/${investigationId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  })
}

/**
 * 获取调查的运行列表
 */
export function fetchInvestigationRuns(investigationId) {
  return request(`/investigations/${investigationId}/runs`)
}

/**
 * 启动调查运行
 */
export function startInvestigationRun(investigationId) {
  return request(`/investigations/${investigationId}/runs`, {
    method: 'POST'
  })
}
