<script setup>
import { ref, computed, onMounted } from 'vue'
import RunProgress from './components/RunProgress.vue'
import Sidebar from './components/Sidebar.vue'
import request from './api/request.js'
import InvestigationView from './views/InvestigationView.vue'
import TopicSearch from './components/TopicSearch.vue'
import { createTopicLauncher } from './api/topicInvestigation.js'
const investigations = ref([])
const activeId = ref('')
const loading = ref(false)
const replaying = ref(false)
const error = ref('')
const startingTopic = ref(false)
const topicError = ref('')
const topicSearch = ref(null)
const launchTopic = createTopicLauncher(request)
const revision = ref(0)
async function load() {
  loading.value = true
  error.value = ''
  try {
    investigations.value = await request('/investigations')
  } catch (e) { error.value = e.message }
  finally { loading.value = false }
}
function newTopic() {
  if (startingTopic.value || replaying.value) return
  activeId.value = ''
  topicError.value = ''
  topicSearch.value?.clear()
  topicSearch.value?.focus()
}
function selectArchive(id) { if (!startingTopic.value && !replaying.value) activeId.value = id }
async function startTopic(topic) {
  if (startingTopic.value || replaying.value) return
  startingTopic.value = true
  topicError.value = ''
  try {
    const result = await launchTopic(topic)
    activeId.value = result.investigation_id
    revision.value++
    topicSearch.value?.clear()
  } catch (e) { topicError.value = e.message }
  finally { await load(); startingTopic.value = false }
}
async function replay() {
  if (replaying.value || startingTopic.value) return
  replaying.value = true
  error.value = ''
  try {
    const result = await request('/cases/east-palestine-2023/replay', { method: 'POST', timeoutMs: 300000 })
    activeId.value = result.investigation_id
    revision.value++
    await load()
  } catch (e) { error.value = e.message }
  finally { replaying.value = false }
}
onMounted(load)

const cases = computed(() => investigations.value.map(i => ({ id: i.investigation_id, name: i.title, status: i.run_count ? 'investigating' : 'draft', statusText: i.run_count ? '有运行记录' : '新建', tag: `${i.run_count}次运行` })))
</script>
<template>
  <div class="app-wrapper">
    <Sidebar :cases="cases" :active-case-id="activeId" :loading="loading" :replaying="replaying" :busy="startingTopic" @select="selectArchive" @new-investigation="newTopic" @refresh="load" @replay="replay" />
    <main class="main-content">
      <div v-if="error" class="notice error" role="alert">{{ error }} <button @click="load">重试连接</button></div>
      <section :class="activeId ? 'topic-strip' : 'welcome'">
        <template v-if="!activeId"><p class="eyebrow">FOLIO · 事件调查与证据验证</p><h1>从一个问题出发，<br>追溯事实与证据。</h1><p>输入你关心的主题，调查从这里开始。</p></template>
        <TopicSearch ref="topicSearch" :compact="Boolean(activeId)" :busy="startingTopic" :disabled="replaying" :error="topicError" @start="startTopic" />
      </section>
      <div v-if="startingTopic" class="topic-strip"><RunProgress starting /></div>
      <InvestigationView v-else-if="activeId" :key="activeId + ':' + revision" :investigation-id="activeId" :replaying="replaying" @updated="load" @replay="replay" @new-investigation="newTopic" />
      <div v-else-if="replaying" class="topic-strip"><RunProgress replaying /></div>
    </main>
  </div>
</template>
<style scoped>
.topic-strip { padding: 28px 64px; border-bottom: 1px solid var(--paper-edge); }
@media (max-width: 1100px) { .topic-strip { padding: 24px 32px; } }
@media (max-width: 640px) { .topic-strip { padding: 20px; } }
</style>
