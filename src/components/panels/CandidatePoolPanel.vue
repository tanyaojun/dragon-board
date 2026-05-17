<template>
  <Teleport to="body">
    <div v-if="visible" class="candidate-mask" @click.self="close">
      <section class="candidate-panel">
        <header class="candidate-header">
          <div>
            <h2>候选池</h2>
            <p>规则分析驱动的候选股跟踪工作台</p>
          </div>
          <button class="icon-btn" title="关闭" @click="close">×</button>
        </header>

        <div class="candidate-toolbar">
          <select v-model="statusFilter" @change="loadCandidates">
            <option value="">全部状态</option>
            <option value="observe">观察</option>
            <option value="candidate">候选</option>
            <option value="triggered">触发</option>
            <option value="tracking">跟踪中</option>
            <option value="pending-review">待复盘</option>
            <option value="reviewed">已复盘</option>
          </select>
          <button class="text-btn" @click="loadCandidates">刷新</button>
          <span class="summary">共 {{ candidates.length }} 条</span>
        </div>

        <div class="stats-row">
          <div class="stat-card">
            <span>今日新增</span>
            <strong>{{ candidateStats.todayNew }}</strong>
          </div>
          <div class="stat-card">
            <span>观察/候选</span>
            <strong>{{ candidateStats.openCount }}</strong>
          </div>
          <div class="stat-card">
            <span>触发跟踪</span>
            <strong>{{ candidateStats.activeCount }}</strong>
          </div>
          <div class="stat-card">
            <span>待复盘</span>
            <strong>{{ candidateStats.pendingReview }}</strong>
          </div>
          <div class="stat-card">
            <span>平均评分</span>
            <strong>{{ candidateStats.averageScore }}</strong>
          </div>
          <div class="stat-card risk-card">
            <span>当前风险</span>
            <strong>{{ candidateStats.riskCount }}</strong>
          </div>
          <div class="stat-card">
            <span>触发率</span>
            <strong>{{ candidateStats.triggerRate }}</strong>
          </div>
          <div class="stat-card">
            <span>失效率</span>
            <strong>{{ candidateStats.failureRate }}</strong>
          </div>
          <div class="stat-card">
            <span>复盘胜率</span>
            <strong>{{ candidateStats.reviewWinRate }}</strong>
          </div>
        </div>

        <div v-if="errorMessage" class="error">{{ errorMessage }}</div>

        <div class="candidate-body">
          <aside class="candidate-list">
            <div v-if="loading" class="empty">加载中...</div>
            <div v-else-if="!candidates.length" class="empty">暂无候选股</div>
            <button
              v-for="entry in candidates"
              v-else
              :key="entry.id"
              class="candidate-item"
              :class="{ active: selectedId === entry.id }"
              @click="selectedId = entry.id"
            >
              <span class="stock-line">
                <strong>{{ entry.stockName || entry.stockCode }}</strong>
                <span>{{ entry.stockCode }}</span>
              </span>
              <span class="meta-line">
                <span>{{ statusLabel(entry.status) }}</span>
                <span>{{ reviewOf(entry).currentAnalysis.grade }}级 · {{ reviewOf(entry).currentAnalysis.score }}分</span>
              </span>
              <span class="meta-line">
                <span>{{ reviewOf(entry).stateLabel }}</span>
                <span :class="deltaClass(reviewOf(entry).scoreDelta)">
                  {{ formatDelta(reviewOf(entry).scoreDelta) }}
                </span>
              </span>
            </button>
          </aside>

          <main class="candidate-detail">
            <template v-if="selectedEntry && selectedReview">
              <div class="detail-title">
                <div>
                  <h3>{{ selectedEntry.stockName || selectedEntry.stockCode }}</h3>
                  <span>{{ selectedEntry.stockCode }} · {{ statusLabel(selectedEntry.status) }}</span>
                </div>
                <div class="status-actions">
                  <button
                    v-for="status in nextStatuses"
                    :key="status"
                    :disabled="updatingStatus"
                    @click="updateStatus(status)"
                  >
                    {{ statusLabel(status) }}
                  </button>
                </div>
              </div>

              <section class="analysis-card">
                <div class="section-header">
                  <h4>规则分析</h4>
                  <button class="text-btn" :disabled="writingAnalysis" @click="writeBackAnalysis">
                    写回当前分析
                  </button>
                </div>
                <div class="analysis-compare">
                  <div>
                    <span>入池快照</span>
                    <strong>{{ selectedReview.savedAnalysis.grade }}级 · {{ selectedReview.savedAnalysis.score }}分</strong>
                  </div>
                  <div>
                    <span>当前重分析</span>
                    <strong>{{ selectedReview.currentAnalysis.grade }}级 · {{ selectedReview.currentAnalysis.score }}分</strong>
                  </div>
                  <div>
                    <span>{{ selectedReview.stateLabel }}</span>
                    <strong :class="deltaClass(selectedReview.scoreDelta)">
                      {{ formatDelta(selectedReview.scoreDelta) }}
                    </strong>
                  </div>
                </div>
                <div class="breakdown">
                  <span>RankTrend {{ selectedReview.currentAnalysis.scoreBreakdown.rankTrend }}</span>
                  <span>题材 {{ selectedReview.currentAnalysis.scoreBreakdown.theme }}</span>
                  <span>龙头 {{ selectedReview.currentAnalysis.scoreBreakdown.dragon }}</span>
                  <span>情绪 {{ selectedReview.currentAnalysis.scoreBreakdown.sentiment }}</span>
                  <span>资金 {{ selectedReview.currentAnalysis.scoreBreakdown.moneyFlow }}</span>
                </div>
                <ul class="state-reasons">
                  <li v-for="reason in selectedReview.stateReasons" :key="reason">{{ reason }}</li>
                </ul>
              </section>

              <section class="editor-card">
                <div class="section-header">
                  <h4>假设编辑</h4>
                  <button class="text-btn" :disabled="savingThesis" @click="saveThesis">保存假设</button>
                </div>
                <div class="form-grid thesis-grid">
                  <label>
                    <span>入池理由</span>
                    <textarea v-model="thesisForm.entryReason" rows="3" />
                  </label>
                  <label>
                    <span>交易假设</span>
                    <textarea v-model="thesisForm.tradeHypothesis" rows="3" />
                  </label>
                  <label>
                    <span>买入前提</span>
                    <textarea v-model="thesisForm.entryPrerequisites" rows="3" />
                  </label>
                  <label>
                    <span>失效条件</span>
                    <textarea v-model="thesisForm.invalidationRules" rows="3" />
                  </label>
                </div>
                <div class="inline-form">
                  <label>
                    <span>人工决策</span>
                    <select v-model="thesisForm.humanDecision">
                      <option value="watch">观察</option>
                      <option value="execute">执行</option>
                      <option value="skip">跳过</option>
                    </select>
                  </label>
                  <label>
                    <span>未执行原因</span>
                    <input v-model="thesisForm.skipReason" placeholder="如 条件未确认 / 仓位不足" />
                  </label>
                </div>
              </section>

              <section class="review-card">
                <div class="section-header">
                  <h4>复盘闭环</h4>
                  <button class="text-btn" :disabled="savingReview" @click="saveReview">保存复盘</button>
                </div>
                <div class="form-grid review-grid">
                  <label>
                    <span>复盘结果</span>
                    <select v-model="reviewForm.reviewOutcome">
                      <option value="pending">待复盘</option>
                      <option value="success">成功</option>
                      <option value="partial">部分兑现</option>
                      <option value="failed">失败</option>
                      <option value="not_triggered">未触发</option>
                    </select>
                  </label>
                  <label>
                    <span>模型结果</span>
                    <select v-model="reviewForm.modelResult">
                      <option value="unknown">未判断</option>
                      <option value="correct">模型正确</option>
                      <option value="partial">部分正确</option>
                      <option value="wrong">模型错误</option>
                    </select>
                  </label>
                  <label>
                    <span>执行结果</span>
                    <select v-model="reviewForm.executionResult">
                      <option value="unknown">未判断</option>
                      <option value="good">执行到位</option>
                      <option value="early_sell">卖早</option>
                      <option value="late_sell">卖晚</option>
                      <option value="chased">追高</option>
                      <option value="missed">错过</option>
                      <option value="no_trade">未交易</option>
                    </select>
                  </label>
                </div>
                <label class="full-field">
                  <span>复盘结论</span>
                  <textarea v-model="reviewForm.reviewNotes" rows="3" />
                </label>
              </section>

              <section v-if="selectedReview.currentAnalysis.riskWarnings.length">
                <h4>风险提示</h4>
                <ul>
                  <li v-for="risk in selectedReview.currentAnalysis.riskWarnings" :key="risk">{{ risk }}</li>
                </ul>
              </section>
            </template>
            <div v-else class="empty detail-empty">选择一条候选股查看分析详情</div>
          </main>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { candidateJournalService } from '@/services/candidate/CandidateJournalService'
