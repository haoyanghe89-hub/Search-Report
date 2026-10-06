const names = { chart_price_raw: '未复权价格', chart_price_qfq: '前复权价格', chart_price_hfq: '后复权价格', chart_drawdown_raw: '回撤', chart_drawdown_qfq: '回撤', chart_drawdown_hfq: '回撤', pe: '独立 PE', pb: '独立 PB', disclosed_pe_ttm: '披露 PE', disclosed_pb_mrq: '披露 PB', chart_parent_net_profit_growth: '归母净利润同比', chart_revenue_growth: '营业收入同比' }
export const seriesLabel = name => names[name] || name
// Only presentation conversion for ECharts; no returns, ratios or valuation formulas here.
export function chartOptions(exhibit, { adjustment = 'raw', reducedMotion = false, accent = '#4f46e5', text = '#707078', border = '#e4e4e8' } = {}) {
  const selected = exhibit.series.filter(s => exhibit.kind !== 'price' || s.name.endsWith('_' + adjustment))
  const categories = [...new Set(selected.flatMap(s => s.points.map(p => p.x)))].sort()
  const valuation = exhibit.kind === 'valuation'
  const values = valuation ? selected.flatMap(s => s.points.map((p,i) => ({ label: `${seriesLabel(s.name)} · ${p.label?.split(' · ')[1] || i+1}`, value: p.value }))) : []
  return {
    animation: !reducedMotion, color: [accent, text],
    tooltip: { trigger: 'axis', renderMode: 'richText', confine: true },
    legend: { show: !valuation, top: 0, textStyle: { color: text, fontSize: 11 } },
    grid: { top: 48, bottom: valuation ? 90 : 40, left: 52, right: 48 },
    xAxis: { type: 'category', data: valuation ? values.map(v => v.label) : categories, axisLabel: { color: text, fontSize: 10, rotate: valuation ? 35 : 0 }, axisLine: { lineStyle: { color: border } } },
    yAxis: [{ type: 'value', name: valuation ? '倍' : exhibit.kind === 'financial' ? '同比 fraction' : 'CNY/share', scale: true, axisLabel: { color: text }, splitLine: { lineStyle: { color: border } } }, ...(exhibit.kind === 'price' ? [{ type: 'value', name: '回撤 fraction', axisLabel: { color: text }, splitLine: { show: false } }] : [])],
    series: valuation ? [{ type: 'bar', data: values.map(v => Number(v.value)), barMaxWidth: 32 }] : selected.map((s,i) => ({ name: seriesLabel(s.name), type: 'line', yAxisIndex: s.name.startsWith('chart_drawdown') ? 1 : 0,
      connectNulls: false, showSymbol: false, lineStyle: { width: 2, type: i ? 'dashed' : 'solid' },
      data: categories.map(x => { const p = s.points.find(p => p.x === x); return p?.value == null ? null : Number(p.value) }) })),
  }
}
