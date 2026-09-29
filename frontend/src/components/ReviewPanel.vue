<script setup>
import { ref, onMounted } from 'vue'
import FolioSelect from './FolioSelect.vue'
import request from '../api/request.js'
const props = defineProps({ reportId: { type: String, required: true } })
const emit = defineEmits(['updated'])
const review = ref(null)
const reviewer = ref(null)
const password = ref('')
const decision = ref('REQUEST_MORE_RESEARCH')
const decisionOptions = [{ value: 'REQUEST_MORE_RESEARCH', label: '要求补充研究' }, { value: 'REJECT', label: '驳回' }, { value: 'APPROVE', label: '批准' }]
const reason = ref('')
const error = ref('')
const busy = ref(false)
const lastAttempt = ref(null)
const headers = { 'X-Requested-With': 'XMLHttpRequest' }
async function load() {
  try { review.value = await request('/reports/' + props.reportId + '/review') }
  catch (e) { error.value = e.message }
}
async function login() {
  busy.value = true; error.value = ''
  try { const result = await request('/review/login', { method: 'POST', headers, body: JSON.stringify({ password: password.value }) }); reviewer.value = result.reviewer; password.value = '' }
  catch (e) { error.value = e.message }
  finally { busy.value = false }
}
async function logout() {
  busy.value = true; error.value = ''
  try { await request('/review/logout', { method: 'POST', headers, body: '{}' }); reviewer.value = null }
  catch (e) { error.value = e.message }
  finally { busy.value = false }
}
async function submit() {
  busy.value = true; error.value = ''
  const body = JSON.stringify({ report_id: props.reportId, decision: decision.value, reason: reason.value.trim() })
  if (lastAttempt.value?.body !== body) lastAttempt.value = { body, key: crypto.randomUUID() }
  try {
    await request('/review/decisions', { method: 'POST', headers: { ...headers, 'Idempotency-Key': lastAttempt.value.key }, body })
    reason.value = ''; lastAttempt.value = null
    await load(); emit('updated')
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
onMounted(async () => {
  await load()
  try { reviewer.value = await request('/review/me') }
  catch (e) { if (![401, 503].includes(e.status)) error.value = e.message }
})
</script>
<template>
  <section class="review-panel"><h2>发布门禁与人工审核</h2><p v-if="error" role="alert" class="notice error">{{ error }}</p>
    <template v-if="review"><p>发布：{{ review.release_status }}；审核：{{ review.review_status }}</p><ul><li v-for="f in review.findings" :key="f.finding_id">{{ f.severity }} / {{ f.code }}：{{ f.detail }}</li></ul><p v-if="!review.pending_request" class="muted">当前没有可提交的审核请求。硬门禁问题需要先修复证据或报告。</p></template>
    <form v-if="!reviewer" @submit.prevent="login"><p class="muted">使用服务端配置的审核员密码登录；未配置审核员时此功能不可用。</p><label>审核员密码<input v-model="password" type="password" autocomplete="current-password" required /></label><button :disabled="busy" type="submit">登录审核</button></form>
    <template v-else><div class="row"><p>已登录：{{ reviewer.display_name }}</p><button :disabled="busy" @click="logout">退出登录</button></div><form v-if="review?.pending_request" @submit.prevent="submit"><FolioSelect v-model="decision" label="审核决定" :options="decisionOptions" :disabled="busy" /><label>审核理由<textarea v-model="reason" required maxlength="2000" rows="3" /></label><button :disabled="busy || !reason.trim()" class="primary">提交审核决定</button></form></template>
    <details v-if="review?.history.length"><summary>审核历史</summary><article v-for="item in review.history" :key="item.review_id" class="record"><p>{{ item.decision }} · {{ item.reviewer_id }} · {{ item.created_at }}</p><p>{{ item.reason }}</p></article></details>
  </section>
</template>
