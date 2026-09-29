<script setup>
import { ref, onMounted } from 'vue'
import request from '../api/request.js'
const emit = defineEmits(['close', 'created'])
const modal = ref(null)
const title = ref('')
const description = ref('')
const goal = ref('')
const questions = ref('')
const error = ref('')
const busy = ref(false)
onMounted(() => modal.value.showModal())
async function create() {
  busy.value = true
  error.value = ''
  try {
    const result = await request('/investigations', { method: 'POST', body: JSON.stringify({ title: title.value.trim(), event_description: description.value.trim(), investigation_goal: goal.value.trim(), questions: questions.value.split('\n').map(q => q.trim()).filter(Boolean) }) })
    emit('created', result)
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
</script>
<template>
  <dialog ref="modal" aria-labelledby="new-title" @close="emit('close')">
    <form @submit.prevent="create">
      <div class="row"><h2 id="new-title">新建事件调查</h2><button type="button" @click="emit('close')">关闭</button></div>
      <label>调查标题<input v-model="title" required maxlength="500" autofocus /></label>
      <label>事件描述<textarea v-model="description" required rows="3" placeholder="描述发生了什么，以及已知的时间和地点" /></label>
      <label>调查目标<textarea v-model="goal" required rows="2" /></label>
      <label>关键问题（每行一个，可选）<textarea v-model="questions" rows="4" /></label>
      <p class="muted">创建后可启动联网研究。联网研究需要服务端配置模型密钥，并产生模型调用费用。</p>
      <p v-if="error" class="notice error" role="alert">{{ error }}</p>
      <button class="primary" :disabled="busy || !title.trim() || !description.trim() || !goal.trim()">{{ busy ? '正在创建…' : '创建调查' }}</button>
    </form>
  </dialog>
</template>
