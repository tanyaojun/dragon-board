<template>
  <Teleport to="body">
    <div v-if="visible" class="candidate-mask" @click.self="close">
      <section class="candidate-panel">
        <header class="candidate-header">
          <div class="candidate-title">
            <h2>候选池</h2>
            <p>规则分析驱动的候选股跟踪工作台</p>
          </div>
          <button class="icon-btn" title="关闭" aria-label="关闭候选池" @click="close">×</button>
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
          <select v-model="sortMode" title="评分排序">
            <option value="updated-desc">按更新时间</option>
            <option value="score-desc">评分排序</option>
            <option value="grade-asc">按等级</option>
          </select>
          <select v-model="riskFilter" title="风险筛选">
            <option value="">风险筛选</option>
            <option value="risk">仅看有风险</option>
            <option value="safe">仅看无风险</option>
          </select>
          <input v-model.trim="themeFilter" class="theme-filter" placeholder="题材筛选" />
          <span class="summary">共 {{ visibleCandidates.length }} / {{ candidates.length }} 条</span>
        </div>

        <div class="stats-row">
          <div class="stat-card">
            <span>今日新增</span>
            <strong>{{ candidateStats.todayNew }}</strong>
          </div>
          <div class="stat-card">
            <span>总候选</span>
            <strong>{{ qualityStats.total }}</strong>
          </div>
          <div class="stat-card">
            <span title="复盘胜率">命中率</span>
            <strong>{{ formatMetricPercent(qualityStats.metrics.hitRate) }}</strong>
          </div>
          <div class="stat-card">
            <span>失效率</span>
            <strong>{{ formatMetricPercent(qualityStats.metrics.failureRate) }}</strong>
          </div>
          <div class="stat-card">
            <span>平均评分</span>
            <strong>{{ qualityStats.metrics.averageScore }}</strong>
          </div>
          <div class="stat-card">
            <span>平均跟踪</span>
            <strong>{{ formatDays(qualityStats.metrics.averageFollowDays) }}</strong>
          </div>
          <div class="stat-card risk-card">
            <span>当前风险</span>
            <strong>{{ qualityStats.metrics.riskCount }}</strong>
          </div>
          <div class="stat-card">
            <span>触发率</span>
            <strong>{{ formatMetricPercent(qualityStats.metrics.triggerRate) }}</strong>
          </div>
          <div class="stat-card">
            <span>待复盘</span>
            <strong>{{ qualityStats.metrics.pendingReview }}</strong>
          </div>
        </div>

        <div v-if="errorMessage" class="error">{{ errorMessage }}</div>

        <div class="candidate-body">
          <aside class="candidate-list">
            <div v-if="loading" class="empty">加载中...</div>
            <div v-else-if="!visibleCandidates.length" class="empty">暂无候选股</div>
            <button v-for="entry in visibleCandidates" v-else :key="entry.id" class="candidate-item"
              :class="{ active: selectedId === entry.id }" @click="selectedId = entry.id">
              <span class="candidate-item-main">
                <span class="candidate-name">
                  <strong>{{ entry.stockName || entry.stockCode }}</strong>
                  <span>{{ entry.stockCode }}</span>
                </span>
                <span class="candidate-score">
                  {{ reviewOf(entry).currentAnalysis.grade }}级 · {{ reviewOf(entry).currentAnalysis.score }}分
                </span>
              </span>
              <span class="candidate-item-meta">
                <span class="candidate-status">{{ statusLabel(entry.status) }}</span>
                <span>{{ reviewOf(entry).stateLabel }}</span>
              </span>
              <span class="candidate-item-foot">
                <span>{{ candidateThemeText(entry) || '暂无题材' }}</span>
                <span :class="deltaClass(reviewOf(entry).scoreDelta)">
                  {{ formatDelta(reviewOf(entry).scoreDelta) }}
                </span>
              </span>
            </button>
          </aside>

          <main class="candidate-detail">
            <div class="candidate-workbench-layout">
              <div class="candidate-workflow">
                <template v-if="selectedEntry && selectedReview">
                  <div class="detail-title">
                    <div>
                      <h3>{{ selectedEntry.stockName || selectedEntry.stockCode }}</h3>
                      <span>{{ selectedEntry.stockCode }} · {{ statusLabel(selectedEntry.status) }}</span>
                    </div>
                    <div class="quick-actions">
                      <button type="button" @click="addToFavorites">加入自选</button>
                      <button type="button" @click="openStockDetail">股票详情</button>
                      <button type="button" @click="openRankTrend">排名趋势</button>
                      <button type="button" class="danger-btn" :disabled="deletingCandidate" @click="deleteCandidate">
                        删除候选
                      </button>
                    </div>
                  </div>

                  <section class="decision-card">
                    <div class="section-header">
                      <h4>当前决策</h4>
                      <span>先判断是否继续跟踪，再推进状态</span>
                    </div>
                    <div class="analysis-compare decision-metrics">
                      <div>
                        <span>当前重分析</span>
                        <strong>{{ selectedReview.currentAnalysis.grade }}级 · {{ selectedReview.currentAnalysis.score
                          }}分</strong>
                      </div>
                      <div>
                        <span>入池快照</span>
                        <strong>{{ selectedReview.savedAnalysis.grade }}级 · {{ selectedReview.savedAnalysis.score
                          }}分</strong>
                      </div>
                      <div>
                        <span>{{ selectedReview.stateLabel }}</span>
                        <strong :class="deltaClass(selectedReview.scoreDelta)">
                          {{ formatDelta(selectedReview.scoreDelta) }}
                        </strong>
                      </div>
                    </div>
                    <div class="decision-strip">
                      <div>
                        <span class="decision-label">主要风险</span>
                        <p>
                          {{
                            selectedReview.currentAnalysis.riskWarnings[0] ||
                            selectedReview.currentAnalysis.structuredRisks[0]?.message ||
                            '暂无明确风险'
                          }}
                        </p>
                      </div>
                      <div class="status-actions">
                        <button v-for="status in nextStatuses" :key="status" :disabled="updatingStatus"
                          @click="updateStatus(status)">
                          {{ statusLabel(status) }}
                        </button>
                      </div>
                    </div>
                    <ul class="state-reasons">
                      <li v-for="reason in selectedReview.stateReasons" :key="reason">{{ reason }}</li>
                    </ul>
                  </section>

                  <section class="analysis-card">
                    <div class="section-header">
                      <h4>规则分析</h4>
                      <button class="text-btn" :disabled="writingAnalysis" @click="writeBackAnalysis">
                        写回当前分析
                      </button>
                    </div>
                    <div class="breakdown">
                      <span>RankTrend {{ formatScoreValue(selectedReview.currentAnalysis.scoreBreakdown.rankTrend)
                        }}</span>
                      <span>题材 {{ formatScoreValue(selectedReview.currentAnalysis.scoreBreakdown.theme) }}</span>
                      <span>龙头 {{ formatScoreValue(selectedReview.currentAnalysis.scoreBreakdown.dragon) }}</span>
                      <span>情绪 {{ formatScoreValue(selectedReview.currentAnalysis.scoreBreakdown.sentiment) }}</span>
                      <span>资金 {{ formatScoreValue(selectedReview.currentAnalysis.scoreBreakdown.moneyFlow) }}</span>
                    </div>
                    <div class="evidence-grid">
                      <div>
                        <h5>证据项</h5>
                        <div v-if="selectedReview.currentAnalysis.evidence.length" class="evidence-list">
                          <div v-for="item in selectedReview.currentAnalysis.evidence"
                            :key="`evidence-${item.dimension}-${item.title}`" class="evidence-item"
                            :class="`evidence-${item.kind}`">
                            <span>
                              <strong>{{ item.title }}</strong>
                              <em>{{ formatScoreImpact(item.scoreImpact) }}</em>
                            </span>
                            <small>{{ item.detail }}</small>
                          </div>
                        </div>
                        <p v-else>暂无证据项</p>
                      </div>
                      <div>
                        <h5>扣分项</h5>
                        <div v-if="selectedReview.currentAnalysis.penalties.length" class="evidence-list">
                          <div v-for="item in selectedReview.currentAnalysis.penalties"
                            :key="`penalty-${item.dimension}-${item.title}`" class="evidence-item"
                            :class="`evidence-${item.kind}`">
                            <span>
                              <strong>{{ item.title }}</strong>
                              <em>{{ formatScoreImpact(item.scoreImpact) }}</em>
                            </span>
                            <small>{{ item.detail }}</small>
                          </div>
                        </div>
                        <p v-else>暂无扣分项</p>
                      </div>
                    </div>
                    <div class="condition-grid">
                      <h5>结构化条件</h5>
                      <div class="condition-columns">
                        <div>
                          <span class="condition-title">触发条件</span>
                          <span v-for="item in selectedReview.currentAnalysis.structuredThesis.triggerConditions"
                            :key="`trigger-${item.id}`" class="condition-pill" :class="`condition-${item.status}`">
                            {{ item.label }} · {{ conditionStatusText(item.status) }}
                          </span>
                        </div>
                        <div>
                          <span class="condition-title">买入前提</span>
                          <span v-for="item in selectedReview.currentAnalysis.structuredThesis.entryPrerequisites"
                            :key="`entry-${item.id}`" class="condition-pill" :class="`condition-${item.status}`">
                            {{ item.label }} · {{ conditionStatusText(item.status) }}
                          </span>
                        </div>
                        <div>
                          <span class="condition-title">失效条件</span>
                          <span v-for="item in selectedReview.currentAnalysis.structuredThesis.invalidationConditions"
                            :key="`invalid-${item.id}`" class="condition-pill" :class="`condition-${item.status}`">
                            {{ item.label }} · {{ conditionStatusText(item.status) }}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div v-if="selectedReview.currentAnalysis.structuredRisks.length" class="structured-risk-list">
                      <h5>结构化风险</h5>
                      <span v-for="item in selectedReview.currentAnalysis.structuredRisks" :key="item.code"
                        class="risk-chip" :class="`risk-${item.level}`">
                        {{ riskLevelText(item.level) }} · {{ item.message }}
                      </span>
                    </div>
                    <div v-if="selectedReview.currentAnalysis.riskWarnings.length" class="risk-warning-list">
                      <h5>风险提示</h5>
                      <ul>
                        <li v-for="risk in selectedReview.currentAnalysis.riskWarnings" :key="risk">{{ risk }}</li>
                      </ul>
                    </div>
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
                  <div class="execution-record">
                    <div class="section-header">
                      <h4>执行记录</h4>
                      <span>实际成交详情，用于回测对齐</span>
                    </div>
                    <div class="form-grid exec-grid">
                      <label>
                        <span>买入价</span>
                        <input v-model.number="execForm.entryPrice" type="number" step="0.01" placeholder="12.50" />
                      </label>
                      <label>
                        <span>买入时间</span>
                        <input v-model="execForm.entryTime" type="datetime-local" />
                      </label>
                      <label>
                        <span>卖出价</span>
                        <input v-model.number="execForm.exitPrice" type="number" step="0.01" placeholder="13.20" />
                      </label>
                      <label>
                        <span>卖出时间</span>
                        <input v-model="execForm.exitTime" type="datetime-local" />
                      </label>
                      <label>
                        <span>止损线</span>
                        <input v-model.number="execForm.stopLossPrice" type="number" step="0.01" placeholder="11.70" />
                      </label>
                      <label>
                        <span>止盈线</span>
                        <input v-model.number="execForm.takeProfitPrice" type="number" step="0.01" placeholder="14.50" />
                      </label>
                      <label>
                        <span>仓位占比</span>
                        <input v-model.number="execForm.positionPct" type="number" step="0.01" min="0" max="1" placeholder="0.20" />
                      </label>
                    </div>
                  </div>
                  </section>
                </template>
                <div v-else class="empty detail-empty">选择一条候选股查看分析详情</div>
              </div>

              <aside class="candidate-side-brief">
                <section class="discovery-dashboard">
                  <div class="section-header">
                    <h4>建议入池</h4>
                    <div class="section-actions">
                      <span>人工确认后入池</span>
                      <button class="text-btn" :disabled="discovering" @click="refreshDiscovery(true)">
                        刷新建议
                      </button>
                    </div>
                  </div>
                  <div v-if="discoveryRecommendations.length" class="discovery-list">
                    <article v-for="item in discoveryRecommendations" :key="item.stock.code" class="discovery-item"
                      :class="{ duplicate: item.duplicate.isOpen }">
                      <div class="discovery-main">
                        <strong>{{ item.stock.name || item.stock.code }}</strong>
                        <span>{{ item.stock.code }} · {{ item.grade }}级 · {{ item.score }}分</span>
                      </div>
                      <div class="discovery-meta">
                        <span>预期跟踪 {{ item.expectedTrackingDays }}天</span>
                        <span v-if="item.duplicate.isOpen">
                          重复候选 · {{ statusLabel(item.duplicate.status || '') }}
                        </span>
                        <span v-else>可确认入池</span>
                      </div>
                      <p>{{ item.reasons[0] || '规则评分达到候选观察线' }}</p>
                      <p v-if="item.risks.length" class="discovery-risk">{{ item.risks[0] }}</p>
                      <button type="button"
                        :disabled="item.duplicate.isOpen || confirmingDiscoveryCode === item.stock.code"
                        @click="confirmDiscoveryRecommendation(item)">
                        {{ item.duplicate.isOpen ? '已在候选池' : '确认入池' }}
                      </button>
                    </article>
                  </div>
                  <p v-else class="discovery-empty">
                    {{
                      discoveryResult?.skippedReason === 'empty'
                        ? '当前行情样本为空，暂无建议。'
                        : '暂无建议，点击刷新建议重新扫描当前行情列表。'
                    }}
                  </p>
                </section>

                <section class="quality-dashboard">
                  <div class="section-header">
                    <h4>候选质量</h4>
                    <span>候选研究，不含交易盈亏</span>
                  </div>
                  <div class="quality-compact">
                    <div class="quality-block quality-block-primary">
                      <span class="quality-label">候选漏斗</span>
                      <p>
                        观察 {{ qualityStats.funnel.observe }} 候选 {{ qualityStats.funnel.candidate }} 触发
                        {{ qualityStats.funnel.triggered }} 跟踪 {{ qualityStats.funnel.tracking }} 已复盘
                        {{ qualityStats.funnel.reviewed }}
                      </p>
                      <p>
                        成功 {{ qualityStats.funnel.success }} 失败 {{ qualityStats.funnel.failed }} 未触发
                        {{ qualityStats.funnel.notTriggered }}
                      </p>
                    </div>
                    <div class="quality-block">
                      <span class="quality-label">质量拆解</span>
                      <p>
                        题材 {{ qualitySummary.themes }} / RankTrend {{ qualitySummary.rankTrend }} / 等级
                        {{ qualitySummary.grades }} / 资金 {{ qualitySummary.moneyFlow }}
                      </p>
                    </div>
                    <div class="quality-block">
                      <span class="quality-label">复盘结果</span>
                      <p>
                        <span v-for="item in qualityStats.reviewOutcomeSegments" :key="item.key">
                          {{ item.label }} {{ item.total }}
                        </span>
                      </p>
                    </div>
                  </div>
                </section>
              </aside>
            </div>
          </main>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { candidateDiscoveryService } from '@/services/candidate/CandidateDiscoveryService'
