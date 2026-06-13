<template>
  <Teleport to="body">
    <div v-if="visible" class="candidate-mask" @click.self="close">
      <section class="candidate-panel">
        <header class="candidate-header">
          <div class="candidate-title">
            <h2>候选池</h2>
            <p>Fusion 主线策略生命周期工作台</p>
          </div>
          <button class="icon-btn" title="关闭" aria-label="关闭候选池" @click="close">×</button>
        </header>

        <div class="candidate-toolbar">
          <select v-model="statusFilter" title="策略状态">
            <option value="">全部策略状态</option>
            <option value="triggered_wait_entry">待入场</option>
            <option value="active_holding">已入场</option>
            <option value="exit_signaled">已退出待复盘</option>
            <option value="closed">已完成</option>
            <option value="idle">观察中</option>
          </select>
          <select v-model="sortMode" title="排序方式">
            <option value="state-priority">排序方式：按策略优先级</option>
            <option value="trigger-desc">排序方式：按触发时间</option>
            <option value="holding-desc">排序方式：按持有 bars</option>
          </select>
          <select v-model="pendingStrategyMode" title="待生效策略模式">
            <option value="balanced">待生效：均衡盯盘</option>
            <option value="recall_first">待生效：召回优先</option>
            <option value="strict_execution">待生效：严格执行</option>
          </select>
          <span class="mode-note">当前详情以参数快照为准，待生效设置刷新信号后应用</span>
          <input v-model.trim="keyword" class="keyword-filter" placeholder="代码 / 名称" />
          <button class="text-btn" @click="loadCandidates">刷新</button>
          <span class="summary">共 {{ visibleRows.length }} / {{ strategyRows.length }} 条</span>
        </div>

        <div v-if="errorMessage" class="error">{{ errorMessage }}</div>

        <div class="candidate-body">
          <aside class="candidate-list">
            <div v-if="loading" class="empty">加载中...</div>
            <div v-else-if="!groupedRows.length" class="empty">暂无候选股</div>
            <template v-else>
              <section v-for="group in groupedRows" :key="group.key" class="candidate-group">
                <header class="candidate-group-header">
                  <span>{{ group.label }}</span>
                  <strong>{{ group.items.length }}</strong>
                </header>
                <button
                  v-for="row in group.items"
                  :key="row.entry.id"
                  class="candidate-item"
                  :class="{ active: selectedId === row.entry.id }"
                  @click="selectedId = row.entry.id"
                >
                  <span class="candidate-item-main">
                    <span class="candidate-name">
                      <strong>{{ row.entry.stockName || row.entry.stockCode }}</strong>
                      <span>{{ row.entry.stockCode }}</span>
                    </span>
                    <span
                      class="strategy-state-pill"
                      :data-state="row.projection.strategyState"
                    >
                      {{ strategyStateLabel(row.projection.strategyState) }}
                    </span>
                  </span>
                  <span class="candidate-item-meta">
                    <span class="candidate-status">{{ row.projection.candidateTier }}</span>
                    <span>{{ lifecycleActionLabel(row.projection.lifecycleAction) }}</span>
                  </span>
                  <span class="candidate-item-foot">
                    <span>{{ row.projection.triggerAt ? formatDateTime(row.projection.triggerAt) : '未记录触发时间' }}</span>
                    <span>持有 {{ formatHoldingBars(row.projection.holdingBars) }}</span>
                  </span>
                </button>
              </section>
            </template>
          </aside>

          <main class="candidate-detail">
            <template v-if="selectedLiveDetail">
              <div class="detail-title">
                <div>
                  <h3>{{ selectedLiveDetail.entry.stockName || selectedLiveDetail.entry.stockCode }}</h3>
                  <span>
                    {{ selectedLiveDetail.entry.stockCode }} ·
                    {{ strategyStateLabel(selectedLiveDetail.projection.strategyState) }}
                  </span>
                </div>
                <div class="quick-actions">
                  <button type="button" @click="addToFavorites">加入自选</button>
                  <button type="button" @click="openStockDetail">股票详情</button>
                  <button type="button" @click="openRankTrend">排名趋势</button>
                  <button
                    v-if="!isTransientLiveDetail"
                    type="button"
                    class="danger-btn"
                    :disabled="deletingCandidate"
                    @click="deleteCandidate"
                  >
                    删除候选
                  </button>
                </div>
              </div>

              <section class="strategy-card">
                <div class="section-header">
                  <h4>策略事实</h4>
                  <span>{{ selectedLiveDetail.projection.strategyName }}</span>
                </div>
                <div class="fact-grid">
                  <div class="fact-item">
                    <span>当前策略状态</span>
                    <strong
                      class="strategy-state-pill"
                      :data-state="selectedLiveDetail.projection.strategyState"
                    >
                      {{ strategyStateLabel(selectedLiveDetail.projection.strategyState) }}
                    </strong>
                  </div>
                  <div class="fact-item">
                    <span>当前入池诊断</span>
                    <strong
                      class="strategy-state-pill"
                      :data-state="selectedEntryDecision?.decisionState || 'not_candidate'"
                    >
                      {{ currentEntryDecisionLabel }}
                    </strong>
                  </div>
                  <div class="fact-item">
                    <span>首次触发时间</span>
                    <strong>{{ formatDateTime(selectedLiveDetail.projection.triggerAt) }}</strong>
                  </div>
                  <div class="fact-item">
                    <span>入池价格</span>
                    <strong>{{ formatOptionalNumber(selectedEntrySnapshot?.price, 2) }}</strong>
                  </div>
                  <div class="fact-item">
                    <span>入池综合排名</span>
                    <strong>{{ formatOptionalNumber(selectedEntrySnapshot?.compRank, 0) }}</strong>
                  </div>
                  <div class="fact-item">
                    <span>入池涨幅 / 量比</span>
                    <strong>
                      {{ formatOptionalNumber(selectedEntrySnapshot?.change, 2) }}% /
                      {{ formatOptionalNumber(selectedEntrySnapshot?.volumeRatio, 2) }}
                    </strong>
                  </div>
                  <div class="fact-item">
                    <span>入池主力净额</span>
                    <strong>{{ formatOptionalNumber(selectedEntrySnapshot?.zlje, 2) }}</strong>
                  </div>
                  <div class="fact-item">
                    <span>策略入场时间</span>
                    <strong>{{ formatDateTime(selectedLiveDetail.projection.strategyEntryAt) }}</strong>
                  </div>
                  <div class="fact-item">
                    <span>策略退出时间</span>
                    <strong>{{ formatDateTime(selectedLiveDetail.projection.strategyExitAt) }}</strong>
                  </div>
                  <div class="fact-item">
                    <span>策略持有 bars</span>
                    <strong>{{ formatHoldingBars(selectedLiveDetail.projection.holdingBars) }}</strong>
                  </div>
                  <div class="fact-item">
                    <span>候选层级</span>
                    <strong>{{ selectedLiveDetail.projection.candidateTier }}</strong>
                  </div>
                  <div class="fact-item">
                    <span>生命周期动作</span>
                    <strong>{{ lifecycleActionLabel(selectedLiveDetail.projection.lifecycleAction) }}</strong>
                  </div>
                  <div class="fact-item">
                    <span>退出原因</span>
                    <strong>{{ selectedLiveDetail.projection.exitReason || '未触发退出原因' }}</strong>
                  </div>
                  <div class="fact-item">
                    <span>仓位槽位 / 最大持仓</span>
                    <strong>{{ formatSlotSummary(selectedLiveDetail.projection) }}</strong>
                  </div>
                  <div class="fact-item">
                    <span>快照口径</span>
                    <strong>{{ selectedLiveDetail.projection.snapshotType }}</strong>
                  </div>
                </div>
                <div v-if="selectedConfigSnapshot" class="snapshot-note">
                  当前诊断：{{ strategyModeLabel(selectedConfigSnapshot.mode) }} · {{ selectedConfigSnapshot.version }}
                </div>
                <div v-if="selectedConfigSnapshot" class="config-strip">
                  <div>
                    <span>策略模式</span>
                    <strong>{{ strategyModeLabel(selectedConfigSnapshot.mode) }}</strong>
                  </div>
                  <div>
                    <span>参数快照</span>
                    <strong>{{ selectedConfigSnapshot.version }}</strong>
                  </div>
                  <div>
                    <span>Jump阈值</span>
                    <strong>{{ selectedConfigSnapshot.minJumpConfidence }}</strong>
                  </div>
                  <div>
                    <span>涨幅规则</span>
                    <strong>{{ selectedConfigSnapshot.changeGate.mode }} / {{ selectedConfigSnapshot.changeGate.maxEntryChangePct ?? '不限' }}</strong>
                  </div>
                  <div>
                    <span>加速度阈值</span>
                    <strong>{{ selectedConfigSnapshot.accelerationMin }} / {{ selectedConfigSnapshot.accDeltaMin }}</strong>
                  </div>
                  <div>
                    <span>允许层级</span>
                    <strong>{{ formatTierList(selectedConfigSnapshot.allowedCandidateTiers) }}</strong>
                  </div>
                  <div>
                    <span>B档确认</span>
                    <strong>{{ selectedConfigSnapshot.requireTierBMidAndZeroCross ? '硬确认' : '观察降级' }}</strong>
                  </div>
                </div>
                <div v-if="selectedGateChecks.length" class="gate-matrix">
                  <div class="section-header compact">
                    <h4>规则矩阵</h4>
                    <span>{{ selectedEntryDecision?.summary || '无阻断' }}</span>
                  </div>
                  <div class="gate-table">
                    <div class="gate-row gate-head">
                      <span>规则</span>
                      <span>结果</span>
                      <span>硬阻断</span>
                      <span>当前值</span>
                      <span>要求</span>
                    </div>
                    <div
                      v-for="check in selectedGateChecks"
                      :key="check.key"
                      class="gate-row"
                      :data-status="check.status"
                    >
                      <span>{{ check.label }}</span>
                      <strong>{{ gateStatusLabel(check.status) }}</strong>
                      <span>{{ check.hardBlock ? '是' : '否' }}</span>
                      <span>{{ formatGateActual(check.actual) }}</span>
                      <span>{{ check.expected }}</span>
                    </div>
                  </div>
                </div>
                <ul class="fact-notes">
                  <li>入池理由：{{ thesisForm.entryReason || selectedLiveDetail.entry.entryReason || '未填写' }}</li>
                  <li>交易假设：{{ thesisForm.tradeHypothesis || selectedLiveDetail.entry.tradeHypothesis || '未填写' }}</li>
                  <li>失效条件：{{ thesisForm.invalidationRules || selectedLiveDetail.entry.invalidationRules || '未填写' }}</li>
                </ul>
              </section>

              <section v-if="!isTransientLiveDetail" class="execution-card">
                <div class="section-header">
                  <h4>执行事实</h4>
                  <button class="text-btn" :disabled="savingExecution" @click="saveExecution">保存执行记录</button>
                </div>
                <p class="section-copy">trade_journal 只作为 execution overlay，主状态仍以策略投影为准。</p>
                <div class="fact-grid compact-facts">
                  <div class="fact-item">
                    <span>执行记录</span>
                    <strong>{{ selectedLiveDetail.projection.executionOverlay?.executed ? '已记录' : '未记录' }}</strong>
                  </div>
                  <div class="fact-item">
                    <span>执行偏差</span>
                    <strong>{{ executionDriftLabel(selectedLiveDetail.projection) }}</strong>
                  </div>
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
              </section>

              <section v-if="!isTransientLiveDetail" class="editor-card">
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

              <section v-if="!isTransientLiveDetail" class="review-card">
                <div class="section-header">
                  <h4>对齐复盘</h4>
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
            </template>
            <div v-else class="empty detail-empty">选择左侧候选查看策略事实与执行 overlay。</div>
          </main>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { buildCandidateJournalProjection } from '@/services/candidate/CandidateProjectionBuilder'
