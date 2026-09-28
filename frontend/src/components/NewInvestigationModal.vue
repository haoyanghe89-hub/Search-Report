<script setup>
import { ref, computed, watch } from 'vue'
import { createInvestigation } from '@/api/index.js'

const emit = defineEmits(['close', 'created'])

// 步骤
const currentStep = ref(1)
const totalSteps = 4

// 表单数据
const formData = ref({
  title: '',
  event_description: '',
  investigation_goal: '',
  questions: ['', '', '']
})

// 加载状态
const loading = ref(false)
const error = ref(null)

// 步骤标题
const steps = [
  { num: 1, title: '事件标题', desc: '给这次调查起个名字' },
  { num: 2, title: '事件描述', desc: '简述发生了什么' },
  { num: 3, title: '调查目标', desc: '你想弄清楚什么' },
  { num: 4, title: '关键问题', desc: '列出待解答的问题' }
]

// 当前步骤是否可进入下一步
const canProceed = computed(() => {
  switch (currentStep.value) {
    case 1:
      return formData.value.title.trim().length >= 2
    case 2:
      return formData.value.event_description.trim().length >= 10
    case 3:
      return formData.value.investigation_goal.trim().length >= 5
    case 4:
      return true
    default:
      return false
  }
})

// 下一步
function nextStep() {
  if (currentStep.value < totalSteps && canProceed.value) {
    currentStep.value++
  }
}

// 上一步
function prevStep() {
  if (currentStep.value > 1) {
    currentStep.value--
  }
}

// 添加问题
function addQuestion() {
  if (formData.value.questions.length < 8) {
    formData.value.questions.push('')
  }
}

// 删除问题
function removeQuestion(index) {
  if (formData.value.questions.length > 1) {
    formData.value.questions.splice(index, 1)
  }
}

// 提交创建
async function submitCreate() {
  loading.value = true
  error.value = null
  try {
    // 过滤空问题
    const questions = formData.value.questions.filter(q => q.trim())
    
    const result = await createInvestigation({
      title: formData.value.title.trim(),
      event_description: formData.value.event_description.trim(),
      investigation_goal: formData.value.investigation_goal.trim(),
      questions
    })
    
    emit('created', result)
    emit('close')
  } catch (e) {
    error.value = e.message || '创建失败，请重试'
    console.error('创建调查失败:', e)
  } finally {
    loading.value = false
  }
}

// 关闭弹窗
function handleClose() {
  if (!loading.value) {
    emit('close')
  }
}

// 按 ESC 关闭
function handleKeydown(e) {
  if (e.key === 'Escape') {
    handleClose()
  }
}
</script>

