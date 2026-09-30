<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useOperations } from '../composables/useOperations.js'
const emit = defineEmits(['open-investigation'])
const { status, error, refresh, stop } = useOperations()
onMounted(refresh)
onUnmounted(stop)
</script>
<template>
  <aside v-if="error || status?.alerts?.length || status?.healthy === false" class="ops-notice" aria-label="运行守护告警">
    <div class="ops-heading"><strong>运行需要留意</strong><button type="button" @click="refresh">刷新状态</button></div>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="!status.healthy" role="alert">运行守护检查异常，请检查服务进程和日志。</p>
    <ul v-if="status?.alerts?.length">
      <li v-for="alert in status.alerts" :key="alert.alert_id">
        <p>{{ alert.message }}</p>
        <small>{{ alert.run_id }} · {{ new Date(alert.created_at).toLocaleString('zh-CN') }}</small>
        <button type="button" @click="emit('open-investigation', alert.investigation_id)">查看调查</button>
      </li>
    </ul>
  </aside>
</template>
<style scoped>
.ops-notice { margin: 24px 32px; padding: 18px 24px; background: var(--paper-warm); border-left: 3px solid var(--accent); color: var(--ink-deep); }
.ops-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
ul { list-style: none; padding: 0; margin-top: 12px; max-height: 300px; overflow-y: auto; }
li { padding: 12px 0; border-top: 1px solid var(--paper-edge); }
p { line-height: 1.7; }
small { color: var(--ink-muted); overflow-wrap: anywhere; }
button { border-bottom: 1px solid var(--accent-line); padding: 4px 8px; cursor: pointer; color: var(--accent); }
@media (max-width: 640px) { .ops-notice { margin: 16px; padding: 12px; } }
</style>
