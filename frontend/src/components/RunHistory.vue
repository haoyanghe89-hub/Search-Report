<script setup>
import { computed } from 'vue'
import FolioSelect from './FolioSelect.vue'
import { runStatusLabel, runModeLabel } from '../composables/presentation.js'
const props = defineProps({ runs: { type: Array, required: true }, modelValue: String, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const options = computed(() => props.runs.map((run, index) => ({ value: run.run_id, label: runModeLabel(run), description: run.created_at ? new Date(run.created_at).toLocaleString('zh-CN') : '时间未记录', status: runStatusLabel(run.status), detail: run.run_id, tag: index === 0 ? '最近一次' : '' })))
</script>
<template>
  <FolioSelect label="运行记录" :hint="runs.length + ' 次'" :options="options" :model-value="modelValue" :disabled="disabled" @update:model-value="emit('update:modelValue', $event)" />
</template>