import { candidateJournalService } from '@/services/candidate/CandidateJournalService'
import type { CandidateJournalEntry, CandidateReviewUpdate, CandidateThesisUpdate } from '@/services/candidate/types'
import type { FusionStrategyProjection, FusionStrategyState } from '@/types/fusionStrategyProjection'
import {
  RANK_TREND_LIVE_STRATEGY_CONFIG_STORAGE_KEY,
  normalizeRankTrendLiveStrategyConfig,
} from '@/config/rankTrendLiveStrategyConfig'
import { AppEvents } from '@/types'
import type { CandidatePoolOpenPayload } from '@/types/candidatePoolOpenPayload'
import type { RankTrendLiveStrategyMode } from '@/types/rankTrendLiveStrategy'
import { EventManager } from '@/utils/eventManager'

interface CandidatePoolRow {
  entry: CandidateJournalEntry
  projection: FusionStrategyProjection
  liveDecisionProjection?: FusionStrategyProjection | null
}

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  (event: 'update:visible', value: boolean): void
  (event: 'close'): void
}>()

const STRATEGY_STATE_LABELS: Record<FusionStrategyState, string> = {
  idle: '观察中',
  triggered_wait_entry: '待入场',
  active_holding: '已入场',
  exit_signaled: '已退出待复盘',
  closed: '已完成',
}

