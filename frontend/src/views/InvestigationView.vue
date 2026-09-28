<script setup>
import { ref, computed, watch } from 'vue'

import TopBar from '@/components/TopBar.vue'
import SectionHeading from '@/components/SectionHeading.vue'
import AgentFlow from '@/components/AgentFlow.vue'
import EvidenceChain from '@/components/EvidenceChain.vue'
import MetricsRow from '@/components/MetricsRow.vue'
import Timeline from '@/components/Timeline.vue'
import ClaimList from '@/components/ClaimList.vue'
import ReportPreview from '@/components/ReportPreview.vue'
import SourceList from '@/components/SourceList.vue'
import EvidenceList from '@/components/EvidenceList.vue'
import ConflictGapPanel from '@/components/ConflictGapPanel.vue'
import ReviewPanel from '@/components/ReviewPanel.vue'
import ReportDetail from '@/components/ReportDetail.vue'
import RunProgress from '@/components/RunProgress.vue'

import { runEastPalestineReplay, startInvestigationRun, fetchRunDetail, fetchReportDetail, fetchRunReports } from '@/api/index.js'

const props = defineProps({
  caseData: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['open-search', 'run-started', 'run-completed'])

// Tab 定义
const tabs = [
  { id: 'overview', label: '概览', count: null },
  { id: 'agents', label: '智能体流程', count: 5 },
  { id: 'sources', label: '来源', count: 10 },
  { id: 'evidence', label: '证据', count: 13 },
  { id: 'claims', label: '声明', count: 8 },
  { id: 'conflicts', label: '冲突与缺口', count: 1 },
  { id: 'report', label: '报告', count: null },
  { id: 'review', label: '审核', count: null }
]

const activeTab = ref('overview')
const runLoading = ref(false)
const runError = ref(null)
const runResult = ref(null)
const activeRunId = ref(null)
const runCompleted = ref(false)
const realReport = ref(null) // 后端真实报告数据

const caseName = computed(() => props.caseData.name || props.caseData.title)
const category = computed(() => props.caseData.category || '公共安全')

// 是否为内置案例（有回放功能）
const isBuiltinCase = computed(() => {
  return props.caseData.isBuiltin || props.caseData.id === 'EP-2023-001'
})

// 是否有运行记录
const hasRuns = computed(() => {
  return (props.caseData.run_count && props.caseData.run_count > 0) ||
         (props.caseData.metrics && props.caseData.metrics.sources > 0)
})

// 是否为新调查（无数据）
const isNewInvestigation = computed(() => {
  return !isBuiltinCase.value && !hasRuns.value
})

// 切换调查时重置运行状态
watch(() => props.caseData.id, () => {
  activeRunId.value = null
  runCompleted.value = false
  runLoading.value = false
  runError.value = null
  runResult.value = null
  realReport.value = null
  activeTab.value = 'overview'
})

// 运行回放调查（内置 East Palestine 案例）
// 注意：回放是同步执行的，后端会完整运行后才返回
// 所以前端需要模拟思考过程，让用户看到进度
async function handleReplay() {
  runLoading.value = true
  runError.value = null
  runResult.value = null
  runCompleted.value = false

  // 用一个假的 runId 触发 RunProgress 的模拟模式
  activeRunId.value = 'replay-pending'

  try {
    const result = await runEastPalestineReplay()
    runResult.value = result
    activeRunId.value = result.run_id
    emit('run-started', result)
  } catch (e) {
    runError.value = e.message || '回放启动失败'
    runLoading.value = false
    activeRunId.value = null
  }
  // 注意：回放是同步返回的（后端同步执行），返回时已经完成
  // runLoading 不立即设为 false，让 RunProgress 显示完成状态
}

// 新建调查运行
async function handleStartRun() {
  const invId = props.caseData.investigation_id || props.caseData.id
  if (!invId) {
    runError.value = '当前调查没有 investigation_id，无法启动运行'
    return
  }
  runLoading.value = true
  runError.value = null
  runResult.value = null
  runCompleted.value = false
  try {
    const result = await startInvestigationRun(invId)
    runResult.value = result
    activeRunId.value = result.run_id
    emit('run-started', result)
  } catch (e) {
    runError.value = e.message || '运行启动失败'
    runLoading.value = false
  }
}

// 运行完成回调
async function onRunCompleted(data) {
  runCompleted.value = true
  runLoading.value = false
  // 尝试获取运行的报告
  try {
    const reports = await fetchRunReports(data.run_id)
    if (reports && reports.length > 0) {
      const reportDetail = await fetchReportDetail(reports[0].report_id)
      realReport.value = reportDetail
    }
  } catch (e) {
    console.warn('获取报告失败:', e)
  }
  // 通知父组件刷新数据
  emit('run-completed', data)
}
</script>

<template>
  <div class="investigation-view">
    <TopBar :case-name="caseName" :category="category" @open-search="emit('open-search')" />

    <div class="content-area">

      <!-- Hero 区 -->
      <section class="hero fade-in-up">
        <div class="hero-tag">
          <template v-if="isBuiltinCase">案例档案 · {{ caseData.tag }} · 内置回放</template>
          <template v-else-if="hasRuns">调查档案 · {{ caseData.run_count || 0 }}次运行</template>
          <template v-else>新建调查 · 待开始</template>
        </div>
        <h1 class="hero-title">
          {{ caseData.title }}
        </h1>
        <p class="hero-lede">{{ caseData.subtitle || caseData.description || '点击下方按钮开始调查，系统将自动搜索全网信息并生成结构化调查报告。' }}</p>

        <div class="hero-meta-row" v-if="isBuiltinCase || hasRuns">
          <div class="meta-block">
            <span class="meta-label">档案编号</span>
            <span class="meta-value">{{ caseData.id }}</span>
          </div>
          <div class="meta-block" v-if="caseData.completionDate">
            <span class="meta-label">完成日期</span>
            <span class="meta-value">{{ caseData.completionDate }}</span>
          </div>
          <div class="meta-block">
            <span class="meta-label">验证状态</span>
            <span class="meta-value" :class="hasRuns ? 'verified' : ''">
              {{ hasRuns ? '● 已验证' : '○ 未开始' }}
            </span>
          </div>
          <div class="meta-block">
            <span class="meta-label">信息来源</span>
            <span class="meta-value">{{ caseData.metrics?.sources || caseData.sources?.length || 0 }}个有效来源</span>
          </div>
        </div>

        <!-- 新调查空状态的元信息 -->
        <div class="hero-meta-row" v-else>
          <div class="meta-block">
            <span class="meta-label">调查编号</span>
            <span class="meta-value">{{ caseData.id }}</span>
          </div>
          <div class="meta-block">
            <span class="meta-label">状态</span>
            <span class="meta-value">○ 待开始</span>
          </div>
          <div class="meta-block">
            <span class="meta-label">类型</span>
            <span class="meta-value">{{ caseData.category || '调查' }}</span>
          </div>
          <div class="meta-block">
            <span class="meta-label">运行次数</span>
            <span class="meta-value">0 次</span>
          </div>
        </div>

        <div class="hero-actions">
          <!-- 内置案例：显示回放按钮 -->
          <template v-if="isBuiltinCase">
            <button
              class="btn btn-primary"
              :disabled="runLoading || (activeRunId && !runCompleted)"
              @click="handleReplay"
            >
              <template v-if="runLoading || (activeRunId && !runCompleted)">运行中…</template>
              <template v-else>
                运行回放调查
                <span class="btn-arrow">→</span>
              </template>
            </button>
            <button
              class="btn btn-ghost"
              :disabled="runLoading || (activeRunId && !runCompleted)"
              @click="handleStartRun"
            >
              新建调查运行
            </button>
          </template>

          <!-- 新调查/有运行记录：显示开始调查按钮 -->
          <template v-else>
            <button
              class="btn btn-primary"
              :disabled="runLoading || (activeRunId && !runCompleted)"
              @click="handleStartRun"
            >
              <template v-if="runLoading || (activeRunId && !runCompleted)">
                {{ runCompleted ? '运行完成' : '调查运行中…' }}
              </template>
              <template v-else>
                {{ hasRuns ? '再次运行调查' : '开始调查' }}
                <span class="btn-arrow">→</span>
              </template>
            </button>
            <button
              v-if="hasRuns"
              class="btn btn-ghost"
              @click="activeTab = 'report'"
            >
              查看报告
            </button>
          </template>
        </div>

        <!-- 运行结果反馈 -->
        <div v-if="runResult" class="run-feedback success">
          ✓ 调查运行已启动 — 运行编号 {{ runResult.run_id }}，状态：{{ runResult.run_status }}
        </div>
        <div v-if="runError" class="run-feedback error">
          ✗ {{ runError }}（请确认后端服务已启动：uv run marketpulse-api）
        </div>
      </section>

      <!-- 运行进度展示（运行中时显示，替代 Tab 内容） -->
      <RunProgress
        v-if="(activeRunId && !runCompleted) || runLoading"
        :run-id="activeRunId || ''"
        :starting="runLoading && !activeRunId"
        @completed="onRunCompleted"
        class="run-progress-wrap fade-in-up"
      />

      <!-- 章节导航 Tabs + Tab 内容（运行完成或未运行时显示） -->
      <template v-else>
        <!-- 新调查空状态 -->
        <div v-if="isNewInvestigation" class="empty-investigation fade-in-up">
          <div class="empty-icon">
            <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
              <circle cx="32" cy="32" r="28" stroke="currentColor" stroke-width="2" stroke-dasharray="4 4"/>
              <circle cx="32" cy="32" r="18" stroke="currentColor" stroke-width="1.5"/>
              <path d="M32 14v36M14 32h36" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
          </div>
          <h2 class="empty-title">开始你的调查</h2>
          <p class="empty-desc">
            点击上方「开始调查」按钮，系统将自动：
          </p>
          <div class="empty-steps">
            <div class="empty-step">
              <span class="step-num">1</span>
              <div>
                <div class="step-title">全网搜索</div>
                <div class="step-desc">在 DuckDuckGo、Bing、Yahoo 等引擎检索相关信息</div>
              </div>
            </div>
            <div class="empty-step">
              <span class="step-num">2</span>
              <div>
                <div class="step-title">采集证据</div>
                <div class="step-desc">抓取权威来源页面，提取事实证据片段</div>
              </div>
            </div>
            <div class="empty-step">
              <span class="step-num">3</span>
              <div>
                <div class="step-title">验证分析</div>
                <div class="step-desc">交叉验证声明，识别冲突与研究缺口</div>
              </div>
            </div>
            <div class="empty-step">
              <span class="step-num">4</span>
              <div>
                <div class="step-title">生成报告</div>
                <div class="step-desc">输出 17 章节结构化调查报告，附完整引用溯源</div>
              </div>
            </div>
          </div>
          <button class="btn btn-primary empty-cta" @click="handleStartRun">
            开始调查
            <span class="btn-arrow">→</span>
          </button>
        </div>

        <!-- 有数据时显示 Tab 内容 -->
        <template v-else>
        <!-- 章节导航 Tabs -->
        <nav class="section-nav">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          class="nav-tab"
          :class="{ active: activeTab === tab.id }"
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
          <span v-if="tab.count" class="tab-count">{{ tab.count }}</span>
        </button>
      </nav>

      <!-- 概览内容 -->
      <template v-if="activeTab === 'overview'">
        <!-- 智能体流程 -->
        <AgentFlow :agents="caseData.agents" class="fade-in-up" style="animation-delay: 0.1s;">
          <template #heading>
            <SectionHeading
              section-num="§ 01"
              section-name="多智能体协作流程"
              section-desc="Planner · Researcher · Analyst · Verifier · Writer"
            />
          </template>
        </AgentFlow>

        <!-- 证据链 -->
        <EvidenceChain :chain="caseData.evidenceChain" class="fade-in-up" style="animation-delay: 0.15s;">
          <template #heading>
            <SectionHeading
              section-num="§ 02"
              section-name="证据链路"
              section-desc="从原始来源到验证结论的完整追溯"
            />
          </template>
        </EvidenceChain>

        <!-- 指标行 -->
        <MetricsRow :metrics="caseData.metrics" class="fade-in-up" style="animation-delay: 0.2s;" />

        <!-- 两列：时间线 + 声明 -->
        <div class="two-column fade-in-up" style="animation-delay: 0.25s;">
          <div>
            <SectionHeading
              section-num="§ 03"
              section-name="事件时间线"
            />
            <Timeline :items="caseData.timeline" />
          </div>
          <div>
            <SectionHeading
              section-num="§ 04"
              section-name="已验证声明"
            />
            <ClaimList :claims="caseData.claims.slice(0, 3)" />
          </div>
        </div>

        <!-- 报告预览 -->
        <ReportPreview :findings="caseData.reportFindings" class="fade-in-up" style="animation-delay: 0.3s;">
          <template #heading>
            <SectionHeading
              section-num="§ 05"
              section-name="报告摘选"
              section-desc="点击上标引用可溯源至原始证据"
            />
          </template>
        </ReportPreview>

        <!-- 来源列表 -->
        <SourceList :sources="caseData.sources" class="fade-in-up" style="animation-delay: 0.35s;">
          <template #heading>
            <SectionHeading
              section-num="§ 06"
              section-name="参考文献与来源"
              :section-desc="`${caseData.metrics.sources}个有效来源 · 7个官方一手 · 3种类型`"
            />
          </template>
        </SourceList>
      </template>

      <!-- 智能体流程 Tab -->
      <template v-else-if="activeTab === 'agents'">
        <AgentFlow :agents="caseData.agents">
          <template #heading>
            <SectionHeading
              section-num="§ 01"
              section-name="多智能体协作流程"
              section-desc="5个智能体协同完成调查"
            />
          </template>
        </AgentFlow>
      </template>

      <!-- 来源 Tab -->
      <template v-else-if="activeTab === 'sources'">
        <SourceList :sources="caseData.sources">
          <template #heading>
            <SectionHeading
              section-num="§ 02"
              section-name="参考文献与来源"
              :section-desc="`${caseData.metrics.sources}个有效来源`"
            />
          </template>
        </SourceList>
      </template>

      <!-- 证据 Tab -->
      <template v-else-if="activeTab === 'evidence'">
        <SectionHeading
          section-num="§ 03"
          section-name="证据片段"
          :section-desc="`${caseData.evidence?.length || 0}条证据 · 全部可定位溯源`"
        />
        <EvidenceList :evidence="caseData.evidence || []" />
      </template>

      <!-- 声明 Tab -->
      <template v-else-if="activeTab === 'claims'">
        <SectionHeading
          section-num="§ 04"
          section-name="已验证声明"
          :section-desc="`${caseData.claims.length}项事实声明`"
        />
        <ClaimList :claims="caseData.claims" />
      </template>

      <!-- 冲突与缺口 Tab -->
      <template v-else-if="activeTab === 'conflicts'">
        <SectionHeading
          section-num="§ 05"
          section-name="冲突与研究缺口"
          :section-desc="`${caseData.conflicts?.length || 0}个冲突 · ${caseData.gaps?.length || 0}个缺口`"
        />
        <ConflictGapPanel
          :conflicts="caseData.conflicts || []"
          :gaps="caseData.gaps || []"
        />
      </template>

      <!-- 报告 Tab -->
      <template v-else-if="activeTab === 'report'">
        <ReportDetail :report-data="realReport || caseData" />
      </template>

      <!-- 审核 Tab -->
      <template v-else-if="activeTab === 'review'">
        <SectionHeading
          section-num="§ 07"
          section-name="审核与发布"
          :section-desc="caseData.review?.policy_version ? `政策版本 ${caseData.review.policy_version}` : ''"
        />
        <ReviewPanel :review="caseData.review || {}" />
      </template>

      <div class="page-footer">
        <span>Folio Investigation Journal</span>
        <span>第 1 页 / 共 17 节</span>
      </div>
      </template>
      </template>
    </div>
  </div>
</template>

<style scoped>
.investigation-view {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.content-area {
  padding: 56px 64px 80px;
  flex: 1;
  max-width: var(--content-max-width);
  margin: 0 auto;
  width: 100%;
}

/* Hero */
.hero {
  margin-bottom: 64px;
  position: relative;
}

.hero-tag {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 28px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent);
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.hero-tag::before {
  content: '';
  width: 28px;
  height: 1px;
  background: var(--accent);
}

.hero-title {
  font-family: var(--font-display);
  font-size: 52px;
  font-weight: 500;
  line-height: 1.15;
  color: var(--ink-black);
  margin-bottom: 24px;
  letter-spacing: -0.02em;
  font-variation-settings: "opsz" 144;
  word-break: break-word;
  overflow-wrap: break-word;
}

.hero-title em {
  font-style: italic;
  font-weight: 400;
  color: var(--ink-soft);
}

.hero-lede {
  max-width: 640px;
  font-size: 18px;
  line-height: 1.8;
  color: var(--ink-soft);
  font-family: var(--font-serif);
  font-style: italic;
  font-weight: 400;
  padding-left: 24px;
  border-left: 2px solid var(--accent-line);
  margin-bottom: 32px;
}

.hero-meta-row {
  display: flex;
  gap: 48px;
  padding-top: 24px;
  border-top: 1px solid var(--paper-edge);
  position: relative;
}

.hero-meta-row::before {
  content: '';
  position: absolute;
  top: -1px;
  left: 0;
  width: 40px;
  height: 1px;
  background: var(--accent);
}

.meta-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-label {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-faint);
}

.meta-value {
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 600;
  color: var(--ink-deep);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.meta-value.verified {
  color: var(--status-verified);
}

.hero-actions {
  display: flex;
  gap: 12px;
  margin-top: 32px;
}

.btn {
  padding: 14px 28px;
  border-radius: 2px;
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.4s var(--ease-out);
  border: 1px solid transparent;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  position: relative;
  overflow: hidden;
}

.btn-primary {
  background: var(--ink-black);
  color: var(--paper-base);
  border-color: var(--ink-black);
}

.btn-primary::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.1), transparent);
  transition: left 0.6s var(--ease-out);
}

