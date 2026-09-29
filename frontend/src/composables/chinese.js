import catalog from '../locales/zh-CN.json' with { type: 'json' }

export const label = value => catalog.labels[value] || value || '未记录'
// Exact, reviewed translations only. Never run this on verbatim evidence.
export const chineseText = value => catalog.texts[value] || value || ''
export function validationExplanation(claim) {
  const status = {
    VERIFIED: '该声明已通过当前验证规则，具体支持范围请核对引用原文。',
    PROBABLE: '现有证据提供一定支持，但充分性仍不足，结论保留不确定性。',
    DISPUTED: '证据之间存在尚未解决的分歧，不能作为已确定的结论。',
    UNVERIFIED: '当前证据尚不足以证实该声明。',
    REJECTED: '该候选声明未通过验证。',
  }[claim?.validation_status] || '该声明尚待完成验证。'
  return status + (claim?.claim_type === 'STATEMENT' ? ' 此处验证的是来源作出该陈述，不等于陈述内容已被独立证实。' : '')
}
