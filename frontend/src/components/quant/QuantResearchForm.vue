<script setup>
import { onUnmounted, ref } from 'vue'
import request from '../../api/request.js'
import DepthSelector from '../DepthSelector.vue'
const props = defineProps({ busy: Boolean })
const emit = defineEmits(['created'])
const query = ref(''), results = ref([]), selected = ref(null), error = ref('')
const start = ref(''), end = ref(''), adjustment = ref('raw'), depth = ref('quick')
const windows = ref([]), frozenWindow = ref('')
let timer, generation = 0
function search() {
  selected.value = null
  clearTimeout(timer)
  const ticket = ++generation
  timer = setTimeout(async () => {
    try { const items = await request('/quant/instruments?q=' + encodeURIComponent(query.value)); if (ticket === generation) results.value = items }
    catch (e) { if (ticket === generation) error.value = e.message }
  }, 200)
}
async function choose(item) {
  selected.value = item; query.value = `${item.code} · ${item.name}`; results.value = []; windows.value = []; frozenWindow.value = ''
  const ticket = ++generation
  try { const data = await request('/quant/instruments/' + item.instrument_id + '/windows'); if (ticket === generation) windows.value = data }
  catch(e) { if(ticket === generation) error.value = e.message }
}
const submitting = ref(false)
async function submit() {
  if (!selected.value || submitting.value) return
  submitting.value = true; error.value = ''
  try {
    const body = { instrument: selected.value.instrument_id, adjustment: adjustment.value, depth: depth.value }
    if (start.value && end.value) Object.assign(body, { date_start: start.value, date_end: end.value })
    const frozen = windows.value.find(w => w.window_id === frozenWindow.value)
    if (frozen) Object.assign(body, { date_start: frozen.date_start, date_end: frozen.date_end, asof: frozen.asof, frozen_snapshot_ids: frozen.frozen_snapshot_ids })
    emit('created', await request('/quant/runs', { method: 'POST', body: JSON.stringify(body) }))
  } catch (e) { error.value = e.message } finally { submitting.value = false }
}
onUnmounted(() => { clearTimeout(timer); generation++ })
</script>
<template>
  <section class="quant-form" aria-label="量化投研参数">
    <label class="field"><span>证券 · 仅已主数据化标的</span><input v-model="query" type="search" placeholder="代码或名称" autocomplete="off" @input="search" aria-controls="quant-suggestions" :aria-expanded="Boolean(results.length)" /></label>
    <ul v-if="results.length" id="quant-suggestions" class="suggestions"><li v-for="item in results" :key="item.instrument_id"><button type="button" @click="choose(item)">{{ item.code }} · {{ item.name }} <small>{{ item.exchange }} / {{ item.status }}</small></button></li></ul>
    <p v-if="selected" class="muted">{{ selected.instrument_id }}</p>
    <label v-if="windows.length" class="field"><span>数据窗口 · 显式冻结选择</span><select v-model="frozenWindow"><option value="">当前截至昨日 · 近一年 / 自定义</option><option v-for="w in windows" :key="w.window_id" :value="w.window_id">{{ w.date_start }} — {{ w.date_end }} · {{ w.sample_count }} 日 · 历史时点 {{ w.asof.slice(0,10) }}</option></select></label>
    <p v-if="frozenWindow" class="notice info">本次使用已冻结的历史窗口，不替换为最新行情；短窗口与回溯财报限制将写入报告。</p>
    <div v-else class="dates"><label class="field"><span>开始日（缺省近一年）</span><input v-model="start" type="date" /></label><label class="field"><span>结束日 · 完整历史收盘</span><input v-model="end" type="date" /></label></div>
    <label class="field"><span>价格口径</span><select v-model="adjustment"><option value="raw">raw · 未复权价格收益</option><option value="qfq">qfq · 冻结锚点前复权代理</option><option value="hfq">hfq · 冻结锚点后复权代理</option></select></label>
    <DepthSelector v-model="depth" :disabled="busy || submitting" />
    <p class="notice info">仅冻结数据与确定性计算，不由模型生成数值。资料不足会保留部分报告；未填基准与无风险利率不会写零，不提供交易或预测。</p>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <button type="button" class="btn btn-primary" :disabled="!selected || busy || submitting || Boolean(start) !== Boolean(end)" @click="submit">{{ submitting ? '正在启动…' : '启动量化投研' }}</button>
  </section>
</template>
<style scoped>
.quant-form { display: grid; gap: var(--space-4); min-width: 0; }
.dates { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: var(--space-4); }
.field { margin: 0; min-width: 0; }.field input, .field select { width: 100%; min-width: 0; box-sizing: border-box; }
.suggestions { list-style: none; margin: 0; padding: 0; border-block: 1px solid var(--border-default); max-height: 220px; overflow: auto; }
.suggestions button { width: 100%; text-align: left; padding: var(--space-3); background: transparent; color: var(--text-primary); border: 0; cursor: pointer; }
.suggestions button:hover { background: var(--bg-elevated); }.suggestions small { color: var(--text-muted); }.muted { overflow-wrap: anywhere; }
@media(max-width:480px) { .dates { grid-template-columns: 1fr; } }
</style>