const STRATEGY_STATE_ORDER: FusionStrategyState[] = [
  'active_holding',
  'exit_signaled',
  'triggered_wait_entry',
  'closed',
  'idle',
]

const loading = ref(false)
const savingThesis = ref(false)
const savingReview = ref(false)
const savingExecution = ref(false)
const deletingCandidate = ref(false)
const errorMessage = ref('')
const candidates = ref<CandidateJournalEntry[]>([])
const selectedId = ref('')
const statusFilter = ref('')
const sortMode = ref<'state-priority' | 'trigger-desc' | 'holding-desc'>('state-priority')
const keyword = ref('')
const pendingStrategyMode = ref<RankTrendLiveStrategyMode>('balanced')
const transientRow = ref<CandidatePoolRow | null>(null)
const liveDecisionOverrides = ref<Record<string, FusionStrategyProjection>>({})

const thesisForm = ref<CandidateThesisUpdate>({
  entryReason: '',
  tradeHypothesis: '',
  entryPrerequisites: '',
  invalidationRules: '',
  humanDecision: 'watch',
  skipReason: '',
})

const reviewForm = ref<Pick<CandidateReviewUpdate, 'reviewOutcome' | 'modelResult' | 'executionResult' | 'reviewNotes'>>({
  reviewOutcome: 'pending',
  modelResult: 'unknown',
  executionResult: 'unknown',
  reviewNotes: '',
})

const execForm = ref<Pick<
  CandidateReviewUpdate,
  'entryPrice' | 'entryTime' | 'exitPrice' | 'exitTime' | 'stopLossPrice' | 'takeProfitPrice' | 'positionPct'
