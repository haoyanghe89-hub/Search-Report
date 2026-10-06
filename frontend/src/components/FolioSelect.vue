<script setup>
import { computed, getCurrentInstance, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import gsap from 'gsap'
import { tokenDuration, tokenEase, tokenLength } from '../utils/motionTokens.js'

const props = defineProps({ options: { type: Array, required: true }, modelValue: String, disabled: Boolean, label: { type: String, required: true }, hint: String, placeholder: { type: String, default: '请选择' } })
const id = 'folio-select-' + getCurrentInstance().uid
const emit = defineEmits(['update:modelValue'])
const open = ref(false)
const root = ref(null)
const trigger = ref(null)
const menu = ref(null)
let menuTween = null
let motionPreference = null
const selected = computed(() => props.options.find(r => r.value === props.modelValue))
function showMenuFinal() {
  if (menu.value) gsap.set(menu.value, { opacity: 1, y: 0, clearProps: 'transform' })
}
function revealMenu() {
  if (!menu.value) return
  menuTween?.kill()
  if (motionPreference?.matches) {
    showMenuFinal()
    return
  }
  menuTween = gsap.fromTo(menu.value, { opacity: 0, y: -tokenLength('--motion-distance-tab') }, { opacity: 1, y: 0, duration: tokenDuration('--dur-sm'), ease: tokenEase('--ease-gsap-reveal'), onComplete: () => gsap.set(menu.value, { clearProps: 'opacity,transform' }) })
}
async function toggle() { if (props.disabled || !props.options.length) return; open.value = !open.value; if (open.value) { await nextTick(); revealMenu(); const index = Math.max(0, props.options.findIndex(r => r.value === props.modelValue)); root.value.querySelectorAll('[role="option"]')[index]?.focus() } }
function close(focus = false) { menuTween?.kill(); open.value = false; if (focus) trigger.value?.focus() }
function choose(id) { emit('update:modelValue', id); close(true) }
function navigate(event) { if (event.key === 'Escape') { event.preventDefault(); close(true); return } if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return; event.preventDefault(); const items = [...root.value.querySelectorAll('[role="option"]')]; const index = items.indexOf(document.activeElement); const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length; items[next]?.focus() }
function outside(event) { if (!root.value?.contains(event.target)) close() }
function blur(event) { if (!root.value?.contains(event.relatedTarget)) close() }
watch(() => props.disabled, value => { if (value) close() })
function handleMotionPreference(event) {
  if (event.matches) {
    menuTween?.kill()
    showMenuFinal()
  }
}
onMounted(() => {
  motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
  motionPreference.addEventListener('change', handleMotionPreference)
  document.addEventListener('pointerdown', outside)
})
onUnmounted(() => {
  motionPreference?.removeEventListener('change', handleMotionPreference)
  document.removeEventListener('pointerdown', outside)
  menuTween?.kill()
  if (menu.value) gsap.killTweensOf(menu.value)
})
</script>

<template>
  <div ref="root" class="folio-select field" @focusout="blur">
    <span :id="id + '-label'" class="select-label">{{ label }} <small v-if="hint">{{ hint }}</small></span>
    <button ref="trigger" type="button" class="select-trigger" aria-haspopup="listbox" :aria-expanded="open" :aria-controls="open ? id + '-list' : undefined" :aria-labelledby="id + '-label ' + id + '-value'" :disabled="disabled || !options.length" @click="toggle" @keydown.down.prevent="!open && toggle()" @keydown.up.prevent="!open && toggle()">
      <span :id="id + '-value'" class="select-copy"><strong>{{ selected?.label || placeholder }}</strong><span v-if="selected?.description" class="select-description">{{ selected.description }}</span></span><span v-if="selected?.status" class="badge unverified">{{ selected.status }}</span><span class="select-chevron" :class="{ open }" aria-hidden="true">⌄</span>
    </button>
    <div v-if="open" :id="id + '-list'" ref="menu" class="card select-menu" role="listbox" :aria-label="label" @keydown="navigate">
      <button v-for="item in options" :key="item.value" type="button" role="option" :aria-selected="item.value === modelValue" tabindex="-1" class="record select-option" @click="choose(item.value)">
        <span class="select-check" aria-hidden="true">{{ item.value === modelValue ? '✓' : '' }}</span><span class="select-copy"><strong>{{ item.label }} <small v-if="item.tag" class="option-tag">{{ item.tag }}</small></strong><span v-if="item.description" class="select-description">{{ item.description }}</span><small v-if="item.detail" class="select-id">{{ item.detail }}</small></span><span v-if="item.status" class="badge unverified">{{ item.status }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.folio-select { position: relative; width: min(100%, calc(var(--content-max-width) - var(--space-32) - var(--space-32) - var(--space-32))); margin-block: 0; }
.select-label { color: var(--text-muted); font-size: var(--font-size-small); line-height: var(--line-height-small); }
.select-label small { margin-left: var(--space-2); color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-size-overline); }
.select-trigger { display: flex; width: 100%; height: auto; min-height: calc(var(--space-10) + var(--space-3)); align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4); border: calc(var(--space-1) / 4) solid var(--border-default); border-radius: var(--radius-md); background: var(--bg-surface); color: var(--text-primary); text-align: left; transition: border-color var(--dur-sm) var(--ease-standard), box-shadow var(--dur-sm) var(--ease-standard), background var(--dur-sm) var(--ease-standard); }
.select-trigger:hover:not(:disabled), .select-trigger[aria-expanded='true'] { border-color: var(--border-strong); background: var(--bg-elevated); }
.select-copy { display: grid; min-width: 0; flex: 1; gap: var(--space-1); overflow-wrap: anywhere; }
.select-copy strong { color: var(--text-primary); font-family: var(--font-display); font-size: var(--font-size-body); font-weight: var(--font-weight-h4); line-height: var(--line-height-body); }
.select-description, .select-id { display: block; color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-size-caption); line-height: var(--line-height-caption); }
.select-id { color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; }
.select-chevron { flex-shrink: 0; color: var(--accent); font-size: var(--font-size-h3); transition: transform var(--dur-sm) var(--ease-standard); }
.select-chevron.open { transform: rotate(.5turn); }
.select-menu { position: absolute; z-index: var(--z-popover); top: calc(100% + var(--space-2)); right: 0; left: 0; display: grid; max-height: calc(var(--space-32) + var(--space-32) + var(--space-24)); gap: var(--space-1); padding: var(--space-2); overflow-y: auto; background: var(--bg-elevated); box-shadow: var(--shadow-soft); }
.select-option { display: flex; width: 100%; height: auto; min-height: var(--space-16); align-items: center; gap: var(--space-3); margin: 0; padding: var(--space-3); border-color: transparent; text-align: left; cursor: pointer; }
.select-option + .select-option { margin-top: 0; }
.select-option:hover, .select-option:focus-visible, .select-option[aria-selected='true'] { border-color: var(--border-strong); background: var(--accent-subtle); box-shadow: none; transform: none; }
.select-check { width: var(--space-4); flex-shrink: 0; color: var(--accent); }
.option-tag { margin-left: var(--space-2); color: var(--warning); font-family: var(--font-mono); font-size: var(--font-size-overline); }
@media (prefers-reduced-motion: reduce) { .select-chevron { transition: none; } }
</style>
