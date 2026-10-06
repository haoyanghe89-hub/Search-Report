<script setup>
defineProps({ modelValue: { type: String, default: 'standard' }, disabled: Boolean })
defineEmits(['update:modelValue'])
const options = [
  { value: 'quick', label: '快速', time: '约 2–5 分钟', hint: '优先整理最重要内容' },
  { value: 'standard', label: '标准', time: '约 10 分钟', hint: '均衡检索与交叉验证' },
  { value: 'deep', label: '深度', time: '30 分钟及以上', hint: '更多材料，多轮验证' },
]
</script>

<template>
  <fieldset class="depth-selector" :disabled="disabled">
    <legend>调查时长</legend>
    <div class="depth-options">
      <label v-for="option in options" :key="option.value" class="depth-option" :class="{ selected: modelValue === option.value }">
        <input type="radio" name="investigation-depth" :value="option.value" :checked="modelValue === option.value" @change="$emit('update:modelValue', option.value)" />
        <span><strong>{{ option.label }}</strong><span class="depth-time">{{ option.time }}</span><small>{{ option.hint }}</small></span>
      </label>
    </div>
    <p>时间越长，材料通常越完整；快速档优先整理最重要内容。各档采用相同的证据确认标准。</p>
  </fieldset>
</template>

<style scoped>
.depth-selector { min-width: 0; margin: 0; padding: 0; border: 0; }
.depth-selector legend { margin-bottom: var(--space-3); color: var(--text-secondary); font-size: var(--font-size-small); }
.depth-options { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.depth-option { display: flex; flex: 1 1 var(--space-32); align-items: flex-start; gap: var(--space-2); min-height: var(--touch-target); padding: var(--space-3); border: var(--border-width) solid var(--border-default); border-radius: var(--radius-md); cursor: pointer; }
.depth-option.selected { border-color: var(--accent); background: var(--accent-subtle); }
.depth-option:hover { border-color: var(--border-strong); }
.depth-option:focus-within { outline: var(--focus-width) solid var(--accent); outline-offset: var(--focus-offset); }
.depth-option input { width: auto; margin: var(--space-1) 0 0; accent-color: var(--accent); }
.depth-option strong, .depth-time, .depth-option small { display: block; }
.depth-option strong { color: var(--text-primary); font-size: var(--font-size-body); }
.depth-time { margin-block: var(--space-1); color: var(--text-secondary); font-size: var(--font-size-small); font-variant-numeric: tabular-nums; }
.depth-option small, .depth-selector p { color: var(--text-muted); font-size: var(--font-size-caption); line-height: var(--line-height-small); }
.depth-selector p { margin: var(--space-2) 0 0; }
</style>
