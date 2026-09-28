<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { fetchRunDetail, fetchRunSteps, fetchRunSources, fetchRunEvidence, fetchRunClaims } from '@/api/index.js'

const props = defineProps({
  runId: {
    type: String,
    default: ''
  },
  initialRunStatus: {
    type: String,
    default: 'RUNNING'
  },
  // 是否正在启动中（还没有 runId）
  starting: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['completed'])

// 状态
const runDetail = ref(null)
const steps = ref([])
const sources = ref([])
const evidence = ref([])
const claims = ref([])
const loading = ref(true)
const error = ref(null)
const isRunning = ref(true)
const activeLogId = ref(null)

// 轮询定时器
let pollTimer = null
const POLL_INTERVAL = 2000 // 2秒轮询

// 阶段定义 - 用于进度条
const phases = [
  { key: 'PLAN', label: '规划', desc: '分析问题，制定研究计划', icon: '◈' },
  { key: 'COLLECT', label: '搜集', desc: '搜索网络，采集来源', icon: '⬡' },
  { key: 'ANALYZE', label: '分析', desc: '提取证据，形成声明', icon: '◇' },
  { key: 'VERIFY', label: '验证', desc: '交叉验证，识别冲突', icon: '◆' },
  { key: 'REPORT', label: '报告', desc: '生成报告，整理结论', icon: '▣' }
]

// 当前阶段索引
const currentPhaseIndex = computed(() => {
  if (!runDetail.value?.run?.current_phase) return 0
  const phase = runDetail.value.run.current_phase
  const idx = phases.findIndex(p => p.key === phase)
  return idx >= 0 ? idx : 0
})

// 步骤类型对应的展示文本
const stepTypeLabels = {
  PLANNING: { label: '规划研究', color: '#7c3aed', icon: '🧠' },
  RESEARCH: { label: '研究采集', color: '#0891b2', icon: '🔍' },
  SEARCH: { label: '执行搜索', color: '#0284c7', icon: '🌐' },
  FETCH: { label: '抓取页面', color: '#0d9488', icon: '📄' },
  EXTRACTION: { label: '证据提取', color: '#65a30d', icon: '✂️' },
  ANALYSIS: { label: '声明分析', color: '#d97706', icon: '📊' },
  VALIDATION: { label: '证据验证', color: '#dc2626', icon: '⚖️' },
  REPORTING: { label: '撰写报告', color: '#7c3aed', icon: '✍️' },
  REVIEW: { label: '审核', color: '#6b7280', icon: '👁' },
  OTHER: { label: '系统处理', color: '#6b7280', icon: '⚙️' }
}

// Agent 角色文本
const agentLabels = {
  SUPERVISOR: { label: '规划智能体', color: '#7c3aed' },
  RESEARCHER: { label: '研究智能体', color: '#0891b2' },
  ANALYST: { label: '分析智能体', color: '#d97706' },
  VERIFIER: { label: '验证智能体', color: '#dc2626' },
  WRITER: { label: '写作智能体', color: '#7c3aed' },
  HARNESS: { label: '系统调度', color: '#6b7280' }
}

// 步骤状态文本
const statusLabels = {
  PENDING: '等待中',
  RUNNING: '进行中',
  COMPLETED: '已完成',
  FAILED: '失败',
  SKIPPED: '跳过',
  BLOCKED: '阻塞'
}

// 模拟的思考日志（根据步骤类型生成）
const stepThinkingMap = {
  PLANNING: [
    '正在分析调查目标和问题范围…',
    '拆解核心问题为可研究的子任务…',
    '评估每个问题的信息可得性…',
    '制定搜索策略和关键词组合…',
    '规划研究轮次和验证路径…'
  ],
  RESEARCH: [
    '构造搜索查询词…',
    '提交搜索请求，等待结果…',
    '筛选相关来源，评估可信度…',
    '抓取来源页面内容…',
    '解析页面结构，提取正文…',
    '识别有证据价值的段落…'
  ],
  SEARCH: [
    '正在 DuckDuckGo 搜索相关结果…',
    '解析搜索结果页面…',
    '过滤低质量结果，保留权威来源…',
    '对结果进行相关性评分…'
  ],
  FETCH: [
    '请求页面内容…',
    '解析 HTML 结构…',
    '提取正文文本…',
    '清理广告和导航元素…',
    '保存页面快照…'
  ],
  EXTRACTION: [
    '分析页面内容结构…',
    '识别事实性陈述…',
    '提取证据片段及上下文…',
    '生成文本定位器（Text Quote）…',
    '关联来源和证据…'
  ],
  ANALYSIS: [
    '整理已采集的证据…',
    '归纳事实声明…',
    '对声明进行分类（事件/定量/因果/影响…）',
    '检测声明间的潜在冲突…',
    '构建证据-声明关系图…'
  ],
  VALIDATION: [
    '逐条验证声明的证据支撑…',
    '检查证据与声明的语义蕴含关系…',
    '评估来源独立性和权威性…',
    '交叉比对不同来源的一致性…',
    '识别证据缺口和研究局限…',
    '计算验证置信度…'
  ],
  REPORTING: [
    '整理已验证的声明…',
    '按章节组织报告结构…',
    '生成执行摘要…',
    '构建引用网络…',
    '检查引用完整性…',
    '执行发布门禁检查…'
  ]
}

// 生成的思考日志列表
const thinkingLogs = ref([])
const logIdCounter = ref(0)

// 添加思考日志
function addThinkingLog(text, type = 'thinking', meta = {}) {
  const id = `log-${++logIdCounter.value}`
  thinkingLogs.value.push({
    id,
    text,
    type, // thinking, search, source, evidence, claim
    meta,
    timestamp: new Date()
  })
  nextTick(() => {
    const logContainer = document.querySelector('.thinking-logs')
    if (logContainer) {
      logContainer.scrollTop = logContainer.scrollHeight
    }
  })
  activeLogId.value = id
  // 2秒后取消高亮
  setTimeout(() => {
    if (activeLogId.value === id) {
      activeLogId.value = null
    }
  }, 1500)
}

// 已处理的步骤ID集合
const processedStepIds = new Set()
const stepStartTimes = {}

// 轮询获取运行状态和步骤
async function pollStatus() {
  try {
    // 获取运行详情
    const detail = await fetchRunDetail(props.runId)
    runDetail.value = detail
    loading.value = false

    // 获取步骤
    const stepList = await fetchRunSteps(props.runId)
    
    // 检查新步骤或状态变化
    for (const step of stepList) {
      const stepKey = `${step.step_id}-${step.status}`
      
      if (!processedStepIds.has(stepKey)) {
        processedStepIds.add(stepKey)
        
        const stepTypeInfo = stepTypeLabels[step.step_type] || stepTypeLabels.OTHER
        const agentInfo = agentLabels[step.agent_role] || { label: step.agent_role, color: '#6b7280' }
        
        if (step.status === 'RUNNING') {
          stepStartTimes[step.step_id] = Date.now()
          
          // 开始一个步骤
          const thoughts = stepThinkingMap[step.step_type] || ['处理中…']
          addThinkingLog(
            `${stepTypeInfo.icon} ${agentInfo.label} 开始：${stepTypeInfo.label}`,
            'step-start',
            { stepType: step.step_type, agent: step.agent_role }
          )
          
          // 逐条输出思考过程（模拟流式）
          let i = 0
          const outputNext = () => {
            if (i < thoughts.length) {
              // 只在步骤还在运行时继续输出
              const currentStep = steps.value.find(s => s.step_id === step.step_id)
              if (currentStep && currentStep.status === 'RUNNING') {
                addThinkingLog(thoughts[i], 'thinking', { stepType: step.step_type })
                i++
                setTimeout(outputNext, 600 + Math.random() * 800)
              }
            }
          }
          setTimeout(outputNext, 300)
        } else if (step.status === 'COMPLETED') {
          // 步骤完成
          const elapsed = stepStartTimes[step.step_id] 
            ? ((Date.now() - stepStartTimes[step.step_id]) / 1000).toFixed(1) + 's'
            : ''
          addThinkingLog(
            `✓ ${stepTypeInfo.label}完成 ${elapsed}`,
            'step-complete',
            { stepType: step.step_type }
          )
        } else if (step.status === 'FAILED') {
          addThinkingLog(
            `✗ ${stepTypeInfo.label}失败：${step.error_code || '未知错误'}`,
            'step-error',
            { stepType: step.step_type, error: step.error_code }
          )
        }
      }
    }
    
    steps.value = stepList

    // 检查运行是否完成
    const status = detail.run?.status
    if (['COMPLETED', 'FAILED', 'BLOCKED', 'CANCELLED', 'INTERRUPTED'].includes(status)) {
      isRunning.value = false
      stopPolling()
      
      // 运行完成，加载最终数据
      await loadFinalData()
      
      addThinkingLog(
        status === 'COMPLETED' 
          ? '🎉 调查运行完成！报告已生成' 
          : `运行结束，状态：${status}`,
        status === 'COMPLETED' ? 'complete' : 'error'
      )
      
      emit('completed', { status, runId: props.runId })
      return
    }
    
    // 继续轮询
    schedulePoll()
  } catch (e) {
    error.value = e.message || '获取运行状态失败'
    loading.value = false
    // 出错后继续轮询
    schedulePoll()
  }
}

// 加载最终数据
async function loadFinalData() {
  try {
    const [src, ev, cl] = await Promise.all([
      fetchRunSources(props.runId).catch(() => []),
      fetchRunEvidence(props.runId).catch(() => []),
      fetchRunClaims(props.runId).catch(() => [])
    ])
    sources.value = src
    evidence.value = ev
    claims.value = cl
    
    if (src.length > 0) {
      addThinkingLog(`📚 采集到 ${src.length} 个有效来源`, 'source-summary')
    }
    if (ev.length > 0) {
      addThinkingLog(`📝 提取到 ${ev.length} 条证据片段`, 'evidence-summary')
    }
    if (cl.length > 0) {
      const verified = cl.filter(c => c.verification_status === 'VERIFIED').length
      addThinkingLog(`✅ 验证通过 ${verified}/${cl.length} 条声明`, 'claim-summary')
    }
  } catch (e) {
    console.error('加载最终数据失败:', e)
  }
}

function schedulePoll() {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = setTimeout(pollStatus, POLL_INTERVAL)
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

// 是否为回放模拟模式
const isReplaySim = computed(() => props.runId === 'replay-pending')

// 进度百分比
const progressPercent = computed(() => {
  if (!isRunning.value) return 100
  const idx = currentPhaseIndex.value
  const total = phases.length - 1
  return Math.round((idx / total) * 100)
})

// 格式化时间
function formatDuration(ms) {
  if (!ms) return '0s'
  const sec = Math.floor(ms / 1000)
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  const s = sec % 60
  return `${min}m ${s}s`
}

// 回放模拟：预设的思考步骤序列
const replaySimSteps = [
  { phase: 0, stepType: 'PLAN', log: '正在启动调查引擎，加载案例配置…', delay: 800 },
  { phase: 0, stepType: 'PLAN', log: '解析调查事件：东巴勒斯坦火车脱轨事故', delay: 800 },
  { phase: 0, stepType: 'PLAN', log: '生成研究问题清单，拆解调查方向', delay: 1000 },
  { phase: 0, stepType: 'PLAN', log: '规划搜索策略：5个维度，20+检索关键词', delay: 800 },
  { phase: 1, stepType: 'SEARCH', log: '🔍 在 DuckDuckGo 搜索 "East Palestine train derailment 2023"', delay: 1200 },
  { phase: 1, stepType: 'SEARCH', log: '🔍 在 Bing 搜索 "Ohio train derailment NTSB report"', delay: 1000 },
  { phase: 1, stepType: 'SEARCH', log: '📄 抓取 NTSB 官方报告页面 ntsb.gov', delay: 1500 },
  { phase: 1, stepType: 'SEARCH', log: '🔍 搜索 "East Palestine chemical release vinyl chloride"', delay: 1000 },
  { phase: 1, stepType: 'SEARCH', log: '📄 抓取 EPA 环境评估页面 epa.gov', delay: 1500 },
  { phase: 1, stepType: 'SEARCH', log: '🔍 搜索 "Norfolk Southern 32N train manifest"', delay: 1000 },
  { phase: 1, stepType: 'SEARCH', log: '📄 抓取俄亥俄州州长办公室公告 ohio.gov', delay: 1200 },
  { phase: 1, stepType: 'SEARCH', log: '🔍 搜索 "East Palestine water contamination testing results"', delay: 1000 },
  { phase: 1, stepType: 'SEARCH', log: '📄 抓取 CDC 健康建议页面 cdc.gov', delay: 1500 },
  { phase: 1, stepType: 'SEARCH', log: '🔍 搜索 "train derailment wheel bearing failure cause"', delay: 1000 },
  { phase: 1, stepType: 'SEARCH', log: '📄 抓取 Wikipedia 东巴勒斯坦词条', delay: 1200 },
  { phase: 1, stepType: 'SEARCH', log: '🔍 搜索 "Norfolk Southern compensation settlement"', delay: 1000 },
  { phase: 2, stepType: 'EXTRACT', log: '📊 开始提取证据，分析 32 个来源页面', delay: 1500 },
  { phase: 2, stepType: 'EXTRACT', log: '从 NTSB 报告中提取 8 条事实证据', delay: 1200 },
  { phase: 2, stepType: 'EXTRACT', log: '从 EPA 数据中提取环境监测指标', delay: 1000 },
  { phase: 2, stepType: 'EXTRACT', log: '交叉验证脱轨时间线，识别 2 个数值冲突', delay: 1500 },
  { phase: 2, stepType: 'EXTRACT', log: '证据提取完成：42 条证据 · 置信度均值 0.87', delay: 1000 },
  { phase: 3, stepType: 'ANALYZE', log: '🧠 启动分析师，构建声明网络', delay: 1200 },
  { phase: 3, stepType: 'ANALYZE', log: '生成 12 条核心声明，按置信度分级', delay: 1000 },
  { phase: 3, stepType: 'ANALYZE', log: '识别 3 个来源冲突，启动冲突解决流程', delay: 1500 },
  { phase: 3, stepType: 'ANALYZE', log: '发现 2 个研究缺口：长期健康影响、经济损失', delay: 1200 },
  { phase: 3, stepType: 'ANALYZE', log: '构建因果链：轴承过热 → 轴故障 → 脱轨 → 化学品泄漏', delay: 1000 },
  { phase: 4, stepType: 'VERIFY', log: '✅ 启动验证器，逐条验证声明', delay: 1200 },
  { phase: 4, stepType: 'VERIFY', log: '已验证：脱轨原因确认为车轮轴承过热（多源一致）', delay: 1000 },
  { phase: 4, stepType: 'VERIFY', log: '已验证：氯乙烯受控释放决定经多方确认', delay: 1000 },
  { phase: 4, stepType: 'VERIFY', log: '验证完成：8 条已验证 · 4 条高概率 · 0 条争议', delay: 1000 },
  { phase: 5, stepType: 'REPORT', log: '📝 生成 17 章节调查报告…', delay: 1500 },
  { phase: 5, stepType: 'REPORT', log: '添加引用溯源，关联 42 条证据', delay: 1000 },
  { phase: 5, stepType: 'REPORT', log: '报告生成完成，等待发布审核', delay: 800 }
]

let replaySimTimer = null
let replaySimIndex = 0
let replaySimStartTime = 0

// 开始回放模拟
function startReplaySim() {
  replaySimIndex = 0
  replaySimStartTime = Date.now()
  runSimNextStep()
}

function runSimNextStep() {
  if (replaySimIndex >= replaySimSteps.length) {
    // 模拟完成，等待真实 API 返回
    return
  }
  const step = replaySimSteps[replaySimIndex]
  currentPhaseIndex.value = step.phase
  // 模拟统计数据递增
  if (step.stepType === 'SEARCH') {
    sourceCount.value = Math.min(sourceCount.value + 1, 10)
  } else if (step.stepType === 'EXTRACT') {
    evidenceCount.value = Math.min(evidenceCount.value + 3, 42)
    claimCount.value = Math.min(claimCount.value + 1, 12)
  } else if (step.stepType === 'ANALYZE') {
    claimCount.value = Math.min(claimCount.value + 2, 12)
  }
  // 添加思考日志
  addThinkingLog(step.stepType, step.log, Date.now() - replaySimStartTime)
  // 统计步数
  completedSteps.value = replaySimIndex + 1
  replaySimIndex++
  replaySimTimer = setTimeout(runSimNextStep, step.delay)
}

function stopReplaySim() {
  if (replaySimTimer) {
    clearTimeout(replaySimTimer)
    replaySimTimer = null
  }
}

onMounted(() => {
  if (isReplaySim.value) {
    // 回放模拟模式
    startReplaySim()
  } else if (props.runId) {
    // 正常轮询模式
    pollStatus()
  }
})

onBeforeUnmount(() => {
  stopPolling()
  stopReplaySim()
})

watch(() => props.runId, (newId, oldId) => {
  // 从回放模拟切换到真实 runId：停止模拟，开始轮询
  if (oldId === 'replay-pending' && newId && newId !== 'replay-pending') {
    stopReplaySim()
    // 保留模拟日志，继续轮询真实数据
    loading.value = true
    pollStatus()
    return
  }
  // runId 从无到有，说明启动完成，开始轮询
  if (newId && !oldId) {
    loading.value = true
    pollStatus()
    return
  }
  processedStepIds.clear()
  thinkingLogs.value = []
  logIdCounter.value = 0
  steps.value = []
  sources.value = []
  evidence.value = []
  claims.value = []
  isRunning.value = true
  loading.value = true
  error.value = null
  pollStatus()
})
</script>

<template>
  <div class="run-progress">
    <!-- 头部状态 -->
    <div class="progress-header">
      <div class="ph-status">
        <span class="status-indicator" :class="isRunning ? 'pulse' : 'done'"></span>
        <span class="status-text">
          <template v-if="starting">正在启动调查…</template>
          <template v-else>{{ isRunning ? '调查运行中' : '运行完成' }}</template>
        </span>
        <span v-if="runId" class="run-id-badge">{{ runId }}</span>
        <span v-else class="run-id-badge pending">初始化</span>
      </div>
      <div class="ph-meta" v-if="runDetail?.budget">
        <span class="meta-chip">
          🔍 {{ runDetail.budget.search_calls_used }}/{{ runDetail.budget.max_search_calls }} 搜索
        </span>
        <span class="meta-chip">
          📄 {{ runDetail.budget.fetch_calls_used }}/{{ runDetail.budget.max_fetch_calls }} 抓取
        </span>
        <span class="meta-chip">
          🧠 {{ runDetail.budget.model_calls_used }}/{{ runDetail.budget.max_model_calls }} 模型调用
        </span>
      </div>
    </div>

    <!-- 阶段进度条 -->
    <div class="phase-progress">
      <div
        v-for="(phase, idx) in phases"
        :key="phase.key"
        class="phase-node"
        :class="{
          active: idx === currentPhaseIndex && isRunning,
          completed: idx < currentPhaseIndex || !isRunning,
          current: idx === currentPhaseIndex
        }"
      >
        <div class="phase-icon">{{ phase.icon }}</div>
        <div class="phase-info">
          <div class="phase-label">{{ phase.label }}</div>
          <div class="phase-desc">{{ phase.desc }}</div>
        </div>
        <div v-if="idx < phases.length - 1" class="phase-connector"></div>
      </div>
    </div>

    <!-- 主内容区：思考过程 + 实时数据 -->
    <div class="progress-body">
      <!-- 左侧：思考日志 -->
      <div class="thinking-panel">
        <div class="panel-title">
          <span class="title-dot"></span>
          智能体思考过程
          <span class="title-sub">（实时更新）</span>
        </div>
        <div class="thinking-logs">
          <div
            v-for="log in thinkingLogs"
            :key="log.id"
            class="log-item"
            :class="[log.type, { active: activeLogId === log.id }]"
          >
            <span class="log-text">{{ log.text }}</span>
            <span class="log-time">
              {{ log.timestamp.toLocaleTimeString('zh-CN', { hour12: false }) }}
            </span>
          </div>

          <!-- 加载中的光标 -->
          <div v-if="isRunning && thinkingLogs.length > 0" class="log-item thinking cursor-blink">
            <span class="log-text">▊</span>
          </div>

          <!-- 启动中（还没有 runId） -->
          <div v-if="starting" class="log-starting">
            <div class="starting-dots">
              <span></span><span></span><span></span>
            </div>
            <p>正在初始化调查引擎…</p>
            <p class="starting-sub">准备搜索适配器、模型连接、验证管线</p>
          </div>

          <!-- 初始加载 -->
          <div v-else-if="loading && thinkingLogs.length === 0" class="log-empty">
            <div class="spinner"></div>
            <p>正在启动调查运行…</p>
          </div>
        </div>
      </div>

      <!-- 右侧：实时数据统计 -->
      <div class="stats-panel">
        <div class="panel-title">
          <span class="title-dot"></span>
          实时数据
        </div>

        <div class="stat-cards">
          <div class="stat-card sources">
            <div class="stat-num">{{ sources.length }}</div>
            <div class="stat-label">有效来源</div>
            <div class="stat-bar"><div class="stat-fill" :style="{ width: Math.min(sources.length * 10, 100) + '%' }"></div></div>
          </div>
          <div class="stat-card evidence">
            <div class="stat-num">{{ evidence.length }}</div>
            <div class="stat-label">证据片段</div>
            <div class="stat-bar"><div class="stat-fill" :style="{ width: Math.min(evidence.length * 7, 100) + '%' }"></div></div>
          </div>
          <div class="stat-card claims">
            <div class="stat-num">{{ claims.length }}</div>
            <div class="stat-label">事实声明</div>
            <div class="stat-bar"><div class="stat-fill" :style="{ width: Math.min(claims.length * 12, 100) + '%' }"></div></div>
          </div>
          <div class="stat-card steps">
            <div class="stat-num">{{ steps.filter(s => s.status === 'COMPLETED').length }}</div>
            <div class="stat-label">完成步骤</div>
            <div class="stat-bar"><div class="stat-fill" :style="{ width: Math.min(steps.length * 8, 100) + '%' }"></div></div>
          </div>
        </div>

        <!-- 当前运行阶段详情 -->
        <div v-if="runDetail?.run" class="phase-detail">
          <h4>运行信息</h4>
          <div class="detail-row">
            <span class="detail-label">当前阶段</span>
            <span class="detail-value">{{ runDetail.run.current_phase }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">运行模式</span>
            <span class="detail-value">{{ runDetail.run.mode }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">状态版本</span>
            <span class="detail-value">v{{ runDetail.run.state_version }}</span>
          </div>
          <div class="detail-row" v-if="runDetail.budget">
            <span class="detail-label">已用时间</span>
            <span class="detail-value">{{ formatDuration(runDetail.budget.consumed_wall_time_ms) }}</span>
          </div>
          <div class="detail-row" v-if="runDetail.budget">
            <span class="detail-label">研究轮次</span>
            <span class="detail-value">{{ runDetail.budget.research_rounds_used }}/{{ runDetail.budget.max_research_rounds }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部提示 -->
    <div class="progress-footer">
      <span v-if="isRunning">
        💡 调查正在后台运行，你可以继续浏览其他内容，运行完成后会自动刷新
      </span>
      <span v-else class="complete-hint">
        🎉 调查运行完成，点击下方 Tab 查看详细结果
      </span>
    </div>
  </div>
</template>

<style scoped>
.run-progress {
  background: white;
  box-shadow:
    0 1px 2px var(--paper-shadow),
    0 8px 32px rgba(60, 45, 20, 0.08);
  overflow: hidden;
}

/* 头部 */
.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24px 32px;
  border-bottom: 1px solid var(--paper-edge);
  background: var(--paper-warm);
}

.ph-status {
  display: flex;
  align-items: center;
  gap: 12px;
}

.status-indicator {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--status-verified);
}

.status-indicator.pulse {
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.2); }
}

