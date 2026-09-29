// Display summaries never infer verification from the presence of a run or report.
export const runModeLabel = run => run.execution_provenance === 'CURATED_OFFLINE' ? (run.mode === 'REPLAY' ? '离线案例回放' : '离线案例录制') : run.mode === 'REPLAY' ? '历史回放' : '联网研究'
export const runStatusLabel = status => ({ CREATED: '已创建', PENDING: '等待执行', WAITING_FOR_EXECUTION: '等待执行', RUNNING: '调查中', VERIFYING: '验证中', READY_FOR_REPORT: '调查完成', COMPLETED: '已完成', FAILED: '运行失败', CANCELLED: '已取消', TIMED_OUT: '已超时' })[status] || status
export function resultsPending({ replaying, starting, running, loading }) { return Boolean(replaying || starting || running || loading) }

export function runFailureLabel(reason) {
  if (/^(InvalidProviderResponseError|MODEL_RESPONSE_INVALID|INVALID_RESPONSE)/.test(reason || '')) return '模型返回的数据格式或引用编号未通过校验，自动修复后仍不合格。已有资料已保留，可重新发起调查。'
  if (/^ModelOutputTruncatedError/.test(reason || '')) return '模型输出超过长度限制，重试后仍未返回完整结果。已有资料已保留。'
  if (/^RUN_TIMEOUT/.test(reason || '')) return '调查达到时间上限，已有资料已保留。'
  return reason
}

export function verificationSummary(claims) {
  const verified = claims.filter(c => c.validation_status === 'VERIFIED').length
  return { verified, label: claims.length ? `${verified} / ${claims.length} 条已验证` : '尚无验证结果' }
}

export function projectAgents(steps) {
  const groups = new Map()
  for (const step of steps) {
    const role = step.agent_role || 'UNKNOWN'
    if (!groups.has(role)) groups.set(role, [])
    groups.get(role).push(step)
  }
  const order = ['SUPERVISOR', 'PLANNER', 'RESEARCHER', 'ANALYST', 'VERIFIER', 'WRITER', 'HARNESS']
  return [...groups].sort(([a], [b]) => (order.indexOf(a) < 0 ? 99 : order.indexOf(a)) - (order.indexOf(b) < 0 ? 99 : order.indexOf(b))).map(([role, records]) => {
    const failed = records.some(s => ['FAILED', 'TIMED_OUT', 'CANCELLED'].includes(s.status))
    const active = records.some(s => ['RUNNING', 'VERIFYING'].includes(s.status))
    const complete = records.every(s => ['COMPLETED', 'SUCCEEDED', 'SKIPPED'].includes(s.status))
    const labels = { SUPERVISOR: '调度', PLANNER: '规划', RESEARCHER: '检索', ANALYST: '分析', VERIFIER: '验证', WRITER: '报告', HARNESS: '流程执行器' }
    return { id: role, initial: role[0], label: labels[role] || role, role, status: active ? 'active' : failed ? 'failed' : complete ? 'completed' : 'pending', statusText: active ? '执行中' : failed ? '存在中断步骤' : complete ? '已完成' : '等待执行' }
  })
}
