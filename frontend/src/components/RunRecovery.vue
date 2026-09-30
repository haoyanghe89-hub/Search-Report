<script setup>
import { watch, onUnmounted } from 'vue'
import { recoveryBudgetFields, useRunRecovery } from '../composables/useRunRecovery.js'
const props = defineProps({ runId: { type: String, required: true }, busy: Boolean })
const emit = defineEmits(['resumed', 'busy'])
const { recovery, loading, submitting, accepted, error, consent, increase, validIncrease, allAcknowledged, canSubmit, load, clear, dispose, resume } = useRunRecovery({ onResumed: result => emit('resumed', result) })
watch(() => props.runId, id => { clear(); load(id) }, { immediate: true })
watch(submitting, value => emit('busy', value), { flush: 'sync' })
onUnmounted(dispose)
function amount(value, scale = 1) { return Number.isFinite(value) ? (value / scale).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '—' }
</script>

<template>
  <section class="run-recovery" aria-label="继续原调查" :aria-busy="loading || submitting">
    <h2>继续原调查</h2>
    <p>从已保存的检查点继续，复用已落盘结果。运行编号和已消耗预算保留。开启自动恢复时，符合条件的中断会自动继续；费用不明或预算不足仍需手动处理。</p>
    <p v-if="loading" role="status">正在检查恢复条件…</p>
    <p v-if="error" class="recovery-error" role="alert">{{ error }}</p>
    <p v-if="recovery?.reason" class="recovery-reason">{{ recovery.reason }}</p>
    <form v-if="recovery?.can_resume" @submit.prevent="!busy && resume()">
      <fieldset :disabled="busy || submitting || accepted">
        <legend>追加预算（可选）</legend>
        <p class="muted">仅增加上限，不清零用量；填 0 表示不追加。追加额度可能增加实际调用费用。</p>
        <div class="budget-grid">
          <label v-for="field in recoveryBudgetFields" :key="field.key">
            <span>{{ field.label }}</span>
            <small>已用 {{ amount(recovery.budget?.[field.used], field.scale) }} / 上限 {{ amount(recovery.budget?.['max_' + field.key], field.scale) }}</small>
            <input v-model="increase[field.key]" type="number" min="0" step="1" required :aria-label="'追加' + field.label" />
          </label>
        </div>
      </fieldset>
      <fieldset v-if="recovery.unknown_calls?.length" :disabled="busy || submitting || accepted" class="unknown-calls">
        <legend>有 {{ recovery.unknown_calls.length }} 个调用的执行结果不明</legend>
        <p>供应商可能已经完成并计费，但本地没有响应记录。只有逐项接受可能重复计费，才能重试这些调用。</p>
        <label v-for="call in recovery.unknown_calls" :key="call.intent_id" class="call-consent">
          <input v-model="consent" type="checkbox" :value="call.intent_id" />
          <span>允许重试并接受可能重复的费用<small>{{ call.logical_step_key }} · {{ call.call_site_key }}</small><small>调用编号：{{ call.intent_id }}</small></span>
        </label>
      </fieldset>
      <p v-if="!validIncrease" role="alert">追加额度必须为非负整数。</p>
      <p v-if="!allAcknowledged" class="muted">请逐项确认未知调用；未确认时不会继续运行。</p>
      <button type="submit" :disabled="busy || !canSubmit">{{ submitting ? '正在提交恢复…' : accepted ? '已提交，等待执行…' : '继续这次调查' }}</button>
    </form>
    <button v-if="!accepted" type="button" class="refresh-recovery" :disabled="busy || loading || submitting" @click="load(runId)">重新检查恢复条件</button>
  </section>
</template>

<style scoped>
.run-recovery { margin: 24px 0 36px; padding: 24px; border: 1px solid var(--accent-line); background: var(--paper-warm); }
h2 { margin: 0 0 12px; font: 500 24px var(--font-display); }
p { margin: 12px 0; line-height: 1.7; }
fieldset { margin: 20px 0; border: 0; padding: 0; min-width: 0; }
legend { font-weight: 600; }
.budget-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; }
.budget-grid label { display: flex; flex-direction: column; gap: 7px; font-size: 14px; }
.budget-grid input { width: 100%; min-width: 0; padding: 8px; border: 1px solid var(--paper-edge); background: var(--paper-base); color: var(--ink-deep); }
small { display: block; color: var(--ink-muted); font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.call-consent { display: flex; align-items: flex-start; gap: 12px; margin-top: 16px; font-size: 14px; }
.call-consent input { margin: 5px 0 0; padding: 0; width: auto; flex-shrink: 0; }
.recovery-error, .recovery-reason { border-left: 2px solid var(--accent); padding-left: 12px; overflow-wrap: anywhere; }
button { padding: 10px 16px; border: 1px solid var(--accent-line); background: var(--ink-black); color: var(--paper-base); cursor: pointer; }
.run-recovery button[type="submit"] { background: var(--ink-black); color: var(--paper-base); }
button:disabled { opacity: .5; cursor: not-allowed; }
.refresh-recovery { margin-top: 16px; background: transparent; color: var(--ink-muted); }
.muted { color: var(--ink-muted); font-size: 13px; }
</style>