import type {
  CandidateJournalEntry,
  CandidateReviewUpdate,
  CandidateStatus,
  CandidateThesisUpdate,
  CandidateWorkbenchReview,
} from '@/services/candidate/types'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  (event: 'update:visible', value: boolean): void
  (event: 'close'): void
}>()

const loading = ref(false)
const errorMessage = ref('')
const statusFilter = ref('')
const candidates = ref<CandidateJournalEntry[]>([])
const selectedId = ref('')
const updatingStatus = ref(false)
const savingThesis = ref(false)
const savingReview = ref(false)
const writingAnalysis = ref(false)

const thesisForm = ref<CandidateThesisUpdate>({
  entryReason: '',
  tradeHypothesis: '',
  entryPrerequisites: '',
  invalidationRules: '',
  humanDecision: 'watch',
  skipReason: '',
})
const reviewForm = ref<CandidateReviewUpdate>({
  reviewOutcome: 'pending',
  modelResult: 'unknown',
  executionResult: 'unknown',
  reviewNotes: '',
})

const selectedEntry = computed(() =>
  candidates.value.find((entry) => entry.id === selectedId.value) || null,
)
const candidateReviews = computed(() => candidates.value.map((entry) => candidateJournalService.reanalyzeCandidate(entry)))
const selectedReview = computed(() => {
  const review = candidateReviews.value.find((item) => item.entry.id === selectedId.value)
  return review || (selectedEntry.value ? candidateJournalService.reanalyzeCandidate(selectedEntry.value) : null)
})
const candidateStats = computed(() => {
  const reviews = candidateReviews.value
  const today = new Date().toISOString().slice(0, 10)
  const totalScore = reviews.reduce((sum, item) => sum + item.currentAnalysis.score, 0)
  const triggeredCount = candidates.value.filter((entry) =>
    ['triggered', 'tracking', 'reviewed'].includes(entry.status),
  ).length
  const reviewedEntries = candidates.value.filter((entry) => entry.status === 'reviewed')
  const failedCount = reviewedEntries.filter((entry) =>
    ['failed', 'not_triggered'].includes(entry.reviewOutcome),
  ).length
  const successCount = reviewedEntries.filter((entry) =>
    ['success', 'partial'].includes(entry.reviewOutcome),
  ).length
  return {
    todayNew: candidates.value.filter((entry) => entry.createdAt.slice(0, 10) === today).length,
    openCount: candidates.value.filter((entry) => ['observe', 'candidate'].includes(entry.status)).length,
    activeCount: candidates.value.filter((entry) => ['triggered', 'tracking'].includes(entry.status)).length,
    pendingReview: candidates.value.filter((entry) => entry.status !== 'reviewed').length,
    averageScore: reviews.length ? Math.round(totalScore / reviews.length) : 0,
    riskCount: reviews.filter((item) => item.currentAnalysis.riskWarnings.length > 0).length,
    triggerRate: formatPercent(triggeredCount, candidates.value.length),
    failureRate: formatPercent(failedCount, reviewedEntries.length),
    reviewWinRate: formatPercent(successCount, reviewedEntries.length),
  }
})

