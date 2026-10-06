<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useOperations } from '../composables/useOperations.js'

const emit = defineEmits(['open-investigation'])
const { status, error, refresh, stop } = useOperations()
onMounted(refresh)
onUnmounted(stop)
</script>

<template>
  <aside v-if="error || status?.alerts?.length || status?.healthy === false" class="ops-notice notice panel-enter" :class="error || status?.healthy === false ? 'danger' : 'probable'" aria-label="运行守护告警">
    <header class="ops-heading"><div><span class="ops-kicker">运行守护</span><strong>运行需要留意</strong></div><button type="button" class="quiet-button" @click="refresh">刷新状态</button></header>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="!status.healthy" role="alert">运行守护检查异常，请检查服务进程和日志。</p>
    <ul v-if="status?.alerts?.length" class="ops-alerts">
      <li v-for="alert in status.alerts" :key="alert.alert_id" class="record ops-alert">
        <div><p>{{ alert.message }}</p><small>{{ alert.run_id }} · {{ new Date(alert.created_at).toLocaleString('zh-CN') }}</small></div>
        <button type="button" class="btn btn-ghost" @click="emit('open-investigation', alert.investigation_id)">查看调查</button>
      </li>
    </ul>
  </aside>
</template>

<style scoped>
.ops-notice { margin: var(--space-6) var(--space-8); }
.ops-heading, .ops-alert { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); }
.ops-heading strong { display: block; margin-top: var(--space-1); color: inherit; font-family: var(--font-display); font-size: var(--font-size-h4); }
.ops-kicker { font-family: var(--font-mono); font-size: var(--font-size-overline); font-weight: var(--font-weight-overline); letter-spacing: var(--letter-spacing-overline); }
.ops-alerts { display: grid; max-height: calc(var(--space-32) + var(--space-32)); gap: var(--space-2); margin: var(--space-4) 0 0; padding: 0; overflow-y: auto; list-style: none; }
.ops-alert { padding: var(--space-3) var(--space-4); background: var(--bg-surface); }
.ops-alert + .ops-alert { margin-top: 0; }
.ops-alert p { margin: 0 0 var(--space-1); color: var(--text-secondary); line-height: var(--line-height-body); }
.ops-alert small { color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-size-caption); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.ops-alert .btn { min-height: var(--space-8); flex-shrink: 0; padding-inline: var(--space-3); font-size: var(--font-size-caption); }
</style>
