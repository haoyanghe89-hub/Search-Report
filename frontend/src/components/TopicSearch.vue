<script setup>
import { nextTick, ref } from 'vue'

const props = defineProps({ busy: Boolean, disabled: Boolean, error: String, compact: Boolean })
const emit = defineEmits(['start'])
const topic = ref('')
const input = ref(null)
const composing = ref(false)
function submit() { if (!composing.value && !props.busy && !props.disabled && topic.value.trim()) emit('start', topic.value.trim()) }
function clear() { topic.value = '' }
async function focus() { await nextTick(); input.value?.focus() }
defineExpose({ focus, clear })
</script>

<template>
  <form class="topic-search panel-enter" :class="{ compact }" aria-label="主题调查" :aria-busy="busy" @submit.prevent="submit">
    <label class="search-label" for="investigation-topic">{{ compact ? '调查新的主题' : '你想调查什么？' }}</label>
    <div class="search topic-input-row">
      <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></svg>
      <input id="investigation-topic" ref="input" v-model="topic" type="text" maxlength="500" required :disabled="busy || disabled" placeholder="输入事件、问题或想了解的主题" :aria-describedby="error ? 'topic-error' : 'topic-hint'" :aria-invalid="Boolean(error)" autocomplete="off" @compositionstart="composing = true" @compositionend="composing = false" @keydown.enter="($event.isComposing || composing) && $event.preventDefault()" />
      <button type="submit" class="btn btn-primary" :disabled="busy || disabled || !topic.trim()">{{ busy ? '正在启动…' : '开始调查' }}<span v-if="!busy" aria-hidden="true">→</span></button>
    </div>
    <p v-if="error" id="topic-error" class="notice error topic-message" role="alert">{{ error }} 可保留当前主题，再次点击“开始调查”重试。</p>
    <p v-else id="topic-hint" class="topic-hint">{{ busy ? '正在创建档案并启动调查，请稍候。' : '检索公开资料，交叉验证证据，整理调查报告。' }}</p>
  </form>
</template>

<style scoped>
.topic-search { width: 100%; }
.search-label { margin: 0 0 var(--space-3); color: var(--text-secondary); font-family: var(--font-display); font-size: var(--font-size-h3); line-height: var(--line-height-h3); }
.topic-input-row { display: flex; min-height: calc(var(--space-16) + var(--space-2)); align-items: center; gap: var(--space-3); margin: 0; padding: var(--space-2); padding-left: var(--space-4); flex-wrap: wrap; }
.topic-input-row:focus-within { border-color: var(--accent); outline: 2px solid var(--accent); outline-offset: 2px; }
.topic-input-row svg { width: var(--space-6); height: var(--space-6); flex-shrink: 0; fill: none; stroke: currentColor; stroke-width: calc(var(--space-1) / 2); color: var(--text-muted); }
.topic-input-row input { min-width: 0; min-height: var(--space-12); flex: 1 1 calc(var(--space-32) + var(--space-32)); margin: 0; padding: 0; border: 0; background: transparent; font-family: var(--font-serif); font-size: var(--font-size-body-lg); line-height: var(--line-height-body-lg); box-shadow: none; }
.topic-input-row input:focus-visible { outline: none; box-shadow: none; }
.topic-input-row .btn { margin-left: auto; flex-shrink: 0; }
.topic-hint { margin: var(--space-3) 0 0; color: var(--text-muted); font-size: var(--font-size-small); line-height: var(--line-height-small); }
.topic-message { margin-top: var(--space-3); }
.compact .search-label { font-size: var(--font-size-body); line-height: var(--line-height-body); }
.compact .topic-input-row { min-height: var(--space-16); }
</style>
