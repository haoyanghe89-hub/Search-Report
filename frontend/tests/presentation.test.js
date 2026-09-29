import test from 'node:test'
import assert from 'node:assert/strict'
import { verificationSummary, projectAgents, resultsPending } from '../src/composables/presentation.js'

test('old results remain hidden throughout replay, submission, execution and new-result loading', () => {
  const phases = [{ replaying: true }, { replaying: true, loading: true }, { loading: true }, { starting: true }, { running: true }, { running: true, loading: true }]
  for (const phase of phases) assert.equal(resultsPending(phase), true)
  assert.equal(resultsPending({}), false)
  assert.equal(resultsPending({ replaying: false, starting: false, running: false, loading: false }), false)
})

test('empty and pending claims never appear verified', () => {
  assert.equal(verificationSummary([]).label, '尚无验证结果')
  assert.deepEqual(verificationSummary([{ validation_status: 'PENDING' }, { validation_status: 'VERIFIED' }]), { verified: 1, label: '1 / 2 条已验证' })
})
test('agent display preserves interruption and pending states', () => {
  assert.deepEqual(projectAgents([]), [])
  const roles = projectAgents([{ agent_role: 'VERIFIER', status: 'COMPLETED' }, { agent_role: 'VERIFIER', status: 'FAILED' }, { agent_role: 'RESEARCHER', status: 'PENDING' }])
  assert.equal(roles.find(r => r.id === 'VERIFIER').status, 'failed')
  assert.equal(roles.find(r => r.id === 'RESEARCHER').status, 'pending')
})
