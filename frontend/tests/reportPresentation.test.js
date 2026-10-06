import test from 'node:test'
import assert from 'node:assert/strict'
import { isAppendixSection, nonEmptyReportSections, partitionReportSections } from '../src/utils/reportPresentation.js'

test('empty report sections are removed without mutating the response', () => {
  const sections = [
    { section_id: 'summary', section_type: 'EXECUTIVE_STATUS', content: { units: [{ unit_key: 'u1', text: '结论速览' }] } },
    { section_id: 'empty', section_type: 'AVAILABLE_FINDINGS', content: { units: [] } },
    { section_id: 'blank', section_type: 'NEXT_STEPS', content: { units: [{ unit_key: 'u2', text: '   ' }] } }
  ]
  const visible = nonEmptyReportSections(sections)
  assert.deepEqual(visible.map(section => section.section_id), ['summary'])
  assert.equal(sections.length, 3)
})

test('technical and research material is partitioned into folded appendices', () => {
  const sections = [
    { section_id: 'summary', section_type: 'EXECUTIVE_STATUS', content: { units: [{ text: '结论' }] } },
    { section_id: 'method', section_type: 'RESEARCH_APPENDIX', content: { presentation: 'APPENDIX', units: [{ text: '方法' }] } },
    { section_id: 'diagnostic', section_type: 'TECHNICAL_APPENDIX', content: { units: [{ text: 'SearchUnavailableError' }] } }
  ]
  const grouped = partitionReportSections(sections)
  assert.deepEqual(grouped.body.map(section => section.section_id), ['summary'])
  assert.deepEqual(grouped.appendices.map(section => section.section_id), ['method', 'diagnostic'])
  assert.equal(isAppendixSection(sections[2]), true)
})
