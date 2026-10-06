<script setup>
import { ref } from 'vue'
import QuantChart from './QuantChart.vue'
const props = defineProps({ data: Object })
const selected = ref(null)
function cell(path) { selected.value = props.data.values.find(v => v.metric_path === path) }
</script>
<template>
  <section v-if="data?.charts?.length" class="quant-report-section" aria-label="量化证据展品">
    <QuantChart v-for="exhibit in data.charts.slice(0,3)" :key="exhibit.exhibit_id" :exhibit="exhibit" @cell="cell" />
    <aside v-if="selected" class="cell-detail" role="region" aria-label="计算证据单元格"><button class="quiet-button" @click="selected = null">关闭单元格</button><h4>{{ selected.name }} · {{ selected.status }}</h4><p>{{ selected.value ?? selected.missing_reason }} {{ selected.unit }} · {{ selected.start }} — {{ selected.end }}</p><p>{{ selected.definition }}</p><pre>{{ JSON.stringify({ artifact_id: selected.artifact_id, metric_path: selected.metric_path, row_keys: selected.row_keys, cell_hash: selected.cell_hash, manifest_hash: data.manifest_hash, input_snapshot_ids: data.input_snapshot_ids }, null, 2) }}</pre><a v-if="selected.citation_id" :href="'/api/citations/' + selected.citation_id" target="_blank" rel="noopener">查看最新验证引用</a></aside>
  </section>
</template>
<style scoped>
.quant-report-section { min-width: 0; }.cell-detail { padding: var(--space-4); background: var(--bg-surface); border-left: 2px solid var(--accent); overflow-wrap: anywhere; }pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: var(--font-size-caption); }
</style>
