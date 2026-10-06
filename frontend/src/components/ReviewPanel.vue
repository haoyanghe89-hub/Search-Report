<script setup>
import { label } from '../composables/chinese.js'
import { onMounted, ref } from 'vue'
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
const statusClass = value => ['APPROVED', 'RELEASED', 'PASS'].includes(value) ? 'verified' : ['REJECTED', 'REJECT', 'BLOCKED', 'FAIL', 'ERROR', 'CRITICAL', 'HIGH'].includes(value) ? 'disputed' : ['PENDING', 'REQUEST_MORE_RESEARCH', 'REVIEW_REQUIRED', 'MEDIUM', 'WARNING'].includes(value) ? 'probable' : 'unverified'
async function load() { try { review.value = await request('/reports/' + props.reportId + '/review') } catch (e) { error.value = e.message } }
async function login() { busy.value = true; error.value = ''; try { const result = await request('/review/login', { method: 'POST', headers, body: JSON.stringify({ password: password.value }) }); reviewer.value = result.reviewer; password.value = '' } catch (e) { error.value = e.message } finally { busy.value = false } }
async function logout() { busy.value = true; error.value = ''; try { await request('/review/logout', { method: 'POST', headers, body: '{}' }); reviewer.value = null } catch (e) { error.value = e.message } finally { busy.value = false } }
async function submit() { busy.value = true; error.value = ''; const body = JSON.stringify({ report_id: props.reportId, decision: decision.value, reason: reason.value.trim() }); if (lastAttempt.value?.body !== body) lastAttempt.value = { body, key: crypto.randomUUID() }; try { await request('/review/decisions', { method: 'POST', headers: { ...headers, 'Idempotency-Key': lastAttempt.value.key }, body }); reason.value = ''; lastAttempt.value = null; await load(); emit('updated') } catch (e) { error.value = e.message } finally { busy.value = false } }
onMounted(async () => { await load(); try { reviewer.value = await request('/review/me') } catch (e) { if (![401, 503].includes(e.status)) error.value = e.message } })
</script>

<template>
  <section class="review-panel panel-enter">
    <header class="review-heading"><div><span class="review-kicker">Governance review</span><h2>发布门禁与人工审核</h2></div><div v-if="review" class="review-statuses"><span class="badge" :class="statusClass(review.release_status)">{{ label(review.release_status) }}</span><span class="badge" :class="statusClass(review.review_status)">{{ label(review.review_status) }}</span></div></header>
    <p v-if="error" role="alert" class="notice error">{{ error }}</p>

    <template v-if="review">
      <div v-if="review.evaluation" class="review-metrics">
        <div class="card"><strong>{{ review.findings.length }}</strong><span>检查项</span></div><div class="card"><strong>{{ review.evaluation.hard_finding_count }}</strong><span>硬门禁</span></div><div class="card"><strong>{{ review.evaluation.governance_finding_count }}</strong><span>治理提醒</span></div>
      </div>
      <div v-if="review.findings.length" class="finding-list">
        <article v-for="f in review.findings" :key="f.finding_id" class="record finding-record"><div class="finding-heading"><span class="badge" :class="statusClass(f.severity)">{{ label(f.severity) }}</span><strong>{{ label(f.code) }}</strong></div><details><summary>详细检查记录</summary><p>{{ f.detail }}</p></details></article>
      </div>
      <div v-else class="empty review-empty"><span class="empty-icon" aria-hidden="true">◇</span><h3>没有审核检查项</h3><p>当前报告未返回需要展示的门禁或治理发现。</p></div>
      <p v-if="!review.pending_request" class="notice probable">当前没有可提交的审核请求。硬门禁问题需要先修复证据或报告。</p>
    </template>

    <form v-if="!reviewer" class="card review-form" @submit.prevent="login"><p class="muted">使用服务端配置的审核员密码登录；未配置审核员时此功能不可用。</p><label class="field">审核员密码<input v-model="password" type="password" autocomplete="current-password" required /></label><button class="btn btn-primary" :disabled="busy" type="submit">登录审核</button></form>
    <template v-else><div class="reviewer-bar card"><p>已登录：<strong>{{ reviewer.display_name }}</strong></p><button class="btn btn-ghost" :disabled="busy" @click="logout">退出登录</button></div><form v-if="review?.pending_request" class="card review-form" @submit.prevent="submit"><FolioSelect v-model="decision" label="审核决定" :options="decisionOptions" :disabled="busy" /><label class="field">审核理由<textarea v-model="reason" required maxlength="2000" rows="3" /></label><button :disabled="busy || !reason.trim()" class="btn btn-primary">提交审核决定</button></form></template>
    <details v-if="review?.history.length" class="review-history"><summary>审核历史</summary><div><article v-for="item in review.history" :key="item.review_id" class="record"><div class="finding-heading"><span class="badge" :class="statusClass(item.decision)">{{ label(item.decision) }}</span><span class="history-meta">{{ item.reviewer_id }} · {{ item.created_at }}</span></div><p>{{ item.reason }}</p></article></div></details>
  </section>
</template>

<style scoped>
.review-panel { padding-block: var(--space-8); }
.review-heading, .review-statuses, .finding-heading, .reviewer-bar { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
.review-heading, .reviewer-bar { justify-content: space-between; }
.review-kicker { color: var(--accent); font-family: var(--font-mono); font-size: var(--font-size-overline); font-weight: var(--font-weight-overline); letter-spacing: var(--letter-spacing-overline); }
h2 { margin: var(--space-1) 0 0; font-family: var(--font-display); font-size: var(--font-size-h2); font-weight: var(--font-weight-h2); }
.review-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(var(--space-32), 1fr)); gap: var(--space-3); margin-block: var(--space-6); }
.review-metrics .card { display: grid; gap: var(--space-1); padding: var(--space-4); }
.review-metrics strong { color: var(--text-primary); font-family: var(--font-mono); font-size: var(--font-size-h2); font-variant-numeric: tabular-nums; }
.review-metrics span { color: var(--text-muted); font-size: var(--font-size-caption); }
.finding-list { display: grid; gap: var(--space-3); }
.finding-record + .finding-record, .review-history .record + .record { margin-top: 0; }
.finding-record strong { color: var(--text-primary); font-size: var(--font-size-small); }
.review-empty .empty-icon { display: grid; width: var(--space-10); height: var(--space-10); margin: 0; border: var(--stroke-thin) solid var(--border-strong); border-radius: var(--radius-sm); color: transparent; font-size: 0; place-items: center; }
.review-empty .empty-icon::before { width: var(--space-5); height: var(--space-3); border-block: var(--stroke-thin) solid var(--text-muted); content: ''; }
.review-form, .reviewer-bar { margin-top: var(--space-6); }
.review-form { max-width: calc(var(--content-max-width) - var(--space-32) - var(--space-32) - var(--space-16)); }
.reviewer-bar p { margin: 0; }
.review-history { margin-top: var(--space-8); }
.review-history > div { display: grid; gap: var(--space-3); margin-top: var(--space-4); }
.history-meta { color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-size-caption); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
</style>