>>({
  entryPrice: undefined,
  entryTime: '',
  exitPrice: undefined,
  exitTime: '',
  stopLossPrice: undefined,
  takeProfitPrice: undefined,
  positionPct: undefined,
})

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function strategyStateLabel(state: FusionStrategyState): string {
  return STRATEGY_STATE_LABELS[state]
}

function gateStatusLabel(status: string): string {
  if (status === 'pass') return '通过'
  if (status === 'warn') return '观察'
  if (status === 'fail') return '阻断'
  return '关闭'
}

function strategyModeLabel(mode: string): string {
  if (mode === 'recall_first') return '召回优先'
  if (mode === 'strict_execution') return '严格执行'
  return '均衡盯盘'
}

function formatGateActual(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

function formatOptionalNumber(value: unknown, digits = 2): string {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '未记录'
  return numeric.toFixed(digits)
}

function formatTierList(value: unknown): string {
  return Array.isArray(value) && value.length ? value.join('/') : '-'
}

function lifecycleActionLabel(action: FusionStrategyProjection['lifecycleAction']): string {
  if (action === 'allow') return '允许推进'
  if (action === 'exit_watch') return '退出观察'
  if (action === 'veto') return '策略否决'
  return '谨慎观察'
}

function formatDateTime(value?: string): string {
  if (!value) return '未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatHoldingBars(value?: number): string {
  return Number.isFinite(Number(value)) ? `${Number(value)} bars` : '--'
}

function formatSlotSummary(projection: FusionStrategyProjection): string {
  if (!Number.isFinite(Number(projection.slotIndex)) || !Number.isFinite(Number(projection.maxPositions))) {
    return '未记录'
  }
  return `${Number(projection.slotIndex) + 1} / ${Number(projection.maxPositions)}`
}

function executionDriftLabel(projection: FusionStrategyProjection): string {
  const overlay = projection.executionOverlay
  if (!overlay?.executed) return '未执行'
  if (!projection.strategyEntryAt || !overlay.entryTime) return '已执行，待对齐'
  return projection.strategyEntryAt === overlay.entryTime ? '按策略执行' : '存在时点偏差'
}

function replaceCandidate(updated: CandidateJournalEntry) {
  const index = candidates.value.findIndex((entry) => entry.id === updated.id)
  if (index < 0) return
  candidates.value.splice(index, 1, updated)
}

function resolveEntrySnapshot(entry: CandidateJournalEntry): Record<string, any> | null {
  return (entry.signalsSnapshot?.entrySnapshot as Record<string, any> | undefined) || null
}

function buildTransientEntry(projection: FusionStrategyProjection): CandidateJournalEntry {
  const stockCode = normalizeCode(projection.stockCode)
  const now = projection.frameTime || new Date().toISOString()
  return {
    id: `transient:${stockCode}`,
    stockCode,
    stockName: projection.stockName || stockCode,
    status: 'observe',
    tradeType: 'watch',
    entryReason: projection.entryDecision?.summary || '',
    tradeHypothesis: '',
    entryPrerequisites: '',
    invalidationRules: '',
    humanDecision: 'watch',
    skipReason: '',
    reviewOutcome: 'pending',
    modelResult: 'unknown',
    executionResult: 'unknown',
    reviewNotes: '',
    reviewTags: [],
    signalsSnapshot: null,
    createdAt: now,
    updatedAt: now,
  }
}

function clearLiveDecisionOverrides() {
  liveDecisionOverrides.value = {}
}

function syncSelection() {
  if (!visibleRows.value.length) {
    selectedId.value = ''
    return
  }
  const exists = visibleRows.value.some((row) => row.entry.id === selectedId.value)
  if (!exists) {
    selectedId.value = visibleRows.value[0]?.entry.id || ''
  }
}

const strategyRows = computed<CandidatePoolRow[]>(() => {
  const rows = candidates.value.map((entry) => ({
    entry,
    projection: buildCandidateJournalProjection(entry),
    liveDecisionProjection:
      liveDecisionOverrides.value[entry.id] ||
      liveDecisionOverrides.value[normalizeCode(entry.stockCode)] ||
      null,
  }))
  return transientRow.value ? [transientRow.value, ...rows] : rows
})

const visibleRows = computed<CandidatePoolRow[]>(() => {
  const normalizedKeyword = keyword.value.trim().toLowerCase()

  return [...strategyRows.value]
    .filter((row) => !statusFilter.value || row.projection.strategyState === statusFilter.value)
    .filter((row) => {
      if (!normalizedKeyword) return true
      return (
        row.entry.stockCode.toLowerCase().includes(normalizedKeyword) ||
        (row.entry.stockName || '').toLowerCase().includes(normalizedKeyword)
      )
    })
    .sort((left, right) => {
      if (sortMode.value === 'trigger-desc') {
        return Date.parse(right.projection.triggerAt || right.entry.updatedAt || '') - Date.parse(left.projection.triggerAt || left.entry.updatedAt || '')
      }
      if (sortMode.value === 'holding-desc') {
        return Number(right.projection.holdingBars || -1) - Number(left.projection.holdingBars || -1)
      }
      const leftRank = STRATEGY_STATE_ORDER.indexOf(left.projection.strategyState)
      const rightRank = STRATEGY_STATE_ORDER.indexOf(right.projection.strategyState)
      if (leftRank !== rightRank) return leftRank - rightRank
      return Date.parse(right.projection.triggerAt || right.entry.updatedAt || '') - Date.parse(left.projection.triggerAt || left.entry.updatedAt || '')
    })
})

const groupedRows = computed(() =>
  STRATEGY_STATE_ORDER.map((state) => ({
    key: state,
    label: strategyStateLabel(state),
    items: visibleRows.value.filter((row) => row.projection.strategyState === state),
  })).filter((group) => group.items.length > 0),
)

const selectedRow = computed(() => visibleRows.value.find((row) => row.entry.id === selectedId.value) || null)
const selectedLiveDetail = computed(() => selectedRow.value)
const isTransientLiveDetail = computed(() => selectedLiveDetail.value?.entry.id.startsWith('transient:') || false)
const selectedEntryDecision = computed(
  () =>
    selectedLiveDetail.value?.liveDecisionProjection?.entryDecision ||
    selectedLiveDetail.value?.projection?.entryDecision ||
    null,
)
const currentEntryDecisionLabel = computed(() => selectedEntryDecision.value?.label || '未触发')
const selectedGateChecks = computed(() => selectedEntryDecision.value?.checks || [])
const selectedConfigSnapshot = computed(() => selectedEntryDecision.value?.configSnapshot || null)
const selectedEntrySnapshot = computed(() =>
  selectedLiveDetail.value ? resolveEntrySnapshot(selectedLiveDetail.value.entry) : null,
)

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
    entryPrice: entry?.entryPrice,
    entryTime: entry?.entryTime || '',
    exitPrice: entry?.exitPrice,
    exitTime: entry?.exitTime || '',
    stopLossPrice: entry?.stopLossPrice,
    takeProfitPrice: entry?.takeProfitPrice,
    positionPct: entry?.positionPct,
  }
}