const nextStatuses: CandidateStatus[] = ['observe', 'candidate', 'triggered', 'tracking', 'reviewed']

function close() {
  emit('update:visible', false)
  emit('close')
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    observe: '观察',
    candidate: '候选',
    triggered: '触发',
    tracking: '跟踪中',
    reviewed: '已复盘',
  }
  return labels[status] || status || '未设置'
}

function reviewOf(entry: CandidateJournalEntry): CandidateWorkbenchReview {
  return candidateReviews.value.find((item) => item.entry.id === entry.id) || candidateJournalService.reanalyzeCandidate(entry)
}

function formatDelta(delta: number) {
  if (delta > 0) return `+${delta}`
  return String(delta)
}

function deltaClass(delta: number) {
  if (delta > 0) return 'delta-up'
  if (delta < 0) return 'delta-down'
  return 'delta-flat'
}

function formatPercent(value: number, total: number) {
  if (!total) return '0%'
  return `${Math.round((value / total) * 100)}%`
}

function applySelectedEntryToForms(entry: CandidateJournalEntry | null) {
  thesisForm.value = {
    entryReason: entry?.entryReason || '',
    tradeHypothesis: entry?.tradeHypothesis || '',
    entryPrerequisites: entry?.entryPrerequisites || '',
    invalidationRules: entry?.invalidationRules || '',
    humanDecision: entry?.humanDecision || 'watch',
    skipReason: entry?.skipReason || '',
  }
  reviewForm.value = {
    reviewOutcome: entry?.reviewOutcome || 'pending',
    modelResult: entry?.modelResult || 'unknown',
    executionResult: entry?.executionResult || 'unknown',
    reviewNotes: entry?.reviewNotes || '',
  }
}

