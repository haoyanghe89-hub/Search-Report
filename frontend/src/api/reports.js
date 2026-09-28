/**
 * 报告相关 API
 */
import request from './request.js'

/**
 * 获取报告详情（含所有章节）
 */
export function fetchReportDetail(reportId) {
  return request(`/reports/${reportId}`)
}

/**
 * 获取报告引用列表
 */
export function fetchReportCitations(reportId) {
  return request(`/reports/${reportId}/citations`)
}

/**
 * 获取报告审核信息
 */
export function fetchReportReview(reportId) {
  return request(`/reports/${reportId}/review`)
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
