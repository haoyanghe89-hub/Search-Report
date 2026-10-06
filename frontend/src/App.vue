<script setup>
import { ref, computed, onMounted } from 'vue'
import RunProgress from './components/RunProgress.vue'
import Sidebar from './components/Sidebar.vue'
import request from './api/request.js'
import InvestigationView from './views/InvestigationView.vue'
import TopicSearch from './components/TopicSearch.vue'
import NewInvestigationModal from './components/NewInvestigationModal.vue'
import DeleteInvestigationModal from './components/DeleteInvestigationModal.vue'
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
const newModal = ref(false)
const deleteTarget = ref(null)
const notice = ref('')
async function createdArchive(archive) {
  newModal.value = false
  activeId.value = archive.investigation_id
  await load()
}
async function deletedArchive(id) {
  deleteTarget.value = null
  if (activeId.value === id) activeId.value = ''
  investigations.value = investigations.value.filter(item => item.investigation_id !== id)
  notice.value = '卷宗及关联记录已删除。'
  await load()
}
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
    <Sidebar :cases="cases" :active-case-id="activeId" :loading="loading" :replaying="replaying" :busy="startingTopic" @select="selectArchive" @new-investigation="newTopic" @create-investigation="newModal = true" @delete-investigation="deleteTarget = $event" @refresh="load" @replay="replay" />
    <main class="main-content">
      <p v-if="notice" class="notice info" role="status">{{ notice }} <button class="quiet-button" @click="notice = ''">关闭提示</button></p>
      <div v-if="error" class="notice error" role="alert">{{ error }} <button @click="load">重试连接</button></div>
      <section v-if="!activeId" class="welcome">
        <div class="welcome-texture" aria-hidden="true"></div>
        <div class="welcome-copy">
          <p class="welcome-kicker">DOSSIER 00 / DIGITAL FOLIO</p>
          <h1>从一个问题出发，<br>追溯事实与证据。</h1>
          <p class="welcome-subtitle">事件调查与证据验证。从一个主题开始，建立可追溯的数字卷宗。</p>
        </div>
        <div class="welcome-search">
          <TopicSearch ref="topicSearch" :busy="startingTopic" :disabled="replaying" :error="topicError" @start="startTopic" />
        </div>
      </section>
      <div v-if="startingTopic" class="topic-strip"><RunProgress starting /></div>
      <InvestigationView v-else-if="activeId" :key="activeId + ':' + revision" :investigation-id="activeId" :replaying="replaying" @updated="load" @replay="replay" @new-investigation="newTopic" />
      <div v-else-if="replaying" class="topic-strip"><RunProgress replaying /></div>
      <div v-if="activeId" class="detail-support">
        <section class="topic-strip">
          <TopicSearch ref="topicSearch" compact :busy="startingTopic" :disabled="replaying" :error="topicError" @start="startTopic" />
        </section>
      </div>
    </main>
    <NewInvestigationModal v-if="newModal" @close="newModal = false" @created="createdArchive" />
    <DeleteInvestigationModal v-if="deleteTarget" :investigation="deleteTarget" @close="deleteTarget = null" @deleted="deletedArchive" />
  </div>
</template>
<style scoped>
.topic-strip {
  padding: var(--space-6) var(--space-16);
  border-bottom: 1px solid var(--border-default);
}

.detail-support {
  border-top: 1px solid var(--border-default);
}

.welcome {
  position: relative;
  isolation: isolate;
  display: grid;
  width: 100%;
  max-width: none;
  min-height: calc(100vh - var(--topbar-height));
  margin: 0;
  padding: var(--space-20) var(--space-16) var(--space-32);
  overflow: hidden;
  align-content: center;
  justify-items: center;
}

.welcome-texture {
  position: absolute;
  inset: 0;
  z-index: -1;
  background-image:
    linear-gradient(to right, currentColor 1px, transparent 1px),
    linear-gradient(to bottom, currentColor 1px, transparent 1px);
  background-size: var(--space-8) var(--space-8);
  color: var(--text-primary);
  opacity: 0.02;
  pointer-events: none;
}

.welcome-copy {
  display: flex;
  max-width: 72ch;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.welcome-kicker {
  margin: 0 0 var(--space-5);
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: var(--font-size-overline);
  font-weight: var(--font-weight-overline);
  letter-spacing: var(--letter-spacing-overline);
  line-height: var(--line-height-overline);
}

.welcome h1 {
  max-width: 18ch;
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: var(--font-size-display-xl);
  font-weight: var(--font-weight-display-xl);
  letter-spacing: var(--letter-spacing-display-xl);
  line-height: var(--line-height-display-xl);
  text-wrap: balance;
}

.welcome-subtitle {
  max-width: 52ch;
  margin: var(--space-5) 0 var(--space-8);
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: var(--font-size-body-lg);
  font-weight: var(--font-weight-body-lg);
  letter-spacing: var(--letter-spacing-body-lg);
  line-height: var(--line-height-body-lg);
}

.welcome-search {
  z-index: 1;
  width: min(100%, 780px);
}

.welcome-search :deep(.topic-search > label) {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

.welcome-search :deep(.topic-search button) {
  margin: 0;
}

@media (max-width: 1100px) {
  .topic-strip {
    padding: var(--space-6) var(--space-8);
  }

  .welcome {
    padding-inline: var(--space-8);
  }
}

@media (max-width: 640px) {
  .topic-strip {
    padding: var(--space-5);
  }

  .welcome {
    min-height: auto;
    padding: var(--space-16) var(--space-5) var(--space-24);
  }

  .welcome h1 {
    font-size: var(--font-size-h1);
    line-height: var(--line-height-h1);
  }

  .welcome-subtitle {
    margin-bottom: var(--space-6);
  }
}
</style>