.btn-primary:hover::before {
  left: 100%;
}

.btn-primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(28, 22, 16, 0.15);
}

.btn-ghost {
  background: transparent;
  color: var(--ink-soft);
  border-color: var(--paper-edge);
}

.btn-ghost:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.btn-arrow {
  transition: transform 0.35s var(--ease-out);
  font-style: normal;
}

.btn:hover .btn-arrow {
  transform: translateX(4px);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 运行结果反馈 */
.run-feedback {
  margin-top: 16px;
  padding: 12px 20px;
  font-family: var(--font-serif);
  font-size: 14px;
  border-left: 3px solid;
}

.run-feedback.success {
  background: var(--accent-pale);
  border-left-color: var(--status-verified);
  color: var(--ink-deep);
}

.run-feedback.error {
  background: #fef2f2;
  border-left-color: #dc2626;
  color: #991b1b;
}

/* 章节导航 Tabs */
.section-nav {
  display: flex;
  gap: 0;
  margin-bottom: 48px;
  border-bottom: 1px solid var(--paper-edge);
  position: relative;
  overflow-x: auto;
}

.nav-tab {
  padding: 16px 0;
  margin-right: 36px;
  background: none;
  border: none;
  font-family: var(--font-serif);
  font-size: 14px;
  font-weight: 500;
  color: var(--ink-muted);
  cursor: pointer;
  position: relative;
  transition: color 0.35s var(--ease-out);
  white-space: nowrap;
  flex-shrink: 0;
}

.nav-tab::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 0;
  width: 0;
  height: 1px;
  background: var(--ink-black);
  transition: width 0.5s var(--ease-out);
}