<template>
  <div class="modal-overlay" @click.self="handleClose" @keydown="handleKeydown" tabindex="0">
    <div class="modal-content">
      <!-- 头部 -->
      <div class="modal-header">
        <h2 class="modal-title">新建调查</h2>
        <button class="close-btn" @click="handleClose" :disabled="loading">
          <span class="close-x">×</span>
        </button>
      </div>

      <!-- 步骤指示器 -->
      <div class="step-indicator">
        <div
          v-for="step in steps"
          :key="step.num"
          class="step-item"
          :class="{
            active: currentStep === step.num,
            completed: currentStep > step.num
          }"
        >
          <div class="step-num">{{ step.num }}</div>
          <div class="step-info">
            <div class="step-title">{{ step.title }}</div>
            <div class="step-desc">{{ step.desc }}</div>
          </div>
        </div>
      </div>

      <!-- 进度条 -->
      <div class="progress-bar">
        <div
          class="progress-fill"
          :style="{ width: ((currentStep - 1) / (totalSteps - 1) * 100) + '%' }"
        ></div>
      </div>

      <!-- 表单内容 -->
      <div class="modal-body">
        <!-- 步骤1：事件标题 -->
        <div v-if="currentStep === 1" class="form-step">
          <label class="form-label">
            调查标题
            <span class="label-hint">简明扼要地概括事件</span>
          </label>
          <input
            v-model="formData.title"
            type="text"
            class="form-input large"
            placeholder="例如：2023年东巴勒斯坦列车脱轨事故"
            maxlength="200"
          />
          <div class="char-count">{{ formData.title.length }}/200</div>
        </div>

        <!-- 步骤2：事件描述 -->
        <div v-if="currentStep === 2" class="form-step">
          <label class="form-label">
            事件描述
            <span class="label-hint">描述事件的基本情况和背景</span>
          </label>
          <textarea
            v-model="formData.event_description"
            class="form-textarea"
            placeholder="请详细描述事件的时间、地点、经过、涉及方等基本信息…"
            rows="6"
            maxlength="2000"
          ></textarea>
          <div class="char-count">{{ formData.event_description.length }}/2000</div>
        </div>

        <!-- 步骤3：调查目标 -->
        <div v-if="currentStep === 3" class="form-step">
          <label class="form-label">
            调查目标
            <span class="label-hint">你希望通过这次调查回答什么核心问题</span>
          </label>
          <textarea
            v-model="formData.investigation_goal"
            class="form-textarea"
            placeholder="例如：调查事故的根本原因、责任归属及环境影响…"
            rows="5"
            maxlength="1000"
          ></textarea>
          <div class="char-count">{{ formData.investigation_goal.length }}/1000</div>
          
          <div class="tips-box">
            <div class="tips-title">💡 提示</div>
            <p class="tips-text">
              好的调查目标应该具体、可验证。避免过于宽泛的表述，
              例如"了解事故情况"不如"确定事故的直接原因和根本原因"。
            </p>
          </div>
        </div>

        <!-- 步骤4：关键问题 -->
        <div v-if="currentStep === 4" class="form-step">
          <label class="form-label">
            关键问题
            <span class="label-hint">列出你希望解答的具体问题（可选）</span>
          </label>
          
          <div class="question-list">
            <div
              v-for="(q, index) in formData.questions"
              :key="index"
              class="question-item"
            >
              <span class="question-num">{{ index + 1 }}</span>
              <input
                v-model="formData.questions[index]"
                type="text"
                class="form-input"
                :placeholder="`问题 ${index + 1}（可选）`"
                maxlength="200"
              />
              <button
                v-if="formData.questions.length > 1"
                class="remove-btn"
                @click="removeQuestion(index)"
                title="删除此问题"
              >
                ×
              </button>
            </div>
          </div>
          
          <button
            v-if="formData.questions.length < 8"
            class="add-question-btn"
            @click="addQuestion"
          >
            <span class="plus">+</span>
            添加问题
          </button>

          <!-- 摘要预览 -->
          <div class="summary-preview">
            <div class="summary-title">调查摘要</div>
            <div class="summary-item">
              <span class="summary-label">标题：</span>
              <span class="summary-value">{{ formData.title || '（未填写）' }}</span>
            </div>
            <div class="summary-item">
              <span class="summary-label">目标：</span>
              <span class="summary-value">{{ formData.investigation_goal || '（未填写）' }}</span>
            </div>
            <div class="summary-item">
              <span class="summary-label">问题数：</span>
              <span class="summary-value">
                {{ formData.questions.filter(q => q.trim()).length }} 个有效问题
              </span>
            </div>
          </div>
        </div>

        <!-- 错误提示 -->
        <div v-if="error" class="error-alert">
          {{ error }}
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="modal-footer">
        <button
          class="btn btn-ghost"
          @click="handleClose"
          :disabled="loading"
        >
          取消
        </button>
        <div class="footer-right">
          <button
            v-if="currentStep > 1"
            class="btn btn-ghost"
            @click="prevStep"
            :disabled="loading"
          >
            上一步
          </button>
          <button
            v-if="currentStep < totalSteps"
            class="btn btn-primary"
            @click="nextStep"
            :disabled="!canProceed || loading"
          >
            下一步
            <span class="btn-arrow">→</span>
          </button>
          <button
            v-else
            class="btn btn-primary"
            @click="submitCreate"
            :disabled="loading"
          >
            <span v-if="loading">创建中…</span>
            <span v-else>创建调查</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(28, 22, 16, 0.5);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn 0.3s var(--ease-out);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal-content {
  background: var(--paper-base);
  width: 560px;
  max-width: 90vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  box-shadow:
    0 4px 12px var(--paper-shadow),
    0 24px 60px rgba(60, 45, 20, 0.15);
  animation: slideUp 0.4s var(--ease-out);
  position: relative;
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 头部 */
.modal-header {
  padding: 28px 32px 20px;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  border-bottom: 1px solid var(--paper-edge);
}

.modal-title {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 600;
  color: var(--ink-black);
}

.close-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--ink-muted);
  cursor: pointer;
  font-size: 20px;
  transition: all 0.3s var(--ease-out);
  border-radius: 4px;
}

.close-btn:hover {
  background: var(--accent-pale);
  color: var(--accent);
}

.close-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 步骤指示器 */
.step-indicator {
  display: flex;
  gap: 16px;
  padding: 20px 32px;
  background: var(--paper-warm);
  border-bottom: 1px solid var(--paper-edge);
}

.step-item {
  flex: 1;
  display: flex;
  gap: 10px;
  align-items: flex-start;
  opacity: 0.5;
  transition: opacity 0.3s var(--ease-out);
}

.step-item.active {
  opacity: 1;
}

.step-item.completed {
  opacity: 0.8;
}

.step-num {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--paper-base);
  border: 1.5px solid var(--paper-edge);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 600;
  font-size: 14px;
  color: var(--ink-muted);
  flex-shrink: 0;
  transition: all 0.3s var(--ease-out);
}

