<script setup>
import { ref, nextTick } from 'vue'
const props = defineProps({ busy: Boolean, disabled: Boolean, error: String, compact: Boolean })
const emit = defineEmits(['start'])
const topic = ref('')
const input = ref(null)
const composing = ref(false)
function submit() {
  if (!composing.value && !props.busy && !props.disabled && topic.value.trim()) emit('start', topic.value.trim())
}
function clear() { topic.value = '' }
async function focus() { await nextTick(); input.value?.focus() }
defineExpose({ focus, clear })
</script>
<template>
  <form class="topic-search" :class="{ compact }" aria-label="主题调查" :aria-busy="busy" @submit.prevent="submit">
    <label for="investigation-topic">{{ compact ? '调查新的主题' : '你想调查什么？' }}</label>
    <div class="topic-input-row">
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></svg>
      <input id="investigation-topic" ref="input" v-model="topic" type="text" maxlength="500" required :disabled="busy || disabled" placeholder="输入事件、问题或想了解的主题" :aria-describedby="error ? 'topic-error' : 'topic-hint'" :aria-invalid="Boolean(error)" autocomplete="off" @compositionstart="composing = true" @compositionend="composing = false" @keydown.enter="($event.isComposing || composing) && $event.preventDefault()" />
      <button type="submit" :disabled="busy || disabled || !topic.trim()">{{ busy ? '正在启动…' : '开始调查' }}<span v-if="!busy" aria-hidden="true">→</span></button>
    </div>
    <p v-if="error" id="topic-error" class="topic-error" role="alert">{{ error }} 可保留当前主题，再次点击“开始调查”重试。</p>
    <p v-else id="topic-hint" class="topic-hint">{{ busy ? '正在创建档案并启动调查，请稍候。' : '检索公开资料，交叉验证证据，整理调查报告。' }}</p>
  </form>
</template>
<style scoped>
.topic-search { width: 100%; }
.topic-search label { margin: 0 0 14px; font: 20px var(--font-serif); color: var(--ink-soft); }
.topic-input-row { display: flex; align-items: center; gap: 16px; padding: 10px 10px 10px 20px; border: 1px solid var(--accent-line); background: var(--paper-base); box-shadow: 0 4px 18px #30271906; }
.topic-input-row:focus-within { border-color: var(--accent); }
.topic-input-row svg { flex-shrink: 0; color: var(--ink-faint); }
.topic-input-row input { min-width: 0; flex: 1; margin: 0; padding: 12px 0; border: 0; background: transparent; font: 17px/1.6 var(--font-serif); box-shadow: none; }
.topic-input-row input:focus-visible { outline-offset: 2px; }
.topic-input-row button { display: flex; align-items: center; justify-content: center; gap: 22px; flex-shrink: 0; margin: 0; border: 1px solid var(--ink-black); padding: 16px 24px; background: var(--ink-black); color: var(--paper-base); font: 16px var(--font-serif); }
.topic-search .topic-hint, .topic-search .topic-error { margin: 12px 0 0; font-size: 13px; line-height: 1.8; color: var(--ink-muted); }
.topic-search .topic-error { color: #993d32; }
.compact label { font-size: 14px; margin-bottom: 10px; }
.compact input { font-size: 15px; }
.compact button { padding: 12px 20px; font-size: 14px; }
@media (max-width: 640px) {
  .topic-input-row { flex-wrap: wrap; gap: 8px; padding: 12px; }
  .topic-input-row input { font-size: 15px; }
  .topic-input-row button { width: 100%; padding: 13px; }
}
</style>