function replaceCandidate(updated: CandidateJournalEntry) {
  candidates.value = candidates.value.map((entry) => (entry.id === updated.id ? updated : entry))
  selectedId.value = updated.id
  applySelectedEntryToForms(updated)
}

async function loadCandidates() {
  loading.value = true
  errorMessage.value = ''
  try {
    const status = statusFilter.value === 'pending-review' ? undefined : statusFilter.value || undefined
    candidates.value = await candidateJournalService.listCandidates({
      status,
      limit: 100,
    })
    if (statusFilter.value === 'pending-review') {
      candidates.value = candidates.value.filter((entry) => entry.status !== 'reviewed')
    }
    if (!selectedId.value || !candidates.value.some((entry) => entry.id === selectedId.value)) {
      selectedId.value = candidates.value[0]?.id || ''
    }
    applySelectedEntryToForms(selectedEntry.value)
  } catch (error) {
    errorMessage.value = `候选池加载失败：${error instanceof Error ? error.message : '未知错误'}`
    candidates.value = []
    selectedId.value = ''
    applySelectedEntryToForms(null)
  } finally {
    loading.value = false
  }
}

function selectCandidate(target: { candidateId?: string; stockCode?: string } = {}) {
  const targetCode = String(target.stockCode || '').replace(/\D/g, '').padStart(6, '0').slice(-6)
  const matched = candidates.value.find((entry) => {
    if (target.candidateId && entry.id === target.candidateId) return true
    return !!targetCode && entry.stockCode === targetCode
  })
  if (matched) {
    selectedId.value = matched.id
    return true
  }
  return false
}

async function openCandidate(target: { candidateId?: string; stockCode?: string } = {}) {
  const hasTarget = !!(target.candidateId || target.stockCode)
  if (hasTarget && statusFilter.value) {
    statusFilter.value = ''
    await loadCandidates()
  } else if (!candidates.value.length) {
    await loadCandidates()
  }
  const matched = selectCandidate(target)
  if (hasTarget && !matched) {
    await loadCandidates()
    selectCandidate(target)
  }
}

async function updateStatus(status: CandidateStatus) {
  if (!selectedEntry.value) return
  updatingStatus.value = true
  errorMessage.value = ''
  try {
    const updated = await candidateJournalService.updateCandidateStatus(selectedEntry.value.id, status)
    replaceCandidate(updated)
  } catch (error) {
    errorMessage.value = `候选状态更新失败：${error instanceof Error ? error.message : '未知错误'}`
  } finally {
    updatingStatus.value = false
  }
}

async function saveThesis() {
  if (!selectedEntry.value) return
  savingThesis.value = true
  errorMessage.value = ''
  try {
    const updated = await candidateJournalService.updateCandidateThesis(selectedEntry.value.id, thesisForm.value)
    replaceCandidate(updated)
  } catch (error) {
    errorMessage.value = `候选假设保存失败：${error instanceof Error ? error.message : '未知错误'}`
  } finally {
    savingThesis.value = false
  }
}

async function writeBackAnalysis() {
  if (!selectedEntry.value) return
  writingAnalysis.value = true
  errorMessage.value = ''
  try {
    const updated = await candidateJournalService.writeBackCurrentAnalysis(selectedEntry.value)
    replaceCandidate(updated)
  } catch (error) {
    errorMessage.value = `当前分析写回失败：${error instanceof Error ? error.message : '未知错误'}`
  } finally {
    writingAnalysis.value = false
  }
}

async function saveReview() {
  if (!selectedEntry.value) return
  savingReview.value = true
  errorMessage.value = ''
  try {
    const updated = await candidateJournalService.saveCandidateReview(selectedEntry.value.id, reviewForm.value)
    replaceCandidate(updated)
  } catch (error) {
    errorMessage.value = `候选复盘保存失败：${error instanceof Error ? error.message : '未知错误'}`
  } finally {
    savingReview.value = false
  }
}

onMounted(() => {
  if (props.visible) void loadCandidates()
})

watch(
  () => props.visible,
  (visible) => {
    if (visible) void loadCandidates()
  },
)

watch(selectedEntry, (entry) => {
  applySelectedEntryToForms(entry)
})

defineExpose({
  openCandidate,
})
</script>

<style scoped>
.candidate-mask {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.45);
}

.candidate-panel {
  display: flex;
  flex-direction: column;
  width: min(1180px, calc(100vw - 32px));
  height: min(760px, calc(100vh - 48px));
  overflow: hidden;
  color: var(--text-primary);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: var(--shadow-lg);
}

