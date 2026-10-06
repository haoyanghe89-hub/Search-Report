const APPENDIX_TYPES = new Set([
  'RESEARCH_APPENDIX',
  'TECHNICAL_APPENDIX',
  'SCOPE_AND_MANDATE',
  'INVESTIGATION_QUESTIONS',
  'METHODOLOGY'
])

export function reportSectionUnits(section) {
  const units = Array.isArray(section?.content?.units) ? section.content.units : []
  return units.filter(unit => typeof unit?.text === 'string' && unit.text.trim())
}

export function nonEmptyReportSections(sections) {
  if (!Array.isArray(sections)) return []
  return sections.flatMap(section => {
    const units = reportSectionUnits(section)
    return units.length
      ? [{ ...section, content: { ...(section.content || {}), units } }]
      : []
  })
}

export function isAppendixSection(section) {
  return section?.content?.presentation === 'APPENDIX'
    || APPENDIX_TYPES.has(section?.section_type)
}

export function partitionReportSections(sections) {
  const result = { body: [], appendices: [] }
  for (const section of nonEmptyReportSections(sections)) {
    result[isAppendixSection(section) ? 'appendices' : 'body'].push(section)
  }
  return result
}