import { candidateJournalService } from '@/services/candidate/CandidateJournalService'
import { buildCandidateQualityStats } from '@/services/candidate/CandidateQualityStatsService'
import type { CandidateQualitySegment } from '@/services/candidate/CandidateQualityStatsService'
import type {
  CandidateDiscoveryRecommendation,
  CandidateDiscoveryResult,
  CandidateJournalEntry,
  CandidateReviewUpdate,
  CandidateStatus,
  CandidateThesisUpdate,
  CandidateWorkbenchReview,
  TradeExecutionFields,
} from '@/services/candidate/types'
import { AppEvents } from '@/types'
import { EventManager } from '@/utils/eventManager'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  (event: 'update:visible', value: boolean): void
  (event: 'close'): void
}>()

const loading = ref(false)
const errorMessage = ref('')
const statusFilter = ref('')
const sortMode = ref<'updated-desc' | 'score-desc' | 'grade-asc'>('updated-desc')
const riskFilter = ref('')
const themeFilter = ref('')
const candidates = ref<CandidateJournalEntry[]>([])
const selectedId = ref('')
const updatingStatus = ref(false)
const savingThesis = ref(false)
const savingReview = ref(false)
const writingAnalysis = ref(false)
const deletingCandidate = ref(false)
const discovering = ref(false)
const confirmingDiscoveryCode = ref('')
const discoveryResult = ref<CandidateDiscoveryResult | null>(null)

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
const execForm = ref<TradeExecutionFields>({
  entryPrice: undefined,
  entryTime: '',
  exitPrice: undefined,
  exitTime: '',
  stopLossPrice: undefined,
  takeProfitPrice: undefined,
  positionPct: undefined,
})

