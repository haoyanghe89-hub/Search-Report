/**
 * 运行相关 API
 */
import request from './request.js'

/**
 * 获取运行详情
 */
export function fetchRunDetail(runId) {
  return request(`/runs/${runId}`)
}

/**
 * 获取运行步骤
 */
export function fetchRunSteps(runId) {
  return request(`/runs/${runId}/steps`)
}

/**
 * 获取运行来源
 */
export function fetchRunSources(runId) {
  return request(`/runs/${runId}/sources`)
}

/**
 * 获取运行证据
 */
export function fetchRunEvidence(runId) {
  return request(`/runs/${runId}/evidence`)
}

/**
 * 获取运行声明
 */
export function fetchRunClaims(runId) {
  return request(`/runs/${runId}/claims`)
}

/**
 * 获取运行冲突
 */
export function fetchRunConflicts(runId) {
  return request(`/runs/${runId}/conflicts`)
}

/**
 * 获取运行缺口
 */
export function fetchRunGaps(runId) {
  return request(`/runs/${runId}/gaps`)
}

/**
 * 获取运行时间线
 */
export function fetchRunTimeline(runId) {
  return request(`/runs/${runId}/timeline`)
}

/**
 * 获取运行报告列表
 */
export function fetchRunReports(runId) {
  return request(`/runs/${runId}/reports`)
}

/**
 * 生成报告
 */
export function generateReport(runId, reportType = 'FULL_INVESTIGATION') {
  return request(`/runs/${runId}/reports`, {
    method: 'POST',
    body: JSON.stringify({ report_type: reportType })
  })
}
