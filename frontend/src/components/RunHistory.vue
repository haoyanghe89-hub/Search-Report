<script setup>
import { runStatusLabel, runModeLabel } from '../composables/presentation.js'

defineProps({ runs: { type: Array, required: true }, modelValue: String, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const statusClass = status => ['COMPLETED', 'SUCCEEDED', 'READY_FOR_REPORT'].includes(status) ? 'verified' : ['FAILED', 'CANCELLED', 'INTERRUPTED', 'BLOCKED', 'TIMED_OUT'].includes(status) ? 'disputed' : ['RUNNING', 'VERIFYING'].includes(status) ? 'probable' : 'unverified'
const runTime = run => run.created_at ? new Date(run.created_at).toLocaleString('zh-CN') : '时间未记录'
</script>

<template>
  <section class="run-history panel-enter" aria-label="运行记录">
    <header class="history-heading"><span>运行记录</span><span class="badge unverified">{{ runs.length }} 次</span></header>
    <div class="history-list" role="listbox" aria-label="选择调查运行">
      <button v-for="(run, index) in runs" :key="run.run_id" type="button" class="record history-record" role="option" :aria-selected="run.run_id === modelValue" :disabled="disabled" @click="emit('update:modelValue', run.run_id)">
        <span class="history-copy"><strong>{{ runModeLabel(run) }}</strong><small>{{ runTime(run) }}</small><span class="history-id">{{ run.run_id }}</span></span>
        <span class="history-badges"><span v-if="index === 0" class="badge probable">最近一次</span><span class="badge" :class="statusClass(run.status)">{{ runStatusLabel(run.status) }}</span></span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.run-history { width: 100%; }
.history-heading, .history-record, .history-badges { display: flex; align-items: center; gap: var(--space-3); }
.history-heading { justify-content: space-between; margin-bottom: var(--space-3); color: var(--text-muted); font-size: var(--font-size-small); }
.history-list { display: grid; gap: var(--space-2); }
.history-record { width: 100%; height: auto; min-height: var(--space-16); justify-content: space-between; padding: var(--space-3) var(--space-4); text-align: left; cursor: pointer; transition: border-color var(--dur-sm) var(--ease-standard), background var(--dur-sm) var(--ease-standard); }
.history-record + .history-record { margin-top: 0; }
.history-record:hover:not(:disabled) { border-color: var(--border-strong); background: var(--bg-elevated); }
.history-record[aria-selected='true'] { border-color: var(--border-strong); background: var(--accent-subtle); }
.history-copy { display: grid; min-width: 0; gap: var(--space-1); }
.history-copy strong { color: var(--text-primary); font-family: var(--font-display); font-size: var(--font-size-h4); font-weight: var(--font-weight-h4); }
.history-copy small, .history-id { color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-size-caption); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.history-id { color: var(--text-muted); }
.history-badges { justify-content: flex-end; flex-wrap: wrap; }
</style>