async function loadCandidates() {
  loading.value = true
  errorMessage.value = ''
  clearLiveDecisionOverrides()
  try {
    candidates.value = await candidateJournalService.listCandidates({ limit: 200 })
    syncSelection()
  } catch (error) {
    errorMessage.value = `候选加载失败：${error instanceof Error ? error.message : '未知错误'}`
  } finally {
    loading.value = false
  }
}

async function saveThesis() {
  const row = selectedRow.value
  if (!row) return
  savingThesis.value = true
  errorMessage.value = ''
  try {
    const updated = await candidateJournalService.updateCandidateThesis(row.entry.id, thesisForm.value)
    replaceCandidate(updated)
    EventManager.emit(AppEvents.UI.TOAST, {
      message: '候选假设已保存',
      duration: 1500,
      type: 'success',
    })
  } catch (error) {
    errorMessage.value = `假设保存失败：${error instanceof Error ? error.message : '未知错误'}`
  } finally {
    savingThesis.value = false
  }
}

function buildReviewPayload(): CandidateReviewUpdate {
  return {
    ...reviewForm.value,
    ...execForm.value,
  }
}

async function saveExecution() {
  const row = selectedRow.value
  if (!row) return
  savingExecution.value = true
  errorMessage.value = ''
  try {
    const updated = await candidateJournalService.saveCandidateReview(row.entry.id, buildReviewPayload())
    replaceCandidate(updated)
    EventManager.emit(AppEvents.UI.TOAST, {
      message: '执行记录已保存',
      duration: 1500,
      type: 'success',
    })
  } catch (error) {
    errorMessage.value = `执行记录保存失败：${error instanceof Error ? error.message : '未知错误'}`
  } finally {
    savingExecution.value = false
  }
}

async function saveReview() {
  const row = selectedRow.value
  if (!row) return
  savingReview.value = true
  errorMessage.value = ''
  try {
    const updated = await candidateJournalService.saveCandidateReview(row.entry.id, buildReviewPayload())
    replaceCandidate(updated)
    EventManager.emit(AppEvents.UI.TOAST, {
      message: '对齐复盘已保存',
      duration: 1500,
      type: 'success',
    })
  } catch (error) {
    errorMessage.value = `复盘保存失败：${error instanceof Error ? error.message : '未知错误'}`
  } finally {
    savingReview.value = false
  }
}

function addToFavorites() {
  const row = selectedRow.value
  if (!row) return
  const ok = candidateJournalService.addCandidateToFavorites(row.entry)
  EventManager.emit(AppEvents.UI.TOAST, {
    message: ok ? '已加入自选' : '加入自选失败',
    duration: 1400,
    type: ok ? 'success' : 'warning',
  })
}

function openStockDetail() {
  const row = selectedRow.value
  if (!row) return
  EventManager.emit('stock:show-detail', {
    code: row.entry.stockCode,
    name: row.entry.stockName,
  })
}

function openRankTrend() {
  const row = selectedRow.value
  if (!row) return
  EventManager.emit('rank-trend:open', {
    stockCode: row.entry.stockCode,
  })
}