.nav-tab:hover {
  color: var(--ink-deep);
}

.nav-tab.active {
  color: var(--ink-black);
  font-weight: 600;
}

.nav-tab.active::after {
  width: 100%;
}

.tab-count {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-faint);
  margin-left: 6px;
  font-weight: 400;
}

/* 两列布局 */
.two-column {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 64px;
  margin-bottom: 56px;
}

/* 占位 */
.tab-placeholder {
  padding: 80px 0;
  text-align: center;
}

.placeholder-text {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 18px;
  color: var(--ink-faint);
}

/* 底部 */
/* 新调查空状态 */
.empty-investigation {
  text-align: center;
  padding: 80px 40px;
  background: white;
  box-shadow: 0 1px 2px var(--paper-shadow), 0 8px 32px rgba(60, 45, 20, 0.06);
}

.empty-icon {
  width: 80px;
  height: 80px;
  margin: 0 auto 24px;
  color: var(--accent);
  opacity: 0.6;
}

.empty-icon svg {
  width: 100%;
  height: 100%;
}

.empty-title {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 600;
  color: var(--ink-deep);
  margin: 0 0 12px 0;
}

.empty-desc {
  font-family: var(--font-serif);
  font-size: 14px;
  color: var(--ink-soft);
  margin: 0 0 32px 0;
  font-style: italic;
}