.step-item.active .step-num {
  background: var(--accent-pale);
  border-color: var(--accent);
  color: var(--accent);
}

.step-item.completed .step-num {
  background: var(--status-verified);
  border-color: var(--status-verified);
  color: white;
}

.step-info {
  min-width: 0;
}

.step-title {
  font-family: var(--font-serif);
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-deep);
  margin-bottom: 2px;
}

.step-desc {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 11px;
  color: var(--ink-faint);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 进度条 */
.progress-bar {
  height: 2px;
  background: var(--paper-edge);
  position: relative;
}

.progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.5s var(--ease-out);
}

/* 表单主体 */
.modal-body {
  flex: 1;
  padding: 28px 32px;
  overflow-y: auto;
}

.form-step {
  animation: fadeIn 0.4s var(--ease-out);
}

.form-label {
  display: block;
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 600;
  color: var(--ink-deep);
  margin-bottom: 12px;
}

.label-hint {
  display: block;
  font-family: var(--font-serif);
  font-style: italic;
  font-weight: 400;
  font-size: 12px;
  color: var(--ink-faint);
  margin-top: 4px;
}

.form-input {
  width: 100%;
  padding: 12px 16px;
  border: 1px solid var(--paper-edge);
  background: var(--paper-base);
  font-family: var(--font-serif);
  font-size: 15px;
  color: var(--ink-deep);
  transition: all 0.3s var(--ease-out);
}

.form-input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-pale);
}

.form-input.large {
  font-size: 18px;
  padding: 14px 16px;
  font-weight: 500;
}

.form-textarea {
  width: 100%;
  padding: 12px 16px;
  border: 1px solid var(--paper-edge);
  background: var(--paper-base);
  font-family: var(--font-serif);
  font-size: 14px;
  line-height: 1.7;
  color: var(--ink-deep);
  resize: vertical;
  transition: all 0.3s var(--ease-out);
}

.form-textarea:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-pale);
}

.char-count {
  text-align: right;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-faint);
  margin-top: 6px;
}

.tips-box {
  margin-top: 20px;
  padding: 16px 20px;
  background: var(--paper-warm);
  border-left: 2px solid var(--accent-light);
}

.tips-title {
  font-family: var(--font-serif);
  font-weight: 600;
  font-size: 13px;
  color: var(--ink-deep);
  margin-bottom: 6px;
}

.tips-text {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink-soft);
}

/* 问题列表 */
.question-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 16px;
}

.question-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.question-num {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--accent);
  font-weight: 600;
  min-width: 20px;
}

.question-item .form-input {
  flex: 1;
  padding: 10px 14px;
  font-size: 14px;
}

.remove-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--ink-faint);
  cursor: pointer;
  font-size: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  transition: all 0.3s var(--ease-out);
  flex-shrink: 0;
}

.remove-btn:hover {
  background: var(--accent-pale);
  color: var(--accent);
}

.add-question-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px dashed var(--paper-edge);
  background: transparent;
  color: var(--ink-muted);
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.3s var(--ease-out);
}

.add-question-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-pale);
}

.add-question-btn .plus {
  font-style: normal;
  font-size: 14px;
}

/* 摘要预览 */
.summary-preview {
  margin-top: 24px;
  padding: 20px;
  background: var(--paper-warm);
  border: 1px solid var(--paper-edge);
}

.summary-title {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-deep);
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--paper-edge);
}

.summary-item {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
}

.summary-item:last-child {
  margin-bottom: 0;
}

.summary-label {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-faint);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  flex-shrink: 0;
  min-width: 50px;
}

.summary-value {
  font-family: var(--font-serif);
  color: var(--ink-soft);
  word-break: break-all;
}

/* 错误提示 */
.error-alert {
  margin-top: 16px;
  padding: 12px 16px;
  background: rgba(139, 58, 26, 0.08);
  border: 1px solid rgba(139, 58, 26, 0.3);
  color: var(--status-disputed);
  font-family: var(--font-serif);
  font-size: 13px;
}

/* 底部 */
.modal-footer {
  padding: 20px 32px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid var(--paper-edge);
  background: var(--paper-warm);
}

.footer-right {
  display: flex;
  gap: 10px;
}

.btn {
  padding: 10px 20px;
  border-radius: 2px;
  font-family: var(--font-serif);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.4s var(--ease-out);
  border: 1px solid transparent;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  position: relative;
  overflow: hidden;
}

.btn-primary {
  background: var(--ink-black);
  color: var(--paper-base);
  border-color: var(--ink-black);
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(28, 22, 16, 0.15);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-ghost {
  background: transparent;
  color: var(--ink-soft);
  border-color: var(--paper-edge);
}

.btn-ghost:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.btn-ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-arrow {
  transition: transform 0.35s var(--ease-out);
  font-style: normal;
}

.btn:hover:not(:disabled) .btn-arrow {
  transform: translateX(4px);
}
</style>