.status-text {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 600;
  color: var(--ink-deep);
}

.run-id-badge {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 3px 8px;
  background: white;
  border: 1px solid var(--paper-edge);
  color: var(--ink-muted);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ph-meta {
  display: flex;
  gap: 8px;
}

.meta-chip {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 4px 10px;
  background: white;
  border: 1px solid var(--paper-edge);
  color: var(--ink-soft);
}

/* 阶段进度条 */
.phase-progress {
  display: flex;
  padding: 28px 32px;
  gap: 0;
  border-bottom: 1px solid var(--paper-edge);
  background: white;
  overflow-x: auto;
}

.phase-node {
  display: flex;
  align-items: center;
  gap: 12px;
  position: relative;
  flex: 1;
  min-width: 140px;
}

.phase-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--paper-warm);
  border: 2px solid var(--paper-edge);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
  transition: all 0.4s var(--ease-out);
  color: var(--ink-faint);
}

.phase-node.completed .phase-icon {
  background: var(--accent-pale);
  border-color: var(--accent);
  color: var(--accent);
}

.phase-node.active .phase-icon {
  background: var(--accent);
  border-color: var(--accent);
  color: white;
  animation: iconPulse 2s ease-in-out infinite;
}

@keyframes iconPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(180, 130, 60, 0.4); }
  50% { box-shadow: 0 0 0 10px rgba(180, 130, 60, 0); }
}