const visibleCandidates = computed(() => {
  const list = candidates.value
    .filter((entry) => {
      if (!riskFilter.value) return true
      const review = candidateJournalService.reanalyzeCandidate(entry)
      const hasRisk = review.currentAnalysis.riskWarnings.length > 0
      return riskFilter.value === 'risk' ? hasRisk : !hasRisk
    })
    .filter((entry) => {
      if (!themeFilter.value) return true
      return candidateThemeText(entry).includes(themeFilter.value)
    })

  return [...list].sort((left, right) => {
    if (sortMode.value === 'score-desc') {
      return reviewOf(right).currentAnalysis.score - reviewOf(left).currentAnalysis.score
    }
    if (sortMode.value === 'grade-asc') {
      return gradeRank(reviewOf(left).currentAnalysis.grade) - gradeRank(reviewOf(right).currentAnalysis.grade)
    }
    return Date.parse(right.updatedAt || right.createdAt) - Date.parse(left.updatedAt || left.createdAt)
  })
})
const selectedEntry = computed(() =>
  candidates.value.find((entry) => entry.id === selectedId.value) || null,
)
const candidateReviews = computed(() => candidates.value.map((entry) => candidateJournalService.reanalyzeCandidate(entry)))
const selectedReview = computed(() => {
  const review = candidateReviews.value.find((item) => item.entry.id === selectedId.value)
  return review || (selectedEntry.value ? candidateJournalService.reanalyzeCandidate(selectedEntry.value) : null)
})
const qualityStats = computed(() => buildCandidateQualityStats(candidateReviews.value))
const candidateStats = computed(() => {
  const today = new Date().toISOString().slice(0, 10)
  return {
    todayNew: candidates.value.filter((entry) => entry.createdAt.slice(0, 10) === today).length,
  }
})
const qualitySummary = computed(() => ({
  themes: segmentSummary(qualityStats.value.breakdowns.themes, 'label'),
  rankTrend: segmentSummary(qualityStats.value.breakdowns.rankTrendTiers, 'label'),
  grades: segmentSummary(qualityStats.value.breakdowns.grades, 'label', '级'),
  moneyFlow: segmentSummary(qualityStats.value.breakdowns.moneyFlowStates, 'label'),
}))
const discoveryRecommendations = computed(() => discoveryResult.value?.recommendations || [])