async function deleteCandidate() {
  const row = selectedRow.value
  if (!row) return
  if (!window.confirm(`确认删除候选 ${row.entry.stockName || row.entry.stockCode}？`)) return
  deletingCandidate.value = true
  errorMessage.value = ''
  try {
    await candidateJournalService.deleteCandidate(row.entry)
    candidates.value = candidates.value.filter((entry) => entry.id !== row.entry.id)
    syncSelection()
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

function close() {
  emit('update:visible', false)
  emit('close')
}

async function openCandidate(target: CandidatePoolOpenPayload = {}) {
  const hasTarget = !!(target.candidateId || target.stockCode || target.liveProjection)
  statusFilter.value = ''
  keyword.value = ''
  await loadCandidates()
  const matched = strategyRows.value.find(
    (row) =>
      row.entry.id === target.candidateId ||
      normalizeCode(row.entry.stockCode) === normalizeCode(target.stockCode),
  )
  if (matched) {
    if (target.liveProjection) {
      const decisionKey = matched.entry.id
      liveDecisionOverrides.value = {
        ...liveDecisionOverrides.value,
        [decisionKey]: target.liveProjection,
      }
    }
    selectedId.value = matched.entry.id
    transientRow.value = null
    return
  }
  if (target.liveProjection) {
    const row = {
      entry: buildTransientEntry(target.liveProjection),
      projection: target.liveProjection,
      liveDecisionProjection: target.liveProjection,
    }
    transientRow.value = row
    selectedId.value = row.entry.id
    errorMessage.value = ''
    return
  }
  if (hasTarget && !matched) {
    errorMessage.value = '未找到对应候选，已打开候选池列表。'
  }
}

onMounted(() => {
  const raw = localStorage.getItem(RANK_TREND_LIVE_STRATEGY_CONFIG_STORAGE_KEY)
  if (raw) {
    try {
      pendingStrategyMode.value = normalizeRankTrendLiveStrategyConfig(JSON.parse(raw)).mode
    } catch {
      pendingStrategyMode.value = 'balanced'
    }
  }
  if (props.visible) {
    void loadCandidates()
  }
})

watch(pendingStrategyMode, (mode) => {
  localStorage.setItem(
    RANK_TREND_LIVE_STRATEGY_CONFIG_STORAGE_KEY,
    JSON.stringify(normalizeRankTrendLiveStrategyConfig({ mode })),
  )
})

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      void loadCandidates()
    }
  },
)

watch(visibleRows, () => {
  syncSelection()
})

watch(
  () => selectedRow.value?.entry || null,
  (entry) => {
    applySelectedEntryToForms(entry)
  },
  { immediate: true },
)

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
  background: rgba(0, 0, 0, 0.68);
  backdrop-filter: blur(6px);
}

.candidate-panel {
  --candidate-font-ui: Inter, 'SF Pro Display', 'Segoe UI', 'Microsoft YaHei UI', sans-serif;
  --candidate-font-data: 'DIN Alternate', 'Roboto Condensed', 'Roboto Mono', Consolas, monospace;
  --candidate-bg: #111318;
  --candidate-rail: #0d1118;
  --candidate-surface: #1b2028;
  --candidate-surface-strong: #252c37;
  --candidate-text: #f4f7fb;
  --candidate-muted: #aeb8c8;
  --candidate-faint: #738093;
  --candidate-line: rgba(168, 184, 204, 0.22);
  --candidate-line-strong: rgba(212, 222, 236, 0.38);
  --candidate-accent: #ffb13b;
  --candidate-hot: #ff5c73;
  --candidate-green: #29d17d;
  --candidate-blue: #5eb6ff;

  display: flex;
  flex-direction: column;
  width: min(1160px, calc(100vw - 32px));
  height: min(760px, calc(100vh - 40px));
  overflow: hidden;
  color: var(--candidate-text);
  font-family: var(--candidate-font-ui);
  background:
    radial-gradient(circle at top left, rgba(255, 177, 59, 0.12), transparent 260px),
    linear-gradient(180deg, rgba(94, 182, 255, 0.05), transparent 240px),
    var(--candidate-bg);
  border: 1px solid var(--candidate-line-strong);
  border-radius: 10px;
  box-shadow: 0 28px 80px rgba(0, 0, 0, 0.58);
}

.candidate-header,
.candidate-toolbar,
.detail-title,
.quick-actions,
.section-header,
.inline-form,
.candidate-item-main,
.candidate-item-meta,
.candidate-item-foot {
  display: flex;
  align-items: center;
}

.candidate-header {
  justify-content: space-between;
  padding: 20px 24px 18px;
  background:
    linear-gradient(90deg, rgba(255, 177, 59, 0.18), rgba(94, 182, 255, 0.06) 56%, transparent),
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
  font-size: 20px;
  font-weight: 800;
}

.candidate-header p,
.detail-title span,
.candidate-group-header span,
.section-copy {
  margin: 4px 0 0;
  color: var(--candidate-muted);
  font-size: 12px;
}

