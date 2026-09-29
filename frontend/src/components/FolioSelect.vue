<script setup>
import { computed, ref, nextTick, onMounted, onUnmounted, watch, getCurrentInstance } from 'vue'
const props = defineProps({ options: { type: Array, required: true }, modelValue: String, disabled: Boolean, label: { type: String, required: true }, hint: String, placeholder: { type: String, default: '请选择' } })
const id = 'folio-select-' + getCurrentInstance().uid
const emit = defineEmits(['update:modelValue'])
const open = ref(false)
const root = ref(null)
const trigger = ref(null)
const selected = computed(() => props.options.find(r => r.value === props.modelValue))
async function toggle() {
  if (props.disabled || !props.options.length) return
  open.value = !open.value
  if (open.value) { await nextTick(); const index = Math.max(0, props.options.findIndex(r => r.value === props.modelValue)); root.value.querySelectorAll('[role="option"]')[index]?.focus() }
}
function close(focus = false) { open.value = false; if (focus) trigger.value?.focus() }
function choose(id) { emit('update:modelValue', id); close(true) }
function navigate(event) {
  if (event.key === 'Escape') { event.preventDefault(); close(true); return }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const items = [...root.value.querySelectorAll('[role="option"]')]
  const index = items.indexOf(document.activeElement)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
  items[next]?.focus()
}
function outside(event) { if (!root.value?.contains(event.target)) close() }
function blur(event) { if (!root.value?.contains(event.relatedTarget)) close() }
watch(() => props.disabled, value => { if (value) close() })
onMounted(() => document.addEventListener('pointerdown', outside))
onUnmounted(() => document.removeEventListener('pointerdown', outside))
</script>
<template>
  <div ref="root" class="folio-select" @focusout="blur">
    <span :id="id + '-label'" class="history-label">{{ label }} <span v-if="hint">{{ hint }}</span></span>
    <button ref="trigger" type="button" class="history-trigger" aria-haspopup="listbox" :aria-expanded="open" :aria-controls="open ? id + '-list' : undefined" :aria-labelledby="id + '-label ' + id + '-value'" :disabled="disabled || !options.length" @click="toggle" @keydown.down.prevent="!open && toggle()" @keydown.up.prevent="!open && toggle()">
      <span :id="id + '-value'" class="history-option-copy"><strong>{{ selected?.label || placeholder }}</strong><span v-if="selected?.description" class="history-description">{{ selected.description }}</span></span><span v-if="selected?.status" class="history-state">{{ selected.status }}</span><span class="history-chevron" :class="{ open }" aria-hidden="true">⌄</span>
    </button>
    <div v-if="open" :id="id + '-list'" class="history-menu" role="listbox" :aria-label="label" @keydown="navigate">
      <button v-for="item in options" :key="item.value" type="button" role="option" :aria-selected="item.value === modelValue" tabindex="-1" class="history-option" @click="choose(item.value)"><span class="history-check">{{ item.value === modelValue ? '✓' : '' }}</span><span class="history-option-copy"><strong>{{ item.label }} <small v-if="item.tag">{{ item.tag }}</small></strong><span v-if="item.description" class="history-description">{{ item.description }}</span><small v-if="item.detail" class="history-id">{{ item.detail }}</small></span><span v-if="item.status" class="history-state">{{ item.status }}</span></button>
    </div>
  </div>
</template>
<style scoped>
.folio-select { position: relative; width: min(100%, 760px); }
.history-label { display: block; color: var(--ink-muted); font-size: 13px; margin-bottom: 10px; }
.history-label span { color: var(--ink-faint); font: 10px var(--font-mono); margin-left: 10px; }
.folio-select .history-trigger { width: 100%; display: flex; align-items: center; gap: 20px; padding: 16px 20px; text-align: left; background: var(--paper-warm); border: 1px solid var(--paper-edge); border-radius: 2px; color: var(--ink-deep); }
.history-trigger:hover { border-color: var(--accent-line); }
strong { font: 500 15px var(--font-serif); }
.history-description { display: block; font: 11px var(--font-mono); color: var(--ink-muted); margin-top: 5px; }
.history-state { margin-left: auto; white-space: nowrap; color: var(--accent); font: 12px var(--font-serif); }
.history-chevron { margin-left: auto; flex-shrink: 0; font-size: 18px; color: var(--accent); transition: transform .2s; }
.history-chevron.open { transform: rotate(180deg); }
.history-menu { position: absolute; top: calc(100% + 6px); left: 0; right: 0; z-index: 20; max-height: 360px; overflow-y: auto; padding: 6px; background: var(--paper-base); border: 1px solid var(--accent-line); box-shadow: 0 12px 30px var(--paper-shadow); }
.folio-select .history-option { display: flex; align-items: center; gap: 12px; width: 100%; padding: 14px 12px; text-align: left; color: var(--ink-deep); background: transparent; border: 0; border-radius: 0; border-bottom: 1px solid var(--paper-edge); }
.history-option:last-child { border-bottom: 0; }
.history-option:hover, .history-option:focus-visible, .history-option[aria-selected="true"] { background: var(--accent-pale); }
.history-option:focus-visible { outline-offset: -2px; }
.history-check { width: 14px; flex-shrink: 0; color: var(--accent); }
.history-option-copy { min-width: 0; overflow-wrap: anywhere; }
.history-option small { color: var(--ink-faint); font-size: 10px; margin-left: 8px; }
.history-option .history-id { display: block; overflow: hidden; text-overflow: ellipsis; margin: 5px 0 0; font: 9px var(--font-mono); }
@media (max-width: 500px) { .folio-select .history-trigger { gap: 10px; padding: 14px 12px; } .folio-select .history-option { gap: 8px; } .history-option .history-state { font-size: 11px; } }
</style>