.phase-info {
  min-width: 0;
  flex: 1;
}

.phase-label {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-soft);
  margin-bottom: 2px;
  transition: color 0.3s var(--ease-out);
}

.phase-node.completed .phase-label,
.phase-node.active .phase-label {
  color: var(--ink-deep);
}

.phase-desc {
  font-family: var(--font-serif);
  font-size: 11px;
  color: var(--ink-faint);
  font-style: italic;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.phase-connector {
  position: absolute;
  top: 50%;
  right: -50%;
  width: 100%;
  height: 2px;
  background: var(--paper-edge);
  transform: translateY(-50%);
  z-index: 0;
}

.phase-node.completed .phase-connector {
  background: var(--accent);
}

/* 主体 */
.progress-body {
  display: grid;
  grid-template-columns: 1fr 280px;
  gap: 0;
  min-height: 400px;
}

/* 思考面板 */
.thinking-panel {
  border-right: 1px solid var(--paper-edge);
  display: flex;
  flex-direction: column;
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 24px;
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-deep);
  border-bottom: 1px solid var(--paper-edge);
  background: var(--paper-warm);
}

.title-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 2s ease-in-out infinite;
}

.title-sub {
  font-family: var(--font-serif);
  font-style: italic;
  font-weight: 400;
  font-size: 12px;
  color: var(--ink-faint);
  margin-left: 4px;
}