.icon-btn,
.text-btn,
.quick-actions button,
.candidate-item {
  color: var(--candidate-text);
  background: var(--candidate-surface);
  border: 1px solid var(--candidate-line);
  border-radius: 6px;
  cursor: pointer;
  transition:
    border-color 160ms ease,
    background-color 160ms ease,
    box-shadow 160ms ease;
}

.icon-btn:hover,
.text-btn:hover,
.quick-actions button:hover,
.candidate-item:hover {
  background: var(--candidate-surface-strong);
  border-color: rgba(255, 177, 59, 0.52);
  box-shadow: 0 0 0 1px rgba(255, 177, 59, 0.08);
}

.icon-btn:focus-visible,
.text-btn:focus-visible,
.quick-actions button:focus-visible,
.candidate-item:focus-visible,
select:focus-visible,
input:focus-visible,
textarea:focus-visible {
  outline: 2px solid rgba(255, 177, 59, 0.8);
  outline-offset: 2px;
}

.icon-btn {
  width: 36px;
  height: 36px;
  font-size: 18px;
  line-height: 1;
}

.candidate-toolbar {
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px 24px;
  background: rgba(13, 17, 24, 0.72);
  border-bottom: 1px solid var(--candidate-line);
}

.candidate-toolbar select,
.candidate-toolbar input,
.candidate-toolbar .text-btn,
.quick-actions button {
  min-height: 34px;
  padding: 0 12px;
  font-size: 12px;
}

.candidate-toolbar select {
  flex: 0 0 180px;
}

.mode-note {
  flex: 1 1 260px;
  color: var(--candidate-muted);
  font-size: 12px;
}

.keyword-filter {
  flex: 0 0 180px;
}

.summary {
  margin-left: auto;
  color: var(--candidate-muted);
  font-family: var(--candidate-font-data);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
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
  grid-template-columns: 320px minmax(0, 1fr);
  min-height: 0;
  flex: 1;
}

.candidate-list {
  overflow-y: auto;
  padding: 14px 0;
  background: var(--candidate-rail);
  border-right: 1px solid var(--candidate-line);
}

.candidate-group {
  padding: 0 14px 14px;
}

.candidate-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  padding: 0 4px;
}

.candidate-group-header strong {
  color: var(--candidate-accent);
  font-family: var(--candidate-font-data);
  font-size: 12px;
}

.candidate-item {
  position: relative;
  display: grid;
  gap: 8px;
  width: 100%;
  margin-bottom: 8px;
  padding: 12px 14px;
  text-align: left;
}

.candidate-item::before {
  position: absolute;
  top: 12px;
  bottom: 12px;
  left: 0;
  width: 3px;
  content: '';
  background: transparent;
  border-radius: 0 999px 999px 0;
}

.candidate-item.active {
  background:
    linear-gradient(90deg, rgba(255, 177, 59, 0.2), rgba(94, 182, 255, 0.06) 56%, rgba(255, 255, 255, 0.02)),
    var(--candidate-surface);
  box-shadow:
    inset 0 0 0 1px rgba(255, 177, 59, 0.26),
    inset 3px 0 0 rgba(255, 177, 59, 0.65);
}

.candidate-item.active::before {
  background: linear-gradient(180deg, var(--candidate-hot), var(--candidate-accent));
}

.candidate-item-main,
.candidate-item-meta,
.candidate-item-foot {
  justify-content: space-between;
  gap: 8px;
}

.candidate-name {
  display: grid;
  gap: 2px;
}

.candidate-name strong {
  font-size: 14px;
  font-weight: 800;
}

.candidate-name span,
.candidate-item-meta,
.candidate-item-foot {
  color: var(--candidate-muted);
  font-size: 12px;
}

.candidate-status {
  color: var(--candidate-blue);
  font-weight: 800;
}

.strategy-state-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 26px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 800;
  color: var(--candidate-text);
  background: rgba(94, 182, 255, 0.12);
  border: 1px solid rgba(94, 182, 255, 0.24);
  border-radius: 999px;
}

.strategy-state-pill[data-state='triggered_wait_entry'] {
  color: #ffe8ae;
  background: rgba(255, 177, 59, 0.14);
  border-color: rgba(255, 177, 59, 0.32);
}

.strategy-state-pill[data-state='active_holding'] {
  color: #d9ffe8;
  background: rgba(41, 209, 125, 0.14);
  border-color: rgba(41, 209, 125, 0.32);
}

.strategy-state-pill[data-state='exit_signaled'] {
  color: #ffd0d8;
  background: rgba(255, 92, 115, 0.14);
  border-color: rgba(255, 92, 115, 0.28);
}

.strategy-state-pill[data-state='closed'] {
  color: #dde6f7;
  background: rgba(115, 128, 147, 0.18);
  border-color: rgba(115, 128, 147, 0.34);
}

.strategy-state-pill[data-state='auto_add'] {
  color: #d9ffe8;
  background: rgba(41, 209, 125, 0.14);
  border-color: rgba(41, 209, 125, 0.32);
}