.empty-steps {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  max-width: 500px;
  margin: 0 auto 32px;
  text-align: left;
}

.empty-step {
  display: flex;
  gap: 12px;
  padding: 16px;
  background: var(--paper-warm);
  border: 1px solid var(--paper-edge);
  transition: all 0.3s var(--ease-out);
}

.empty-step:hover {
  border-color: var(--accent-line);
  transform: translateY(-2px);
  background: white;
}

.step-num {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--accent-pale);
  color: var(--accent);
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.step-title {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-deep);
  margin-bottom: 4px;
}

.step-desc {
  font-family: var(--font-serif);
  font-size: 12px;
  color: var(--ink-muted);
  line-height: 1.5;
}

.empty-cta {
  margin-top: 8px;
}

.page-footer {
  margin-top: 80px;
  padding-top: 24px;
  border-top: 1px solid var(--paper-edge);
  display: flex;
  justify-content: space-between;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-faint);
}

/* 响应式 */
@media (max-width: 1200px) {
  .content-area {
    padding: 40px 40px 64px;
  }
}

@media (max-width: 900px) {
  .two-column {
    grid-template-columns: 1fr;
    gap: 40px;
  }

  .hero-title {
    font-size: 36px;
  }

  .hero-meta-row {
    flex-wrap: wrap;
    gap: 24px;
  }
}
</style>