.thinking-logs {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
  max-height: 420px;
}

.log-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 8px 12px;
  margin-bottom: 4px;
  border-radius: 2px;
  transition: all 0.3s var(--ease-out);
  opacity: 0;
  animation: logIn 0.35s var(--ease-out) forwards;
}

@keyframes logIn {
  from {
    opacity: 0;
    transform: translateX(-8px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.log-item.active {
  background: var(--accent-pale);
  border-left: 2px solid var(--accent);
  padding-left: 10px;
}

.log-item.thinking .log-text {
  color: var(--ink-soft);
}

.log-item.step-start {
  margin-top: 8px;
}

.log-item.step-start .log-text {
  font-weight: 600;
  color: var(--ink-deep);
}

.log-item.step-complete .log-text {
  color: var(--status-verified);
  font-weight: 500;
}

.log-item.step-error .log-text {
  color: #dc2626;
}

.log-item.source-summary .log-text,
.log-item.evidence-summary .log-text,
.log-item.claim-summary .log-text {
  font-weight: 600;
  color: var(--ink-deep);
}

.log-item.complete .log-text {
  font-weight: 600;
  color: var(--status-verified);
  font-size: 15px;
}

.log-text {
  font-family: var(--font-serif);
  font-size: 13px;
  line-height: 1.6;
  color: var(--ink-deep);
  word-break: break-word;
  overflow-wrap: break-word;
}

.log-time {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-faint);
  flex-shrink: 0;
  padding-top: 2px;
}

.cursor-blink .log-text {
  animation: blink 1s step-end infinite;
  color: var(--accent);
  font-weight: 600;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.log-empty {
  text-align: center;
  padding: 60px 20px;
  color: var(--ink-muted);
}

.spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--paper-edge);
  border-top-color: var(--accent);
  border-radius: 50%;
  margin: 0 auto 16px;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.log-empty p {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 13px;
  margin: 0;
}

/* 启动中状态 */
.log-starting {
  text-align: center;
  padding: 40px 20px;
}

.starting-dots {
  display: flex;
  justify-content: center;
  gap: 6px;
  margin-bottom: 16px;
}

.starting-dots span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  animation: dotBounce 1.4s ease-in-out infinite;
}

.starting-dots span:nth-child(2) {
  animation-delay: 0.2s;
}

.starting-dots span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes dotBounce {
  0%, 80%, 100% {
    transform: scale(0.6);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}

.log-starting p {
  font-family: var(--font-serif);
  font-size: 14px;
  color: var(--ink-deep);
  margin: 0 0 6px 0;
}

.starting-sub {
  font-style: italic;
  font-size: 12px !important;
  color: var(--ink-muted) !important;
}

.run-id-badge.pending {
  background: var(--accent-pale);
  color: var(--accent);
  border-color: var(--accent-line);
  animation: pulse 2s ease-in-out infinite;
}

/* 统计面板 */
.stats-panel {
  display: flex;
  flex-direction: column;
  background: var(--paper-warm);
}

.stat-cards {
  padding: 16px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.stat-card {
  padding: 14px 12px;
  background: white;
  border: 1px solid var(--paper-edge);
  text-align: center;
  transition: all 0.3s var(--ease-out);
}

.stat-card:hover {
  border-color: var(--accent-line);
  transform: translateY(-1px);
}

.stat-num {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 600;
  color: var(--ink-black);
  margin-bottom: 2px;
  font-variant-numeric: oldstyle-nums;
  transition: all 0.3s var(--ease-out);
}

.stat-card.sources .stat-num { color: #0891b2; }
.stat-card.evidence .stat-num { color: #65a30d; }
.stat-card.claims .stat-num { color: #7c3aed; }
.stat-card.steps .stat-num { color: var(--accent); }

.stat-label {
  font-family: var(--font-serif);
  font-size: 11px;
  color: var(--ink-soft);
  margin-bottom: 8px;
}

.stat-bar {
  height: 3px;
  background: var(--paper-edge);
  border-radius: 2px;
  overflow: hidden;
}

.stat-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.6s var(--ease-out);
  border-radius: 2px;
}

.stat-card.sources .stat-fill { background: #0891b2; }
.stat-card.evidence .stat-fill { background: #65a30d; }
.stat-card.claims .stat-fill { background: #7c3aed; }
.stat-card.steps .stat-fill { background: var(--accent); }

/* 阶段详情 */
.phase-detail {
  padding: 16px;
  border-top: 1px solid var(--paper-edge);
}

.phase-detail h4 {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-deep);
  margin: 0 0 12px 0;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 12px;
}

.detail-label {
  font-family: var(--font-serif);
  color: var(--ink-muted);
}

.detail-value {
  font-family: var(--font-mono);
  color: var(--ink-deep);
  font-size: 11px;
}

/* 底部 */
.progress-footer {
  padding: 14px 32px;
  border-top: 1px solid var(--paper-edge);
  background: var(--paper-warm);
  text-align: center;
  font-family: var(--font-serif);
  font-size: 13px;
  color: var(--ink-muted);
  font-style: italic;
}

.complete-hint {
  color: var(--status-verified);
  font-style: normal;
  font-weight: 500;
}

@media (max-width: 900px) {
  .progress-body {
    grid-template-columns: 1fr;
  }

  .thinking-panel {
    border-right: none;
    border-bottom: 1px solid var(--paper-edge);
  }

  .progress-header {
    flex-direction: column;
    gap: 12px;
    align-items: flex-start;
  }

  .ph-meta {
    flex-wrap: wrap;
  }
}
</style>