.candidate-header,
.candidate-toolbar,
.stats-row,
.detail-title,
.score-row,
.stock-line,
.meta-line,
.status-actions,
.breakdown,
.section-header,
.inline-form {
  display: flex;
  align-items: center;
}

.candidate-header {
  justify-content: space-between;
  padding: 16px 18px;
  border-bottom: 1px solid var(--border-color);
}

.candidate-header h2,
.detail-title h3 {
  margin: 0;
  font-size: 18px;
}

.candidate-header p,
.detail-title span {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.icon-btn,
.text-btn,
.status-actions button,
.candidate-item {
  color: var(--text-primary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  cursor: pointer;
}

.icon-btn {
  width: 32px;
  height: 32px;
  font-size: 18px;
}

.candidate-toolbar {
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-color);
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-color);
}

.stat-card {
  min-width: 0;
  padding: 8px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 7px;
}

.stat-card span {
  display: block;
  color: var(--text-secondary);
  font-size: 11px;
}

.stat-card strong {
  display: block;
  margin-top: 4px;
  color: var(--text-title);
  font-size: 18px;
}

.risk-card strong {
  color: #f59e0b;
}

.candidate-toolbar select,
.text-btn,
.status-actions button {
  height: 30px;
  padding: 0 10px;
}

.summary {
  margin-left: auto;
  color: var(--text-secondary);
  font-size: 12px;
}

.error {
  margin: 10px 14px 0;
  padding: 8px 10px;
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 6px;
  font-size: 12px;
}

.candidate-body {
  display: grid;
  grid-template-columns: 360px 1fr;
  min-height: 0;
  flex: 1;
}

.candidate-list {
  overflow-y: auto;
  border-right: 1px solid var(--border-color);
}

.candidate-item {
  display: block;
  width: 100%;
  padding: 12px 14px;
  border: 0;
  border-bottom: 1px solid var(--border-color);
  border-radius: 0;
  text-align: left;
}

.candidate-item.active {
  background: rgba(255, 165, 2, 0.16);
}

.stock-line,
.meta-line,
.score-row,
.breakdown {
  justify-content: space-between;
  gap: 8px;
}

.stock-line span,
.meta-line {
  color: var(--text-secondary);
  font-size: 12px;
}

.candidate-detail {
  overflow-y: auto;
  padding: 16px 18px 22px;
}

.detail-title {
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.status-actions {
  flex-wrap: wrap;
  gap: 6px;
}

.section-header {
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

section {
  margin: 0 0 14px;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
}

section h4 {
  margin: 0;
  color: var(--text-title);
  font-size: 13px;
}

section p,
section li {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.65;
}

ul {
  margin: 0;
  padding-left: 18px;
}

.score-row strong,
.analysis-compare strong {
  color: var(--color-highlight);
  font-size: 22px;
}

.analysis-compare {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.analysis-compare div {
  padding: 8px 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 7px;
}

.analysis-compare span {
  display: block;
  color: var(--text-secondary);
  font-size: 11px;
}

.analysis-compare strong {
  display: block;
  margin-top: 4px;
}

.breakdown {
  flex-wrap: wrap;
  justify-content: flex-start;
  margin-top: 8px;
}

.breakdown span {
  padding: 3px 7px;
  color: var(--text-secondary);
  background: var(--bg-primary);
  border-radius: 5px;
  font-size: 12px;
}

.state-reasons {
  margin-top: 10px;
}

.form-grid {
  display: grid;
  gap: 10px;
}

.thesis-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.review-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.inline-form {
  align-items: flex-start;
  gap: 10px;
  margin-top: 10px;
}

.inline-form label:first-child {
  width: 140px;
}

.inline-form label:last-child {
  flex: 1;
}

label {
  min-width: 0;
}

label span,
.full-field span {
  display: block;
  margin-bottom: 4px;
  color: var(--text-secondary);
  font-size: 12px;
}

textarea,
select,
input {
  width: 100%;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 13px;
}

textarea,
input {
  padding: 7px 8px;
}

textarea {
  resize: vertical;
  line-height: 1.5;
}

select {
  height: 32px;
  padding: 0 8px;
}

.full-field {
  display: block;
  margin-top: 10px;
}

.delta-up {
  color: #ff4757 !important;
}

.delta-down {
  color: #2ed573 !important;
}

.delta-flat {
  color: var(--text-secondary) !important;
}

.empty {
  padding: 24px;
  color: var(--text-tertiary);
  text-align: center;
}

.detail-empty {
  margin-top: 180px;
}
</style>