const nextStatuses: CandidateStatus[] = ['observe', 'candidate', 'triggered', 'tracking', 'reviewed']
const gradeOrder: Record<string, number> = { A: 1, B: 2, C: 3, D: 4 }

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

function gradeRank(grade: string) {
  return gradeOrder[grade] || 99
}

function candidateThemeText(entry: CandidateJournalEntry) {
  const review = reviewOf(entry)
  return [
    ...entry.reviewTags,
    review.currentAnalysis.signalsSnapshot?.theme?.primaryTheme,
    review.savedAnalysis.grade,
  ]
    .filter(Boolean)
    .join(' ')
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

function formatMetricPercent(value: number) {
  return `${value}%`
}

function formatDays(value: number) {
  return `${value}天`
}

function toRoundedScore(value: number) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? Math.round(numeric) : 0
}

function formatScoreValue(value: number) {
  return String(toRoundedScore(value))
}

function formatScoreImpact(value: number) {
  const score = toRoundedScore(value)
  if (score > 0) return `+${score}`
  return String(score)
}

function conditionStatusText(status: string) {
  const labels: Record<string, string> = {
    met: '满足',
    watch: '观察',
    failed: '失效',
    unknown: '缺样本',
  }
  return labels[status] || status
}

function riskLevelText(level: string) {
  const labels: Record<string, string> = {
    info: '提示',
    warning: '警示',
    danger: '高危',
  }
  return labels[level] || level
}