.strategy-state-pill[data-state='watch_candidate'] {
  color: #ffe8ae;
  background: rgba(255, 177, 59, 0.14);
  border-color: rgba(255, 177, 59, 0.32);
}

.strategy-state-pill[data-state='blocked_candidate'] {
  color: #ffd0d8;
  background: rgba(255, 92, 115, 0.14);
  border-color: rgba(255, 92, 115, 0.28);
}

.strategy-state-pill[data-state='not_candidate'] {
  color: #dde6f7;
  background: rgba(115, 128, 147, 0.18);
  border-color: rgba(115, 128, 147, 0.34);
}

.candidate-detail {
  overflow-y: auto;
  padding: 18px 22px 24px;
  background: #171b22;
}

.detail-title {
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.quick-actions {
  flex-wrap: wrap;
  gap: 8px;
}

.quick-actions .danger-btn {
  color: #ff8f8f;
  background: rgba(255, 92, 115, 0.14);
  border-color: rgba(255, 92, 115, 0.42);
}

.quick-actions button:disabled,
.text-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.candidate-detail section {
  margin: 0 0 16px;
  padding: 14px;
  background: rgba(37, 44, 55, 0.72);
  border: 1px solid var(--candidate-line);
  border-radius: 8px;
}

.strategy-card {
  background:
    linear-gradient(135deg, rgba(255, 177, 59, 0.16), rgba(94, 182, 255, 0.05) 58%, rgba(255, 255, 255, 0.02)),
    rgba(37, 44, 55, 0.72);
  border-color: rgba(255, 177, 59, 0.34);
}

.section-header {
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.section-header h4 {
  margin: 0;
  font-size: 13px;
  font-weight: 800;
}

.fact-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.compact-facts {
  margin-bottom: 12px;
}

.fact-item {
  min-width: 0;
  padding: 10px 12px;
  background: rgba(13, 17, 24, 0.76);
  border: 1px solid var(--candidate-line);
  border-radius: 7px;
}

.fact-item span {
  display: block;
  color: var(--candidate-muted);
  font-size: 12px;
  font-weight: 700;
}

.fact-item strong {
  display: block;
  margin-top: 4px;
  font-family: var(--candidate-font-data);
  font-size: 14px;
  font-weight: 800;
  line-height: 1.45;
}

.fact-notes {
  margin: 12px 0 0;
  padding-left: 18px;
  color: var(--candidate-muted);
  font-size: 13px;
  line-height: 1.65;
}

.snapshot-note {
  margin-top: 12px;
  color: var(--candidate-muted);
  font-size: 12px;
}

.config-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.config-strip div {
  min-width: 0;
  padding: 8px 10px;
  background: rgba(13, 17, 24, 0.62);
  border: 1px solid var(--candidate-line);
  border-radius: 7px;
}

.config-strip span {
  display: block;
  color: var(--candidate-muted);
  font-size: 11px;
  font-weight: 700;
}

.config-strip strong {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: var(--candidate-text);
  font-family: var(--candidate-font-data);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gate-matrix {
  margin-top: 12px;
}

.section-header.compact {
  margin-bottom: 8px;
}

.gate-table {
  display: grid;
  gap: 4px;
}

.gate-row {
  display: grid;
  grid-template-columns: 1.15fr 0.55fr 0.55fr 1.15fr 1.15fr;
  gap: 8px;
  align-items: center;
  min-height: 30px;
  padding: 6px 8px;
  color: var(--candidate-muted);
  background: rgba(13, 17, 24, 0.58);
  border: 1px solid rgba(90, 104, 124, 0.26);
  border-radius: 6px;
  font-size: 12px;
}

.gate-head {
  color: #c7d3e6;
  background: rgba(94, 182, 255, 0.08);
  font-weight: 800;
}

.gate-row strong {
  font-size: 12px;
}

.gate-row[data-status='pass'] strong {
  color: #7ee0a3;
}

.gate-row[data-status='warn'] strong {
  color: #ffd36a;
}

.gate-row[data-status='fail'] strong {
  color: #ff8f9f;
}

.gate-row[data-status='disabled'] strong {
  color: #8f99a8;
}

.form-grid {
  display: grid;
  gap: 10px;
}

.exec-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
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

label,
.full-field {
  display: block;
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

select {
  height: 34px;
  padding: 0 8px;
}

textarea::placeholder,
input::placeholder {
  color: var(--candidate-faint);
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
  .keyword-filter {
    flex-basis: 100%;
  }

  .candidate-body {
    grid-template-columns: 1fr;
  }

  .candidate-list {
    max-height: 280px;
    border-right: 0;
    border-bottom: 1px solid var(--candidate-line);
  }

  .candidate-detail {
    padding: 16px;
  }

  .detail-title {
    flex-direction: column;
    align-items: flex-start;
  }

  .fact-grid,
  .config-strip,
  .exec-grid,
  .thesis-grid,
  .review-grid {
    grid-template-columns: 1fr;
  }

  .gate-row {
    grid-template-columns: 1fr;
  }
}
</style>
