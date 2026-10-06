<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import request from '../api/request.js'
import { clearDialogMotion, closeDialog, openDialog } from '../utils/dialogMotion.js'
const props = defineProps({ investigation: { type: Object, required: true } })
const emit = defineEmits(['close', 'deleted'])
const modal = ref(null)
const confirmed = ref(false)
const busy = ref(false)
const error = ref('')
let preference
function close() { if (!busy.value) closeDialog(modal.value, preference?.matches) }
function motionChanged(event) { if (event.matches) clearDialogMotion(modal.value, true) }
onMounted(() => {
  preference = window.matchMedia('(prefers-reduced-motion: reduce)')
  preference.addEventListener('change', motionChanged)
  openDialog(modal.value, preference.matches)
})
onUnmounted(() => {
  preference?.removeEventListener('change', motionChanged)
  clearDialogMotion(modal.value)
})
async function remove() {
  if (!confirmed.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await request(`/investigations/${encodeURIComponent(props.investigation.id)}`, { method: 'DELETE' })
    emit('deleted', props.investigation.id)
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
</script>

<template>
  <dialog ref="modal" aria-labelledby="delete-title" aria-describedby="delete-warning" @cancel.prevent="close" @close="emit('close')">
    <form class="delete-form" @submit.prevent="remove">
      <h2 id="delete-title">删除卷宗</h2>
      <p class="archive-title">{{ investigation.name }}</p>
      <p id="delete-warning">将永久删除该调查及其全部运行、来源、证据、声明、报告记录。此操作无法撤销。正在运行的调查须先停止。</p>
      <label class="delete-confirm"><input v-model="confirmed" type="checkbox" :disabled="busy" />我确认永久删除此卷宗及全部关联记录</label>
      <p v-if="error" class="notice error" role="alert">{{ error }}</p>
      <footer><button type="button" class="btn btn-ghost" :disabled="busy" autofocus @click="close">保留卷宗</button><button type="submit" class="btn delete-button" :disabled="!confirmed || busy">{{ busy ? '正在删除…' : '永久删除' }}</button></footer>
    </form>
  </dialog>
</template>

<style scoped>
.delete-form { display: grid; gap: var(--space-4); }
.delete-form h2, .delete-form p { margin: 0; }
.archive-title { color: var(--text-primary); overflow-wrap: anywhere; }
.delete-form p { color: var(--text-secondary); line-height: var(--line-height-body); }
.delete-confirm { display: flex; gap: var(--space-3); align-items: center; min-height: var(--touch-target); font-size: var(--font-size-small); }
.delete-confirm input { width: auto; margin: 0; accent-color: var(--danger); }
footer { display: flex; justify-content: flex-end; gap: var(--space-3); flex-wrap: wrap; }
.delete-button { color: var(--danger); border: var(--border-width) solid var(--danger); background: var(--danger-bg); }
</style>