function segmentSummary(segments: CandidateQualitySegment[], labelKey: 'label' | 'key', suffix = '') {
  const text = segments
    .slice(0, 2)
    .map((item) => `${item[labelKey]}${suffix}${item.total}`)
    .join('、')
  return text || '暂无'
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
  execForm.value = {
    entryPrice: entry?.entryPrice ?? undefined,
    entryTime: entry?.entryTime ?? '',
    exitPrice: entry?.exitPrice ?? undefined,
    exitTime: entry?.exitTime ?? '',
    stopLossPrice: entry?.stopLossPrice ?? undefined,
    takeProfitPrice: entry?.takeProfitPrice ?? undefined,
    positionPct: entry?.positionPct ?? undefined,
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
    if (!selectedId.value || !visibleCandidates.value.some((entry) => entry.id === selectedId.value)) {
      selectedId.value = visibleCandidates.value[0]?.id || ''
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

async function refreshDiscovery(force = false) {
  discovering.value = true
  errorMessage.value = ''
  try {
    discoveryResult.value = candidateDiscoveryService.discover({
      existingCandidates: candidates.value,
      limit: 6,
      minScore: 55,
      force,
    })
  } catch (error) {
    errorMessage.value = `建议入池刷新失败：${error instanceof Error ? error.message : '未知错误'}`
  } finally {
    discovering.value = false
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

async function confirmDiscoveryRecommendation(item: CandidateDiscoveryRecommendation) {
  if (item.duplicate.isOpen) return
  confirmingDiscoveryCode.value = item.stock.code
  errorMessage.value = ''
  try {
    const result = await candidateJournalService.addCandidateFromStock(item.stock)
    if (result.entry) {
      await loadCandidates()
      selectedId.value = result.entry.id
      discoveryResult.value = candidateDiscoveryService.discover({
        existingCandidates: candidates.value,
        limit: 6,
        minScore: 55,
        force: true,
      })
    }
  } catch (error) {
    errorMessage.value = `建议入池确认失败：${error instanceof Error ? error.message : '未知错误'}`
  } finally {
    confirmingDiscoveryCode.value = ''
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
    const updated = await candidateJournalService.saveCandidateReview(selectedEntry.value.id, {
      ...reviewForm.value,
      ...execForm.value,
    })
    replaceCandidate(updated)
  } catch (error) {
    errorMessage.value = `候选复盘保存失败：${error instanceof Error ? error.message : '未知错误'}`
  } finally {
    savingReview.value = false
  }
}

function addToFavorites() {
  if (!selectedEntry.value) return
  const ok = candidateJournalService.addCandidateToFavorites(selectedEntry.value)
  EventManager.emit(AppEvents.UI.TOAST, {
    message: ok ? `已加入自选：${selectedEntry.value.stockName || selectedEntry.value.stockCode}` : '加入自选失败',
    duration: 1500,
    type: ok ? 'success' : 'error',
  })
}

function openStockDetail() {
  if (!selectedEntry.value) return
  EventManager.emit('stock:show-detail', {
    code: selectedEntry.value.stockCode,
    name: selectedEntry.value.stockName,
  })
}

function openRankTrend() {
  if (!selectedEntry.value) return
  EventManager.emit('rank-trend:open', {
    stockCode: selectedEntry.value.stockCode,
    stockName: selectedEntry.value.stockName,
  })
}

async function deleteCandidate() {
  if (!selectedEntry.value) return
  if (!window.confirm(`确认删除候选：${selectedEntry.value.stockName || selectedEntry.value.stockCode}？`)) return
  deletingCandidate.value = true
  errorMessage.value = ''
  try {
    const deletedId = selectedEntry.value.id
    await candidateJournalService.deleteCandidate(selectedEntry.value)
    candidates.value = candidates.value.filter((entry) => entry.id !== deletedId)
    selectedId.value = visibleCandidates.value[0]?.id || ''
    applySelectedEntryToForms(selectedEntry.value)
    EventManager.emit(AppEvents.UI.TOAST, {
      message: '候选已删除',
      duration: 1500,
      type: 'success',
    })
  } catch (error) {
    errorMessage.value = `候选删除失败：${error instanceof Error ? error.message : '未知错误'}`
  } finally {
    deletingCandidate.value = false
  }
}

onMounted(() => {
  if (props.visible) {
    void loadCandidates().then(() => refreshDiscovery(false))
  }
})

watch(
  () => props.visible,
  (visible) => {
    if (visible) void loadCandidates().then(() => refreshDiscovery(false))
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
  padding: 24px;
  background: rgba(0, 0, 0, 0.64);
  backdrop-filter: blur(4px);
}

.candidate-panel {
  --candidate-font-ui: Inter, 'SF Pro Display', 'Segoe UI', 'Microsoft YaHei UI', sans-serif;
  --candidate-font-data: 'DIN Alternate', 'Roboto Condensed', 'Roboto Mono', 'SFMono-Regular', Consolas,
    'Microsoft YaHei UI', monospace;
  --candidate-bg: #111318;
  --candidate-rail: #0d1118;
  --candidate-surface: #1b2028;
  --candidate-surface-strong: #252c37;
  --candidate-surface-soft: rgba(37, 44, 55, 0.72);
  --candidate-text: #f4f7fb;
  --candidate-line: rgba(168, 184, 204, 0.22);
  --candidate-line-strong: rgba(212, 222, 236, 0.38);
  --candidate-accent: #ffb13b;
  --candidate-accent-soft: rgba(255, 177, 59, 0.18);
  --candidate-hot: #ff3f63;
  --candidate-green: #29d17d;
  --candidate-blue: #5eb6ff;
  --candidate-muted: #aeb8c8;
  --candidate-faint: #738093;

  display: flex;
  flex-direction: column;
  width: min(1180px, calc(100vw - 32px));
  height: min(760px, calc(100vh - 48px));
  overflow: hidden;
  color: var(--candidate-text);
  font-family: var(--candidate-font-ui);
  background:
    radial-gradient(circle at top left, rgba(255, 177, 59, 0.12), transparent 280px),
    linear-gradient(180deg, rgba(94, 182, 255, 0.045), transparent 260px),
    var(--candidate-bg);
  border: 1px solid var(--candidate-line-strong);
  border-radius: 8px;
  box-shadow:
    0 28px 80px rgba(0, 0, 0, 0.58),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.candidate-header,
.candidate-toolbar,
.stats-row,
.detail-title,
.score-row,
.candidate-item-main,
.candidate-item-meta,
.candidate-item-foot,
.quick-actions,
.status-actions,
.breakdown,
.section-header,
.inline-form {
  display: flex;
  align-items: center;
}

.candidate-header {
  justify-content: space-between;
  padding: 20px 24px 18px;
  background:
    linear-gradient(90deg, rgba(255, 177, 59, 0.18), rgba(94, 182, 255, 0.055) 52%, transparent),
    rgba(13, 17, 24, 0.84);
  border-bottom: 1px solid var(--candidate-line-strong);
}

.candidate-title {
  position: relative;
  padding-left: 14px;
}

.candidate-title::before {
  position: absolute;
  top: 2px;
  bottom: 2px;
  left: 0;
  width: 4px;
  content: '';
  background: linear-gradient(180deg, var(--candidate-accent), var(--candidate-hot));
  border-radius: 999px;
}

.candidate-header h2,
.detail-title h3 {
  margin: 0;
  color: var(--candidate-text);
  font-size: 19px;
  font-weight: 800;
  letter-spacing: 0;
}

.candidate-header p,
.detail-title span {
  margin: 4px 0 0;
  color: var(--candidate-muted);
  font-size: 12px;
}

.icon-btn,
.text-btn,
.quick-actions button,
.status-actions button,
.candidate-item {
  color: var(--candidate-text);
  background: var(--candidate-surface);
  border: 1px solid var(--candidate-line);
  border-radius: 6px;
  cursor: pointer;
  font-weight: 700;
  transition:
    border-color 160ms ease,
    background-color 160ms ease,
    box-shadow 160ms ease;
}

.icon-btn {
  width: 36px;
  height: 36px;
  font-size: 18px;
  line-height: 1;
}

.icon-btn:hover,
.text-btn:hover,
.quick-actions button:hover,
.status-actions button:hover,
.candidate-item:hover {
  background: var(--candidate-surface-strong);
  border-color: rgba(255, 177, 59, 0.52);
  box-shadow: 0 0 0 1px rgba(255, 177, 59, 0.08);
}

.icon-btn:focus-visible,
.text-btn:focus-visible,
.quick-actions button:focus-visible,
.status-actions button:focus-visible,
.candidate-item:focus-visible,
select:focus-visible,
input:focus-visible,
textarea:focus-visible {
  outline: 2px solid rgba(255, 177, 59, 0.78);
  outline-offset: 2px;
}

.candidate-toolbar {
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px 24px;
  background: rgba(13, 17, 24, 0.72);
  border-bottom: 1px solid var(--candidate-line);
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(104px, 1fr));
  gap: 8px;
  padding: 12px 24px 14px;
  border-bottom: 1px solid var(--candidate-line);
}

.stat-card {
  position: relative;
  min-width: 0;
  padding: 11px 12px 10px;
  overflow: hidden;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.015)),
    #171b22;
  border: 1px solid var(--candidate-line);
  border-radius: 7px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.055);
}

.stat-card::before {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  height: 3px;
  content: '';
  background: linear-gradient(90deg, var(--candidate-accent), rgba(94, 182, 255, 0.72), transparent);
}

.stat-card span {
  display: block;
  color: var(--candidate-muted);
  font-size: 12px;
  font-weight: 700;
}

.stat-card strong {
  display: block;
  margin-top: 4px;
  color: var(--candidate-text);
  font-family: var(--candidate-font-data);
  font-size: 22px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.risk-card strong {
  color: var(--candidate-accent);
}

.candidate-toolbar select,
.text-btn,
.quick-actions button,
.status-actions button {
  min-height: 34px;
  padding: 0 12px;
  font-size: 12px;
}

.candidate-toolbar select {
  flex: 0 1 240px;
  width: auto;
}

.candidate-toolbar .text-btn {
  flex: 0 0 auto;
}

.summary {
  margin-left: auto;
  color: var(--candidate-muted);
  font-family: var(--candidate-font-data);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.theme-filter {
  flex: 0 0 132px;
  height: 34px;
  padding: 0 10px;
}

.error {
  margin: 12px 24px 0;
  padding: 9px 12px;
  color: var(--candidate-accent);
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 6px;
  font-size: 12px;
}

.candidate-body {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  min-height: 0;
  flex: 1;
}

.candidate-list {
  overflow-y: auto;
  background: var(--candidate-rail);
  border-right: 1px solid var(--candidate-line);
}

.candidate-item {
  position: relative;
  display: grid;
  gap: 8px;
  width: 100%;
  min-height: 82px;
  padding: 13px 16px 13px 18px;
  overflow: hidden;
  border: 0;
  border-bottom: 1px solid var(--candidate-line);
  border-radius: 0;
  text-align: left;
}

.candidate-item::before {
  position: absolute;
  top: 14px;
  bottom: 14px;
  left: 0;
  width: 3px;
  content: '';
  background: transparent;
  border-radius: 0 999px 999px 0;
}

.candidate-item.active {
  background:
    linear-gradient(90deg, rgba(255, 177, 59, 0.24), rgba(94, 182, 255, 0.075) 56%, rgba(255, 255, 255, 0.025)),
    var(--candidate-surface);
  box-shadow:
    inset 0 0 0 1px rgba(255, 177, 59, 0.28),
    inset 3px 0 0 rgba(255, 177, 59, 0.65);
}

.candidate-item.active::before {
  background: linear-gradient(180deg, var(--candidate-hot), var(--candidate-accent));
}

.candidate-item-main,
.candidate-item-meta,
.candidate-item-foot,
.score-row,
.breakdown {
  justify-content: space-between;
  gap: 8px;
}

.candidate-name {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.candidate-name strong {
  overflow: hidden;
  color: var(--candidate-text);
  font-size: 15px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate-name span,
.candidate-item-meta,
.candidate-item-foot {
  color: var(--candidate-muted);
  font-size: 12.5px;
}

.candidate-score {
  flex: 0 0 auto;
  color: var(--candidate-accent);
  font-family: var(--candidate-font-data);
  font-size: 13px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

.candidate-status {
  color: var(--candidate-blue);
  font-weight: 800;
}

.candidate-item-foot {
  min-width: 0;
}

.candidate-item-foot>span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate-detail {
  overflow-y: auto;
  padding: 18px 22px 24px;
  background: #171b22;
}

.candidate-workbench-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 14px;
  align-items: start;
}

.candidate-workflow,
.candidate-side-brief {
  min-width: 0;
}

.candidate-side-brief {
  position: sticky;
  top: 0;
  display: grid;
  gap: 12px;
  align-content: start;
}

.detail-title {
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  padding: 4px 2px 0;
}

.quick-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.quick-actions .danger-btn {
  color: #ff8f8f;
  background: rgba(255, 63, 99, 0.14);
  border-color: rgba(255, 63, 99, 0.58);
}

.quick-actions button:disabled,
.status-actions button:disabled,
.text-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.status-actions {
  flex-wrap: wrap;
  gap: 8px;
}

.section-header {
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.section-header>span {
  color: var(--candidate-muted);
  font-size: 12px;
}

.section-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--candidate-muted);
  font-size: 12px;
}

.candidate-workflow>section,
.candidate-side-brief>section {
  margin: 0 0 16px;
  padding: 14px;
  background: var(--candidate-surface-soft);
  border: 1px solid var(--candidate-line);
  border-radius: 8px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.045);
}

.candidate-workflow>section h4,
.candidate-side-brief>section h4 {
  margin: 0;
  color: var(--candidate-text);
  font-size: 13px;
  font-weight: 800;
}

.candidate-workflow>section p,
.candidate-workflow>section li,
.candidate-side-brief>section p,
.candidate-side-brief>section li {
  margin: 0;
  color: var(--candidate-muted);
  font-size: 13px;
  line-height: 1.65;
}

.decision-card {
  background:
    linear-gradient(135deg, rgba(255, 177, 59, 0.16), rgba(94, 182, 255, 0.055) 58%, rgba(255, 255, 255, 0.02)),
    var(--candidate-surface-soft);
  border-color: rgba(255, 177, 59, 0.34);
}

.decision-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--candidate-line);
}

.decision-label {
  display: block;
  margin-bottom: 4px;
  color: var(--candidate-muted);
  font-size: 12px;
  font-weight: 800;
}

.quality-dashboard {
  background:
    linear-gradient(135deg, rgba(255, 177, 59, 0.18), rgba(255, 63, 99, 0.075) 46%, rgba(94, 182, 255, 0.04)),
    var(--candidate-surface-soft);
  border-color: rgba(255, 177, 59, 0.36);
}

.discovery-dashboard {
  background:
    linear-gradient(135deg, rgba(41, 209, 125, 0.12), rgba(255, 177, 59, 0.075) 48%, rgba(94, 182, 255, 0.035)),
    var(--candidate-surface-soft);
  border-color: rgba(41, 209, 125, 0.28);
}

.discovery-list {
  display: grid;
  gap: 8px;
}

.discovery-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 6px 12px;
  padding: 10px 12px;
  background: rgba(13, 17, 24, 0.76);
  border: 1px solid var(--candidate-line);
  border-radius: 7px;
}

.discovery-item.duplicate {
  opacity: 0.74;
}

.discovery-main,
.discovery-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.discovery-main strong {
  color: var(--candidate-text);
  font-size: 13px;
  font-weight: 800;
}

.discovery-main span,
.discovery-meta {
  color: var(--candidate-muted);
  font-size: 12px;
}

.discovery-item p {
  grid-column: 1;
}

.discovery-risk {
  color: #ffb142 !important;
}

.discovery-item button {
  grid-column: 1;
  justify-self: start;
  min-width: 86px;
  min-height: 32px;
  color: var(--candidate-text);
  background: rgba(255, 177, 59, 0.18);
  border: 1px solid rgba(255, 177, 59, 0.48);
  border-radius: 6px;
  cursor: pointer;
  font-weight: 800;
}

.discovery-item button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.discovery-empty {
  color: var(--candidate-muted);
}

.quality-compact {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}

.quality-block {
  min-width: 0;
  padding: 10px 12px;
  background: rgba(13, 17, 24, 0.78);
  border: 1px solid var(--candidate-line);
  border-radius: 7px;
}

.quality-block-primary {
  border-color: rgba(255, 177, 59, 0.42);
}

.quality-label {
  display: block;
  margin-bottom: 5px;
  color: var(--candidate-text);
  font-size: 12px;
  font-weight: 800;
}

.quality-compact p {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  line-height: 1.5;
}

ul {
  margin: 0;
  padding-left: 18px;
}

.score-row strong,
.analysis-compare strong {
  color: var(--candidate-accent);
  font-family: var(--candidate-font-data);
  font-size: 20px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

.analysis-compare {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.analysis-compare div {
  padding: 10px 12px;
  background: rgba(13, 17, 24, 0.82);
  border: 1px solid var(--candidate-line);
  border-radius: 7px;
}

.analysis-compare span {
  display: block;
  color: var(--candidate-muted);
  font-size: 12px;
  font-weight: 700;
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
  padding: 4px 8px;
  color: #d5e8ff;
  background: rgba(94, 182, 255, 0.12);
  border: 1px solid rgba(94, 182, 255, 0.2);
  border-radius: 5px;
  font-size: 12px;
  font-weight: 700;
}

.state-reasons {
  margin-top: 10px;
}

.evidence-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 10px;
}

.evidence-grid h5,
.condition-grid h5,
.structured-risk-list h5,
.risk-warning-list h5 {
  margin: 0 0 6px;
  color: var(--candidate-text);
  font-size: 12px;
  font-weight: 800;
}

.evidence-list,
.structured-risk-list {
  display: grid;
  gap: 6px;
}

.evidence-item {
  padding: 8px 10px;
  background: rgba(13, 17, 24, 0.76);
  border: 1px solid var(--candidate-line);
  border-radius: 6px;
}

.evidence-item span {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: var(--candidate-text);
  font-size: 12px;
  font-weight: 700;
}

.evidence-item em {
  color: var(--candidate-muted);
  font-style: normal;
}

.evidence-item small {
  display: block;
  margin-top: 3px;
  color: var(--candidate-muted);
  font-size: 12px;
  line-height: 1.45;
}

.evidence-positive {
  background: rgba(255, 63, 99, 0.09);
  border-color: rgba(255, 63, 99, 0.48);
}

.evidence-negative,
.evidence-missing {
  background: rgba(41, 209, 125, 0.08);
  border-color: rgba(41, 209, 125, 0.44);
}

.condition-grid,
.structured-risk-list,
.risk-warning-list {
  margin-top: 10px;
}

.condition-columns {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.condition-title {
  display: block;
  margin-bottom: 5px;
  color: var(--candidate-muted);
  font-size: 12px;
  font-weight: 700;
}

.condition-pill,
.risk-chip {
  display: block;
  margin-bottom: 5px;
  padding: 6px 8px;
  color: var(--candidate-muted);
  background: rgba(13, 17, 24, 0.76);
  border: 1px solid var(--candidate-line);
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.4;
}

.condition-met {
  color: #ffb142;
  border-color: rgba(255, 177, 59, 0.4);
}

.condition-failed,
.risk-danger,
.risk-warning {
  color: #ff8f8f;
  border-color: rgba(255, 63, 99, 0.42);
}

.condition-unknown,
.risk-info {
  color: var(--candidate-faint);
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
  color: var(--candidate-muted);
  font-size: 12px;
  font-weight: 700;
}

textarea,
select,
input {
  width: 100%;
  color: var(--candidate-text);
  background: #0f1319;
  border: 1px solid var(--candidate-line);
  border-radius: 6px;
  font-size: 13px;
}

textarea,
input {
  padding: 8px 10px;
}

textarea {
  resize: vertical;
  line-height: 1.5;
}

textarea::placeholder,
input::placeholder {
  color: var(--candidate-faint);
}

select {
  height: 34px;
  padding: 0 8px;
}

.full-field {
  display: block;
  margin-top: 10px;
}

.delta-up {
  color: var(--candidate-hot) !important;
}

.delta-down {
  color: var(--candidate-green) !important;
}

.delta-flat {
  color: var(--candidate-muted) !important;
}

.empty {
  padding: 24px;
  color: var(--candidate-faint);
  text-align: center;
}

.detail-empty {
  margin-top: 180px;
}

@media (max-width: 900px) {
  .candidate-mask {
    padding: 12px;
  }

  .candidate-panel {
    width: calc(100vw - 24px);
    height: calc(100vh - 24px);
  }

  .candidate-toolbar select,
  .candidate-toolbar .text-btn,
  .theme-filter {
    flex-basis: 100%;
  }

  .candidate-body {
    grid-template-columns: 1fr;
  }

  .candidate-list {
    max-height: 260px;
    border-right: 0;
    border-bottom: 1px solid var(--candidate-line);
  }

  .candidate-detail {
    padding: 16px;
  }

  .candidate-workbench-layout {
    grid-template-columns: 1fr;
  }

  .candidate-side-brief {
    position: static;
  }

  .detail-title {
    align-items: flex-start;
    flex-direction: column;
  }

  .quick-actions,
  .status-actions,
  .section-actions {
    justify-content: flex-start;
  }

  .quality-compact,
  .analysis-compare,
  .decision-strip,
  .discovery-item,
  .evidence-grid,
  .condition-columns,
  .thesis-grid,
  .review-grid {
    grid-template-columns: 1fr;
  }

  .discovery-item button,
  .discovery-item p {
    grid-column: 1;
    grid-row: auto;
  }
}

.execution-record {
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px solid var(--candidate-line);
}

.exec-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
</style>
