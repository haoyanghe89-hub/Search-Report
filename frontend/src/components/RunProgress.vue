<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
defineProps({ replaying: Boolean, starting: Boolean, running: Boolean, phase: String, workers: { type: Object, default: () => ({}) }, budget: Object, steps: { type: Array, default: () => [] } })
const elapsed = ref(0)
let timer
onMounted(() => { const began = Date.now(); timer = setInterval(() => { elapsed.value = Math.floor((Date.now() - began) / 1000) }, 1000) })
onUnmounted(() => clearInterval(timer))
</script>
<template>
  <section class="run-progress" aria-busy="true" aria-label="调查加载过程">
    <div class="progress-heading"><span class="progress-orbit" aria-hidden="true"></span><span class="eyebrow">{{ replaying ? 'ARCHIVE REPLAY' : running || starting ? 'INVESTIGATION IN PROGRESS' : 'LOADING ARCHIVE' }}</span><span class="elapsed">已等待 {{ elapsed }} 秒</span></div>
    <h2 role="status">{{ replaying ? '正在回放调查档案' : starting ? '正在启动调查' : running ? '调查正在进行' : '正在读取调查记录' }}</h2>
    <p>{{ replaying ? '正在读取归档来源并重建证据与引用，完成后展示本次结果。' : starting ? '正在提交调查任务，等待服务端确认。' : running ? '正在收集与验证材料，调查结束后展示证据链与报告。' : '正在加载所选运行的来源、证据和报告。' }}</p>
    <ul v-if="running && !replaying && Object.keys(workers).length" class="worker-grid"><li v-for="(status, name) in workers" :key="name"><span>{{ {official:'官方资料研究员',independent:'独立报道研究员',technical:'技术研究员',counterevidence:'反证研究员'}[name] || name }}</span><strong>{{ {RUNNING:'研究中',COMPLETED:'查询已提出',FAILED:'本轮调用失败',BUDGET_EXHAUSTED:'预算已用尽'}[status] || status }}</strong></li></ul>
    <p v-if="running && !replaying && budget" class="progress-budget">搜索 {{ budget.search_calls_used }} / {{ budget.max_search_calls }} · 抓取 {{ budget.fetch_calls_used }} / {{ budget.max_fetch_calls }} · 模型调用 {{ budget.model_calls_used }} / {{ budget.max_model_calls }}</p>
    <div class="progress-rule" aria-hidden="true"><span></span></div>
    <template v-if="running && !replaying && !starting">
      <p class="progress-phase">当前阶段：{{ phase || '等待执行' }}</p>
      <ol v-if="steps.length" class="progress-steps"><li v-for="step in steps" :key="step.step_id"><span>{{ step.agent_role }} · {{ step.logical_step_key }}</span><span>{{ step.status }}</span></li></ol>
    </template>
    <small>结果将在本次运行结束后自动更新。</small>
  </section>
</template>
<style scoped>
.worker-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 24px 0; padding: 0 !important; list-style: none; }
.worker-grid li { border: 1px solid var(--paper-edge); background: var(--paper-warm); padding: 16px; font-size: 13px; }
.worker-grid strong { display: block; margin-top: 8px; font: 11px var(--font-mono); color: var(--accent); }
.progress-budget { margin-top: 20px; font: 11px var(--font-mono); }
.run-progress { margin: 36px 0; border-top: 1px solid var(--accent-line); border-bottom: 1px solid var(--paper-edge); padding: 36px 0 42px; }
.progress-heading { display: flex; align-items: center; gap: 12px; }
.progress-orbit { width: 18px; height: 18px; border: 1px solid var(--accent-line); border-top-color: var(--accent); border-radius: 50%; animation: orbit 1.3s linear infinite; }
.elapsed { margin-left: auto; font: 11px var(--font-mono); color: var(--ink-muted); }
h2 { font: 500 30px var(--font-display); margin: 24px 0 14px; }
p { color: var(--ink-muted); font-size: 15px; }
.progress-rule { height: 2px; background: var(--paper-edge); overflow: hidden; margin: 32px 0 24px; }
.progress-rule span { display: block; width: 28%; height: 100%; background: var(--accent-light); animation: sweep 2s ease-in-out infinite; }
small { color: var(--ink-faint); font-size: 12px; font-style: italic; }
.progress-steps { padding: 0; list-style: none; margin: 18px 0; max-height: 240px; overflow: auto; }
.progress-steps li { display: flex; justify-content: space-between; gap: 20px; padding: 10px 0; border-bottom: 1px solid var(--paper-edge); font: 11px/1.7 var(--font-mono); overflow-wrap: anywhere; }
@keyframes orbit { to { transform: rotate(360deg); } }
@keyframes sweep { from { transform: translateX(-110%); } to { transform: translateX(460%); } }
</style>
