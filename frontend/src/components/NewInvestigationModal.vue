<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import request from '../api/request.js'
import DepthSelector from './DepthSelector.vue'
import QuantResearchForm from './quant/QuantResearchForm.vue'
import { clearDialogMotion, closeDialog, openDialog } from '../utils/dialogMotion.js'

const emit = defineEmits(['close', 'created'])
const modal = ref(null)
const title = ref('')
const depth = ref('standard')
const description = ref('')
const goal = ref('')
const questions = ref('')
const error = ref('')
const busy = ref(false)
const mode = ref('web')
let motionPreference = null

function requestClose() {
  if (busy.value) return
  closeDialog(modal.value, motionPreference?.matches)
}

function handleMotionPreference(event) {
  if (event.matches && modal.value?.open) clearDialogMotion(modal.value, true)
}

onMounted(() => {
  motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
  motionPreference.addEventListener('change', handleMotionPreference)
  openDialog(modal.value, motionPreference.matches)
})

onUnmounted(() => {
  motionPreference?.removeEventListener('change', handleMotionPreference)
  clearDialogMotion(modal.value)
})
async function create() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await request('/investigations', { method: 'POST', body: JSON.stringify({ title: title.value.trim(), depth: depth.value, event_description: description.value.trim(), investigation_goal: goal.value.trim(), questions: questions.value.split('\n').map(q => q.trim()).filter(Boolean) }) })
    emit('created', result)
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
</script>

<template>
  <dialog ref="modal" class="new-investigation-dialog" aria-labelledby="new-title" @cancel.prevent="requestClose" @close="emit('close')">
    <form class="dialog-form" @submit.prevent="create">
      <header class="dialog-heading"><div><span class="dialog-kicker">新工作卷宗</span><h2 id="new-title">{{ mode === 'quant' ? '量化投研' : '新建事件调查' }}</h2></div><button type="button" class="quiet-button" @click="requestClose">关闭</button></header>
      <div class="mode-choice" role="group" aria-label="工作模式"><button type="button" class="btn btn-ghost" :aria-pressed="mode === 'web'" @click="mode = 'web'">网页调查</button><button type="button" class="btn btn-ghost" :aria-pressed="mode === 'quant'" @click="mode = 'quant'">量化投研</button></div>
      <QuantResearchForm v-if="mode === 'quant'" :busy="busy" @created="emit('created', $event)" />
      <template v-else>
      <label class="field"><span>调查标题</span><input v-model="title" required maxlength="500" autofocus /></label>
      <DepthSelector v-model="depth" :disabled="busy" />
      <label class="field"><span>事件描述</span><textarea v-model="description" required rows="3" placeholder="描述发生了什么，以及已知的时间和地点" /></label>
      <label class="field"><span>调查目标</span><textarea v-model="goal" required rows="2" /></label>
      <label class="field"><span>关键问题（每行一个，可选）</span><textarea v-model="questions" rows="4" /></label>
      <p class="notice info">创建后可启动联网研究。联网研究需要服务端配置模型密钥，并产生模型调用费用。</p>
      <p v-if="error" class="notice error" role="alert">{{ error }}</p>
      <footer class="dialog-actions"><button type="button" class="btn btn-ghost" @click="requestClose">取消</button><button class="btn btn-primary" :disabled="busy || !title.trim() || !description.trim() || !goal.trim()">{{ busy ? '正在创建…' : '创建调查' }}</button></footer>
      </template>
    </form>
  </dialog>
</template>

<style scoped>
.new-investigation-dialog { max-width: calc(var(--content-max-width) - var(--space-32) - var(--space-32) - var(--space-24)); }
.dialog-form { display: grid; gap: var(--space-4); }
.dialog-heading, .dialog-actions { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); flex-wrap: wrap; }
.dialog-kicker { color: var(--accent); font-family: var(--font-mono); font-size: var(--font-size-overline); font-weight: var(--font-weight-overline); letter-spacing: var(--letter-spacing-overline); }
.dialog-heading h2 { margin: var(--space-1) 0 0; }
.dialog-form .field { margin: 0; }
.dialog-actions { justify-content: flex-end; padding-top: var(--space-2); }
</style>
