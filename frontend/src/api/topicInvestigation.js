// Keep the created archive across retries, including a lost start response.
export function createTopicLauncher(request) {
  let draft = null
  let inFlight = null
  async function launch(topic) {
    const title = topic.trim()
    if (!title || title.length > 500) throw new Error('请输入 1–500 字的调查主题。')
    if (draft?.title !== title) draft = null
    if (!draft) {
      const created = await request('/investigations', {
        method: 'POST',
        body: JSON.stringify({
          title,
          event_description: title,
          investigation_goal: `围绕“${title}”检索公开资料，梳理事实与背景，交叉验证关键说法，明确争议和证据缺口。`,
          questions: [
            `关于“${title}”，有哪些可以核实的关键事实和背景？`,
            '哪些第一手资料和独立来源支持这些事实？',
            '有哪些相互矛盾的说法、反证或尚未解决的问题？',
            '现有证据能支持哪些结论，哪些仍需要进一步调查？',
          ],
        }),
      })
      draft = { title, id: created.investigation_id }
    } else {
      const history = await request(`/investigations/${draft.id}/runs`)
      if (history.length) {
        const result = { investigation_id: draft.id, run_id: history[0].run_id }
        draft = null
        return result
      }
    }
    const run = await request(`/investigations/${draft.id}/runs`, { method: 'POST' })
    const result = { investigation_id: draft.id, run_id: run.run_id }
    draft = null
    return result
  }
  return topic => {
    if (inFlight) return inFlight
    inFlight = launch(topic).finally(() => { inFlight = null })
    return inFlight
  }
}
