<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { API_CONFIG } from '@/config/constants'
import { apiService } from '@/services/apiService'

interface JournalEntry {
  id: string
  stockCode: string
  stockName: string
  direction: string
  tradeType: string
  price: number
  volume: number
  tradeTime: string
  linkedEntryId: string | null
  signalsSnapshot: Record<string, any> | null
  notes: string
  screenshotPaths: string[]
  reviewTags: string[]
  pnl: number | null
  pnlPct: number | null
  status: string
  marketPhase: string
  themeRole: string
  stockRole: string
  entryReason: string
  tradeHypothesis: string
  entryPrerequisites: string
  invalidationRules: string
  expectedHoldingDays: number
  humanDecision: string
  skipReason: string
  reviewOutcome: string
  modelResult: string
  executionResult: string
  reviewNotes: string
  createdAt: string
  updatedAt: string
}

interface JournalStats {
  tagCounts: Record<string, number>
  totalPnl: number
  winRate: number
  totalExits: number
}

type JournalForm = Omit<
  JournalEntry,
  'id' | 'screenshotPaths' | 'reviewTags' | 'pnl' | 'pnlPct' | 'createdAt' | 'updatedAt'
>

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'observe', label: '观察' },
  { value: 'triggered', label: '触发' },
  { value: 'tracking', label: '跟踪中' },
  { value: 'reviewed', label: '已复盘' },
]

const ENTRY_STATUS_OPTIONS = STATUS_OPTIONS.filter(option => option.value)

const REVIEW_OUTCOME_OPTIONS = [
  { value: 'pending', label: '待复盘' },
  { value: 'success', label: '成功' },
  { value: 'partial', label: '部分兑现' },
  { value: 'failed', label: '失败' },
  { value: 'not_triggered', label: '未触发' },
]

const MODEL_RESULT_OPTIONS = [
  { value: 'unknown', label: '未判断' },
  { value: 'correct', label: '模型正确' },
  { value: 'partial', label: '部分正确' },
  { value: 'wrong', label: '模型错误' },
]

const EXECUTION_RESULT_OPTIONS = [
  { value: 'unknown', label: '未判断' },
  { value: 'good', label: '执行到位' },
  { value: 'early_sell', label: '卖早' },
  { value: 'late_sell', label: '卖晚' },
  { value: 'chased', label: '追高' },
  { value: 'missed', label: '错过' },
  { value: 'no_trade', label: '未交易' },
]

const PRESET_TAGS = [
  '追高',
  '卖早',
  '信号正确未执行',
  '信号正确执行到位',
  '信号错误',
  '止损',
  '止盈',
  '恐慌卖出',
  '仓位过重',
  '仓位过轻',
  '模型正确',
  '模型错误',
  '未触发',
  '主线确认',
  '支线误判',
  '情绪退潮',
  '题材掉队',
  'RankTrend失效',
]

const JOURNAL_API_BASE = API_CONFIG.CONTEXTS.QUANT_BOARD.baseURL
const TRADE_LOG_TYPES = ['entry', 'exit'] as const

function createDefaultForm(): JournalForm {
  return {
    stockCode: '',
    stockName: '',
    direction: 'buy',
    tradeType: 'entry',
    price: 0,
    volume: 0,
    tradeTime: new Date().toISOString(),
    linkedEntryId: null,
    notes: '',
    signalsSnapshot: null,
    status: 'observe',
    marketPhase: '',
    themeRole: '',
    stockRole: '',
    entryReason: '',
    tradeHypothesis: '',
    entryPrerequisites: '',
    invalidationRules: '',
    expectedHoldingDays: 3,
    humanDecision: 'watch',
    skipReason: '',
    reviewOutcome: 'pending',
    modelResult: 'unknown',
    executionResult: 'unknown',
    reviewNotes: '',
  }
}

function textValue(row: Record<string, any>, camelKey: string, snakeKey: string, fallback = '') {
  const value = row[camelKey] ?? row[snakeKey]
  return value == null ? fallback : String(value)
}

function numberValue(
  row: Record<string, any>,
  camelKey: string,
  snakeKey: string,
  fallback: number | null,
) {
  const value = row[camelKey] ?? row[snakeKey]
  if (value == null || value === '') return fallback
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : fallback
}

function arrayValue(row: Record<string, any>, camelKey: string, snakeKey: string) {
  const value = row[camelKey] ?? row[snakeKey]
  return Array.isArray(value) ? value.map(item => String(item)) : []
}

function normalizeEntry(raw: unknown): JournalEntry {
  const row = (raw && typeof raw === 'object' ? raw : {}) as Record<string, any>
  return {
    id: textValue(row, 'id', 'id'),
    stockCode: textValue(row, 'stockCode', 'stock_code'),
    stockName: textValue(row, 'stockName', 'stock_name'),
    direction: textValue(row, 'direction', 'direction', 'buy'),
    tradeType: textValue(row, 'tradeType', 'trade_type', 'entry'),
    price: numberValue(row, 'price', 'price', 0) ?? 0,
    volume: numberValue(row, 'volume', 'volume', 0) ?? 0,
    tradeTime: textValue(row, 'tradeTime', 'trade_time', new Date().toISOString()),
    linkedEntryId: (row.linkedEntryId ?? row.linked_entry_id ?? null) as string | null,
    signalsSnapshot: (row.signalsSnapshot ?? row.signals_snapshot ?? null) as Record<string, any> | null,
    notes: textValue(row, 'notes', 'notes'),
    screenshotPaths: arrayValue(row, 'screenshotPaths', 'screenshot_paths'),
    reviewTags: arrayValue(row, 'reviewTags', 'review_tags'),
    pnl: numberValue(row, 'pnl', 'pnl', null),
    pnlPct: numberValue(row, 'pnlPct', 'pnl_pct', null),
    status: textValue(row, 'status', 'status', 'observe'),
    marketPhase: textValue(row, 'marketPhase', 'market_phase'),
    themeRole: textValue(row, 'themeRole', 'theme_role'),
    stockRole: textValue(row, 'stockRole', 'stock_role'),
    entryReason: textValue(row, 'entryReason', 'entry_reason'),
    tradeHypothesis: textValue(row, 'tradeHypothesis', 'trade_hypothesis'),
    entryPrerequisites: textValue(row, 'entryPrerequisites', 'entry_prerequisites'),
    invalidationRules: textValue(row, 'invalidationRules', 'invalidation_rules'),
    expectedHoldingDays: numberValue(row, 'expectedHoldingDays', 'expected_holding_days', 3) ?? 3,
    humanDecision: textValue(row, 'humanDecision', 'human_decision', 'watch'),
    skipReason: textValue(row, 'skipReason', 'skip_reason'),
    reviewOutcome: textValue(row, 'reviewOutcome', 'review_outcome', 'pending'),
    modelResult: textValue(row, 'modelResult', 'model_result', 'unknown'),
    executionResult: textValue(row, 'executionResult', 'execution_result', 'unknown'),
    reviewNotes: textValue(row, 'reviewNotes', 'review_notes'),
    createdAt: textValue(row, 'createdAt', 'created_at'),
    updatedAt: textValue(row, 'updatedAt', 'updated_at'),
  }
}

function normalizeStats(raw: unknown): JournalStats {
  const row = (raw && typeof raw === 'object' ? raw : {}) as Record<string, any>
  return {
    tagCounts:
      row.tagCounts && typeof row.tagCounts === 'object'
        ? (row.tagCounts as Record<string, number>)
        : {},
    totalPnl: numberValue(row, 'totalPnl', 'total_pnl', 0) ?? 0,
    winRate: numberValue(row, 'winRate', 'win_rate', 0) ?? 0,
    totalExits: numberValue(row, 'totalExits', 'total_exits', 0) ?? 0,
  }
}

function optionLabel(options: { value: string; label: string }[], value: string) {
  return options.find(option => option.value === value)?.label || value || '未设置'
}

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

function close() {
  emit('update:visible', false)
  emit('close')
}

const entries = ref<JournalEntry[]>([])
const loading = ref(false)
const errorMessage = ref('')
const selectedId = ref<string | null>(null)
const filterStock = ref('')
const filterDirection = ref('')
const filterStatus = ref('')

const form = ref<JournalForm>(createDefaultForm())

const reviewTagsInput = ref('')
const entryNotes = ref('')
const exitPrice = ref(0)
const exitVolume = ref(0)

const selectedEntry = computed(() =>
  entries.value.find(e => e.id === selectedId.value) || null,
)

const filteredEntries = computed(() => {
  let list = entries.value
  if (filterStock.value) {
    const q = filterStock.value.toUpperCase()
    list = list.filter(e => e.stockCode.includes(q) || e.stockName.includes(q))
  }
  if (filterDirection.value) {
    list = list.filter(e => e.direction === filterDirection.value)
  }
  if (filterStatus.value) {
    list = list.filter(e => e.status === filterStatus.value)
  }
  return list
})

const stats = ref<JournalStats | null>(null)

function buildListParams(tradeType: (typeof TRADE_LOG_TYPES)[number]) {
  const params = new URLSearchParams({ limit: '100', trade_type: tradeType })
  if (filterStock.value) params.set('stock_code', filterStock.value)
  if (filterDirection.value) params.set('direction', filterDirection.value)
  if (filterStatus.value) params.set('status', filterStatus.value)
  return params
}

async function loadEntries() {
  loading.value = true
  errorMessage.value = ''
  try {
    const responses = await Promise.all(
      TRADE_LOG_TYPES.map((tradeType) =>
        apiService.get(`/api/journal/entries?${buildListParams(tradeType)}`, {
          context: 'quant-board',
          cache: false,
          silent: true,
          throwOnHttpError: true,
        }),
      ),
    )
    entries.value = responses
      .flatMap((data) => (Array.isArray(data.entries) ? data.entries.map(normalizeEntry) : []))
      .filter((entry) => entry.tradeType !== 'thesis')
      .sort((left, right) => Date.parse(right.tradeTime) - Date.parse(left.tradeTime))
      .slice(0, 100)
  } catch (error) {
    errorMessage.value = `历史交易日志加载失败：${error instanceof Error ? error.message : '未知错误'}`
    entries.value = []
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    const data = await apiService.get('/api/journal/stats', {
      context: 'quant-board',
      cache: false,
      silent: true,
      throwOnHttpError: true,
    })
    stats.value = normalizeStats(data)
  } catch {
    stats.value = null
    /* backend may be unavailable */
  }
}

async function saveEntry() {
  const payload = {
    stock_code: form.value.stockCode,
    stock_name: form.value.stockName,
    direction: form.value.direction,
    trade_type: form.value.tradeType,
    price: form.value.price,
    volume: form.value.volume,
    trade_time: form.value.tradeTime,
    linked_entry_id: form.value.linkedEntryId,
    signals_snapshot: form.value.signalsSnapshot || {},
    notes: form.value.notes,
    status: form.value.status,
    market_phase: form.value.marketPhase,
    theme_role: form.value.themeRole,
    stock_role: form.value.stockRole,
    entry_reason: form.value.entryReason,
    trade_hypothesis: form.value.tradeHypothesis,
    entry_prerequisites: form.value.entryPrerequisites,
    invalidation_rules: form.value.invalidationRules,
    expected_holding_days: form.value.expectedHoldingDays,
    human_decision: form.value.humanDecision,
    skip_reason: form.value.skipReason,
    review_outcome: form.value.reviewOutcome,
    model_result: form.value.modelResult,
    execution_result: form.value.executionResult,
    review_notes: form.value.reviewNotes,
  }

  try {
    if (selectedId.value) {
      await apiService.put(`/api/journal/entries/${selectedId.value}`, payload, {
        context: 'quant-board',
        cache: false,
        silent: true,
        throwOnHttpError: true,
      })
    } else {
      await apiService.post('/api/journal/entries', payload, {
        context: 'quant-board',
        cache: false,
        silent: true,
        throwOnHttpError: true,
      })
    }
    resetForm()
    await loadEntries()
    await loadStats()
  } catch (error) {
    errorMessage.value = `保存失败：${error instanceof Error ? error.message : '未知错误'}`
  }
}

async function recordExit() {
  if (!selectedEntry.value) return
  const exitPayload = {
    stock_code: selectedEntry.value.stockCode,
    stock_name: selectedEntry.value.stockName,
    direction: selectedEntry.value.direction === 'buy' ? 'sell' : 'buy',
    trade_type: 'exit',
    price: exitPrice.value,
    volume: exitVolume.value || selectedEntry.value.volume,
    trade_time: new Date().toISOString(),
    linked_entry_id: selectedEntry.value.id,
    notes: entryNotes.value,
    status: 'tracking',
    market_phase: selectedEntry.value.marketPhase,
    theme_role: selectedEntry.value.themeRole,
    stock_role: selectedEntry.value.stockRole,
    entry_reason: selectedEntry.value.entryReason,
    trade_hypothesis: selectedEntry.value.tradeHypothesis,
    entry_prerequisites: selectedEntry.value.entryPrerequisites,
    invalidation_rules: selectedEntry.value.invalidationRules,
    expected_holding_days: selectedEntry.value.expectedHoldingDays,
    human_decision: 'execute',
    skip_reason: selectedEntry.value.skipReason,
    review_outcome: selectedEntry.value.reviewOutcome,
    model_result: selectedEntry.value.modelResult,
    execution_result: selectedEntry.value.executionResult,
    review_notes: selectedEntry.value.reviewNotes,
  }
  try {
    await apiService.post('/api/journal/entries', exitPayload, {
      context: 'quant-board',
      cache: false,
      silent: true,
      throwOnHttpError: true,
    })
    if (selectedEntry.value.price > 0) {
      const pnl =
        (exitPayload.price - selectedEntry.value.price) * exitPayload.volume
      const pnlPct =
        ((exitPayload.price - selectedEntry.value.price) /
          selectedEntry.value.price) *
        100
      await apiService.put(
        `/api/journal/entries/${selectedEntry.value.id}`,
        { pnl, pnl_pct: pnlPct },
        {
          context: 'quant-board',
          cache: false,
          silent: true,
          throwOnHttpError: true,
        },
      )
    }
    exitPrice.value = 0
    exitVolume.value = 0
    entryNotes.value = ''
    await loadEntries()
    await loadStats()
  } catch (error) {
    errorMessage.value = `记录出场失败：${error instanceof Error ? error.message : '未知错误'}`
  }
}

async function addReviewTags() {
  if (!selectedEntry.value || !reviewTagsInput.value) return
  const newTags = reviewTagsInput.value
    .split(',')
    .map(t => t.trim())
    .filter(Boolean)
  const existingTags = selectedEntry.value.reviewTags || []
  const merged = [...new Set([...existingTags, ...newTags])]
  await apiService.put(`/api/journal/entries/${selectedEntry.value.id}`, { review_tags: merged }, {
    context: 'quant-board',
    cache: false,
    silent: true,
    throwOnHttpError: true,
  })
  reviewTagsInput.value = ''
  await loadEntries()
  await loadStats()
}

async function deleteEntry(id: string) {
  if (!confirm('确认删除此交易记录？关联的出场记录也会被删除。')) return
  await apiService.delete(`/api/journal/entries/${id}`, {
    context: 'quant-board',
    cache: false,
    silent: true,
    throwOnHttpError: true,
  })
  if (selectedId.value === id) selectedId.value = null
  await loadEntries()
  await loadStats()
}

async function uploadScreenshot(file: File) {
  if (!selectedId.value) return
  const formData = new FormData()
  formData.append('file', file)
  await fetch(`${JOURNAL_API_BASE}/api/journal/entries/${selectedId.value}/screenshot`, {
    method: 'POST',
    body: formData,
  })
  await loadEntries()
}

function resetForm() {
  selectedId.value = null
  form.value = createDefaultForm()
}

function selectEntry(entry: JournalEntry) {
  const normalized = normalizeEntry(entry)
  selectedId.value = entry.id
  form.value = {
    stockCode: normalized.stockCode,
    stockName: normalized.stockName,
    direction: normalized.direction,
    tradeType: normalized.tradeType,
    price: normalized.price,
    volume: normalized.volume,
    tradeTime: normalized.tradeTime,
    linkedEntryId: normalized.linkedEntryId,
    notes: normalized.notes,
    signalsSnapshot: normalized.signalsSnapshot,
    status: normalized.status,
    marketPhase: normalized.marketPhase,
    themeRole: normalized.themeRole,
    stockRole: normalized.stockRole,
    entryReason: normalized.entryReason,
    tradeHypothesis: normalized.tradeHypothesis,
    entryPrerequisites: normalized.entryPrerequisites,
    invalidationRules: normalized.invalidationRules,
    expectedHoldingDays: normalized.expectedHoldingDays,
    humanDecision: normalized.humanDecision,
    skipReason: normalized.skipReason,
    reviewOutcome: normalized.reviewOutcome,
    modelResult: normalized.modelResult,
    executionResult: normalized.executionResult,
    reviewNotes: normalized.reviewNotes,
  }
}

function directionLabel(direction: string) {
  return direction === 'buy' ? '买入' : '卖出'
}

function tradeTypeLabel(tradeType: string) {
  return tradeType === 'exit' ? '出场' : '入场'
}

function directionClass(direction: string) {
  return direction === 'buy' ? 'is-buy' : 'is-sell'
}

function pnlClass(value: number | null) {
  if (value == null) return ''
  return value >= 0 ? 'is-profit' : 'is-loss'
}

function statusClass(status: string) {
  return `status-${status || 'unknown'}`
}

function formatTradeTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间未知'
  const pad = (item: number) => String(item).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatNumber(value: number | null | undefined, digits = 2) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '-'
  return numeric.toFixed(digits).replace(/\.?0+$/, '')
}

function formatVolume(value: number | null | undefined) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '-'
  return numeric.toLocaleString('zh-CN')
}

function formatPnl(value: number | null) {
  if (value == null) return '-'
  return `${value >= 0 ? '+' : ''}${value.toFixed(0)}`
}

onMounted(() => {
  loadEntries()
  loadStats()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="trade-journal-overlay" @click.self="close">
      <section class="journal-shell" aria-label="历史交易日志">
        <header class="journal-header">
          <div>
            <p class="eyebrow">Trade Journal</p>
            <h2>历史交易日志</h2>
          </div>
          <div class="journal-header-actions">
            <div v-if="stats" class="metrics-strip" aria-label="交易统计">
              <div class="metric-card">
                <span class="metric-label">总盈亏</span>
                <strong :class="['metric-value', pnlClass(stats.totalPnl)]">
                  {{ formatPnl(stats.totalPnl) }}
                </strong>
              </div>
              <div class="metric-card">
                <span class="metric-label">胜率</span>
                <strong class="metric-value">{{ (stats.winRate * 100).toFixed(1) }}%</strong>
              </div>
              <div class="metric-card">
                <span class="metric-label">已平仓</span>
                <strong class="metric-value">{{ stats.totalExits }}笔</strong>
              </div>
            </div>
            <button class="icon-button" type="button" aria-label="关闭历史交易日志" @click="close">
              ×
            </button>
          </div>
        </header>

        <div class="journal-workspace">
          <aside class="journal-list-panel">
            <div class="list-toolbar">
              <label class="search-field">
                <span>搜索</span>
                <input v-model="filterStock" placeholder="代码 / 名称" @input="loadEntries" />
              </label>
              <div class="filter-row">
                <label>
                  <span>方向</span>
                  <select v-model="filterDirection" @change="loadEntries">
                    <option value="">全部</option>
                    <option value="buy">买入</option>
                    <option value="sell">卖出</option>
                  </select>
                </label>
                <label>
                  <span>状态</span>
                  <select v-model="filterStatus" @change="loadEntries">
                    <option
                      v-for="option in STATUS_OPTIONS"
                      :key="option.value"
                      :value="option.value"
                    >
                      {{ option.label }}
                    </option>
                  </select>
                </label>
              </div>
              <button class="primary-button full-width" type="button" @click="resetForm()">
                新增交易记录
              </button>
            </div>

            <div v-if="errorMessage" class="error-banner" role="alert">{{ errorMessage }}</div>

            <div v-if="!loading" class="journal-entry-list">
              <button
                v-for="entry in filteredEntries"
                :key="entry.id"
                type="button"
                :class="['journal-entry-card', { active: entry.id === selectedId }]"
                @click="selectEntry(entry)"
              >
                <span class="entry-card-top">
                  <span :class="['status-pill', statusClass(entry.status)]">
                    {{ optionLabel(STATUS_OPTIONS, entry.status) }}
                  </span>
                  <span class="entry-time">{{ formatTradeTime(entry.tradeTime) }}</span>
                </span>
                <span class="entry-card-main">
                  <span>
                    <strong class="entry-code">{{ entry.stockCode || '未填代码' }}</strong>
                    <span class="entry-name">{{ entry.stockName || '未填名称' }}</span>
                  </span>
                  <span :class="['direction-pill', directionClass(entry.direction)]">
                    {{ directionLabel(entry.direction) }}
                  </span>
                </span>
                <span class="entry-card-bottom">
                  <span>{{ tradeTypeLabel(entry.tradeType) }}</span>
                  <span>价格 {{ formatNumber(entry.price) }}</span>
                  <span>数量 {{ formatVolume(entry.volume) }}</span>
                  <strong v-if="entry.pnl != null" :class="['entry-pnl', pnlClass(entry.pnl)]">
                    {{ formatPnl(entry.pnl) }}
                  </strong>
                </span>
              </button>
              <div v-if="!filteredEntries.length" class="empty-state">
                <strong>暂无历史交易记录</strong>
                <span>先新增一笔入场或调整筛选条件。</span>
              </div>
            </div>
            <div v-else class="loading-state">加载交易记录中...</div>
          </aside>

          <main class="journal-detail-panel">
            <template v-if="!selectedEntry || selectedEntry.tradeType !== 'exit'">
              <section class="form-section">
                <div class="section-heading">
                  <span>{{ selectedId ? '编辑交易记录' : '新增交易记录' }}</span>
                </div>
                <div class="form-grid two-columns">
                  <label class="field">
                    <span>代码</span>
                    <input v-model="form.stockCode" placeholder="例如 600000" />
                  </label>
                  <label class="field">
                    <span>名称</span>
                    <input v-model="form.stockName" placeholder="股票名称" />
                  </label>
                </div>
                <div class="form-grid compact-grid">
                  <label class="field">
                    <span>状态</span>
                    <select v-model="form.status">
                      <option
                        v-for="option in ENTRY_STATUS_OPTIONS"
                        :key="option.value"
                        :value="option.value"
                      >
                        {{ option.label }}
                      </option>
                    </select>
                  </label>
                  <label class="field">
                    <span>方向</span>
                    <select v-model="form.direction">
                      <option value="buy">买入</option>
                      <option value="sell">卖出</option>
                    </select>
                  </label>
                  <label class="field">
                    <span>价格</span>
                    <input v-model.number="form.price" type="number" step="0.01" />
                  </label>
                  <label class="field">
                    <span>数量(股)</span>
                    <input v-model.number="form.volume" type="number" />
                  </label>
                </div>
                <label class="field">
                  <span>笔记</span>
                  <textarea v-model="form.notes" rows="4" placeholder="记录买卖依据、盘面变化或执行偏差"></textarea>
                </label>

                <div v-if="form.signalsSnapshot" class="snapshot-card">
                  <h4>信号快照</h4>
                  <p v-if="form.signalsSnapshot.dragon">
                    <strong>龙头</strong>
                    {{ form.signalsSnapshot.dragon.primaryRole }} /
                    {{ form.signalsSnapshot.dragon.authorityClass }} /
                    {{ form.signalsSnapshot.dragon.tradeability }}
                  </p>
                  <p v-if="form.signalsSnapshot.sentiment">
                    <strong>情绪</strong>
                    {{ form.signalsSnapshot.sentiment.emotionPhase }}
                    ({{ form.signalsSnapshot.sentiment.breathScore }})
                  </p>
                  <p v-if="form.signalsSnapshot.rankTrend">
                    <strong>排名趋势</strong>
                    {{ form.signalsSnapshot.rankTrend.candidateTier }} /
                    动量 {{ form.signalsSnapshot.rankTrend.momentumComposite }} /
                    {{ form.signalsSnapshot.rankTrend.attentionStage }} /
                    {{ form.signalsSnapshot.rankTrend.decision }}
                  </p>
                </div>

                <div class="action-row">
                  <button class="primary-button" type="button" @click="saveEntry">保存</button>
                </div>
              </section>
            </template>

            <template v-if="selectedEntry && selectedEntry.tradeType !== 'exit' && !selectedEntry.linkedEntryId">
              <section class="form-section exit-section">
                <div class="section-heading">
                  <span>记录出场</span>
                  <small>默认沿用当前入场记录</small>
                </div>
                <div class="form-grid two-columns">
                  <label class="field">
                    <span>卖出价格</span>
                    <input v-model.number="exitPrice" type="number" step="0.01" />
                  </label>
                  <label class="field">
                    <span>卖出数量(默认全部)</span>
                    <input
                      v-model.number="exitVolume"
                      type="number"
                      :placeholder="String(selectedEntry.volume)"
                    />
                  </label>
                </div>
                <label class="field">
                  <span>复盘笔记</span>
                  <textarea v-model="entryNotes" rows="3"></textarea>
                </label>
                <div class="action-row">
                  <button
                    class="primary-button"
                    type="button"
                    :disabled="!exitPrice"
                    @click="recordExit"
                  >
                    记录出场
                  </button>
                </div>
              </section>
            </template>

            <template v-if="selectedEntry">
              <section class="form-section">
                <div class="section-heading">
                  <span>复盘结果</span>
                </div>
                <div class="form-grid three-columns">
                  <label class="field">
                    <span>复盘结果</span>
                    <select v-model="form.reviewOutcome">
                      <option
                        v-for="option in REVIEW_OUTCOME_OPTIONS"
                        :key="option.value"
                        :value="option.value"
                      >
                        {{ option.label }}
                      </option>
                    </select>
                  </label>
                  <label class="field">
                    <span>模型结果</span>
                    <select v-model="form.modelResult">
                      <option
                        v-for="option in MODEL_RESULT_OPTIONS"
                        :key="option.value"
                        :value="option.value"
                      >
                        {{ option.label }}
                      </option>
                    </select>
                  </label>
                  <label class="field">
                    <span>执行结果</span>
                    <select v-model="form.executionResult">
                      <option
                        v-for="option in EXECUTION_RESULT_OPTIONS"
                        :key="option.value"
                        :value="option.value"
                      >
                        {{ option.label }}
                      </option>
                    </select>
                  </label>
                </div>
                <label class="field">
                  <span>复盘结论</span>
                  <textarea v-model="form.reviewNotes" rows="3"></textarea>
                </label>
                <div class="action-row">
                  <button class="secondary-button" type="button" @click="saveEntry">保存复盘</button>
                </div>
              </section>

              <section class="form-section">
                <div class="section-heading">
                  <span>复盘标签</span>
                </div>
                <div class="tag-list">
                  <span v-for="tag in selectedEntry.reviewTags" :key="tag" class="tag-chip">
                    {{ tag }}
                  </span>
                  <span v-if="!selectedEntry.reviewTags.length" class="empty-inline">暂无标签</span>
                </div>
                <div class="inline-editor">
                  <input v-model="reviewTagsInput" placeholder="添加标签，多个用逗号分隔" />
                  <button class="secondary-button" type="button" @click="addReviewTags">添加</button>
                </div>
                <div class="preset-tags">
                  <button
                    v-for="tag in PRESET_TAGS"
                    :key="tag"
                    class="preset-tag"
                    type="button"
                    @click="reviewTagsInput = tag"
                  >
                    {{ tag }}
                  </button>
                </div>
              </section>

              <section class="form-section">
                <div class="section-heading">
                  <span>截图</span>
                </div>
                <div class="screenshot-grid">
                  <div v-for="path in selectedEntry.screenshotPaths" :key="path" class="screenshot-item">
                    <img :src="`/api/static/${path}`" :alt="path" />
                  </div>
                  <span v-if="!selectedEntry.screenshotPaths.length" class="empty-inline">
                    暂无截图
                  </span>
                </div>
                <input
                  class="file-input"
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  @change="(e) => { const f = (e.target as HTMLInputElement).files?.[0]; if (f) uploadScreenshot(f) }"
                />
                <div class="danger-zone">
                  <button class="danger-button" type="button" @click="deleteEntry(selectedEntry.id)">
                    删除记录
                  </button>
                </div>
              </section>
            </template>
          </main>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.trade-journal-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background:
    radial-gradient(circle at 18% 8%, rgba(52, 152, 219, 0.16), transparent 28%),
    rgba(10, 14, 20, 0.68);
}

.journal-shell {
  display: flex;
  flex-direction: column;
  width: min(1180px, calc(100vw - 32px));
  max-height: min(88vh, 820px);
  overflow: hidden;
  color: #182230;
  background: #f7f9fc;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-radius: 12px;
  box-shadow: 0 24px 70px rgba(8, 18, 35, 0.36);
}

.journal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  background: linear-gradient(180deg, #ffffff 0%, #f6f8fb 100%);
  border-bottom: 1px solid #dbe3ee;
}

.journal-header h2 {
  margin: 2px 0 0;
  font-size: 19px;
  font-weight: 700;
  letter-spacing: 0;
  color: #111827;
}

.eyebrow {
  margin: 0;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  color: #2f6fbb;
  text-transform: uppercase;
}

.journal-header-actions,
.metrics-strip,
.filter-row,
.entry-card-top,
.entry-card-main,
.entry-card-bottom,
.action-row,
.inline-editor {
  display: flex;
  align-items: center;
}

.journal-header-actions {
  gap: 12px;
}

.metrics-strip {
  gap: 8px;
}

.metric-card {
  min-width: 86px;
  padding: 7px 10px;
  background: #ffffff;
  border: 1px solid #d8e0ea;
  border-radius: 8px;
}

.metric-label,
.field > span,
.search-field > span,
.filter-row label > span {
  display: block;
  margin-bottom: 5px;
  font-size: 12px;
  font-weight: 600;
  color: #65758b;
}

.metric-value {
  display: block;
  font-size: 15px;
  line-height: 1.2;
  color: #182230;
  font-variant-numeric: tabular-nums;
}

.icon-button,
.primary-button,
.secondary-button,
.danger-button,
.journal-entry-card,
.preset-tag {
  border: 0;
  cursor: pointer;
  font: inherit;
}

.icon-button {
  width: 36px;
  height: 36px;
  font-size: 22px;
  line-height: 1;
  color: #526173;
  background: #ffffff;
  border: 1px solid #d8e0ea;
  border-radius: 8px;
}

.icon-button:hover,
.secondary-button:hover,
.preset-tag:hover {
  border-color: #9ab7dd;
  color: #1f5f9f;
  background: #eef6ff;
}

.journal-workspace {
  display: grid;
  grid-template-columns: minmax(300px, 360px) minmax(0, 1fr);
  min-height: 0;
  flex: 1;
}

.journal-list-panel,
.journal-detail-panel {
  min-height: 0;
  overflow-y: auto;
}

.journal-list-panel {
  display: flex;
  flex-direction: column;
  background: #eef3f8;
  border-right: 1px solid #d6dfeb;
}

.list-toolbar {
  display: grid;
  gap: 10px;
  padding: 12px;
  background: #f8fafc;
  border-bottom: 1px solid #dce4ef;
}

.filter-row {
  gap: 8px;
}

.filter-row label {
  flex: 1;
  min-width: 0;
}

input,
select,
textarea {
  width: 100%;
  min-width: 0;
  color: #162132;
  background: #ffffff;
  border: 1px solid #ccd7e3;
  border-radius: 7px;
  outline: none;
  transition:
    border-color 0.16s ease,
    box-shadow 0.16s ease,
    background 0.16s ease;
}

input,
select {
  height: 34px;
  padding: 0 10px;
}

textarea {
  resize: vertical;
  padding: 9px 10px;
  line-height: 1.5;
}

input:focus,
select:focus,
textarea:focus {
  border-color: #2f6fbb;
  box-shadow: 0 0 0 3px rgba(47, 111, 187, 0.14);
}

.primary-button,
.secondary-button,
.danger-button {
  min-height: 36px;
  padding: 0 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 700;
  transition:
    transform 0.16s ease,
    border-color 0.16s ease,
    background 0.16s ease;
}

.primary-button {
  color: #ffffff;
  background: #1f5f9f;
}

.primary-button:hover:not(:disabled) {
  background: #174f88;
}

.primary-button:disabled,
.secondary-button:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.secondary-button {
  color: #1f5f9f;
  background: #ffffff;
  border: 1px solid #c7d6e8;
}

.danger-button {
  color: #ffffff;
  background: #bd2d2d;
}

.danger-button:hover {
  background: #9f2424;
}

.full-width {
  width: 100%;
}

.error-banner {
  margin: 10px 12px 0;
  padding: 10px 12px;
  color: #8a3f00;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.5;
}

.journal-entry-list {
  display: grid;
  gap: 8px;
  padding: 12px;
}

.journal-entry-card {
  display: grid;
  gap: 8px;
  width: 100%;
  padding: 10px;
  text-align: left;
  color: #27364a;
  background: #ffffff;
  border: 1px solid #dce4ef;
  border-radius: 9px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.journal-entry-card:hover,
.journal-entry-card.active {
  border-color: #75a7dd;
  box-shadow: 0 8px 20px rgba(31, 95, 159, 0.12);
}

.journal-entry-card.active {
  background: #f0f7ff;
}

.entry-card-top,
.entry-card-main,
.entry-card-bottom {
  justify-content: space-between;
  gap: 8px;
}

.entry-card-main {
  align-items: flex-start;
}

.entry-card-bottom {
  flex-wrap: wrap;
  font-size: 12px;
  color: #65758b;
}

.entry-code {
  display: block;
  font-size: 15px;
  color: #111827;
  font-variant-numeric: tabular-nums;
}

.entry-name {
  display: block;
  max-width: 190px;
  overflow: hidden;
  color: #65758b;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-time {
  color: #8291a5;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.status-pill,
.direction-pill,
.tag-chip,
.preset-tag {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  min-height: 24px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.status-pill {
  padding: 0 8px;
  color: #38516f;
  background: #edf2f7;
}

.status-triggered {
  color: #945400;
  background: #fff3cf;
}

.status-tracking {
  color: #1f5f9f;
  background: #e6f1ff;
}

.status-reviewed {
  color: #24734e;
  background: #e6f8ef;
}

.direction-pill {
  padding: 0 9px;
}

.is-buy {
  color: #c73535;
  background: #fff0f0;
}

.is-sell {
  color: #1d8a54;
  background: #eaf8f0;
}

.is-profit {
  color: #c73535;
}

.is-loss {
  color: #1d8a54;
}

.entry-pnl {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}

.empty-state,
.loading-state {
  display: grid;
  place-items: center;
  gap: 6px;
  min-height: 150px;
  padding: 22px;
  color: #7a8899;
  text-align: center;
  background: rgba(255, 255, 255, 0.6);
  border: 1px dashed #c8d4e2;
  border-radius: 10px;
}

.empty-state strong {
  color: #40516a;
}

.journal-detail-panel {
  display: grid;
  align-content: start;
  gap: 14px;
  padding: 16px;
  background: #f7f9fc;
}

.form-section {
  display: grid;
  gap: 12px;
  padding: 14px;
  background: #ffffff;
  border: 1px solid #dce4ef;
  border-radius: 10px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}

.exit-section {
  border-color: #b8d4f1;
  background: #f8fbff;
}

.section-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 9px;
  border-bottom: 1px solid #e4ebf3;
}

.section-heading span {
  font-size: 14px;
  font-weight: 800;
  color: #172033;
}

.section-heading small {
  color: #738297;
  font-size: 12px;
}

.form-grid {
  display: grid;
  gap: 10px;
}

.two-columns {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.three-columns {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.compact-grid {
  grid-template-columns: minmax(120px, 0.8fr) minmax(120px, 0.8fr) minmax(120px, 1fr) minmax(140px, 1fr);
}

.field {
  display: grid;
}

.snapshot-card {
  display: grid;
  gap: 6px;
  padding: 12px;
  color: #40516a;
  background: #f6f8fb;
  border: 1px solid #dce4ef;
  border-radius: 8px;
  font-size: 12px;
}

.snapshot-card h4,
.snapshot-card p {
  margin: 0;
}

.snapshot-card strong {
  color: #1f5f9f;
}

.action-row {
  justify-content: flex-end;
  gap: 8px;
}

.tag-list,
.preset-tags,
.screenshot-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.tag-chip {
  padding: 0 9px;
  color: #1f5f9f;
  background: #e8f2ff;
}

.empty-inline {
  color: #7a8899;
  font-size: 12px;
}

.inline-editor {
  gap: 8px;
}

.inline-editor input {
  flex: 1;
}

.preset-tag {
  padding: 0 9px;
  color: #526173;
  background: #f5f7fa;
  border: 1px solid #dce4ef;
}

.screenshot-item {
  width: 126px;
  height: 84px;
  overflow: hidden;
  background: #f2f5f8;
  border: 1px solid #dce4ef;
  border-radius: 8px;
}

.screenshot-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.file-input {
  padding: 6px;
  height: auto;
}

.danger-zone {
  display: flex;
  justify-content: flex-end;
  padding-top: 6px;
  border-top: 1px solid #eef2f6;
}

@media (max-width: 860px) {
  .journal-shell {
    width: calc(100vw - 20px);
    max-height: 92vh;
  }

  .journal-header {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: start;
  }

  .journal-header > div:first-child {
    grid-column: 1;
    grid-row: 1;
  }

  .journal-header-actions {
    display: contents;
  }

  .metrics-strip {
    display: grid;
    grid-column: 1 / -1;
    grid-row: 2;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .journal-header .icon-button {
    grid-column: 2;
    grid-row: 1;
  }

  .journal-workspace {
    grid-template-columns: 1fr;
  }

  .journal-list-panel {
    max-height: 34vh;
    border-right: 0;
    border-bottom: 1px solid #d6dfeb;
  }

  .two-columns,
  .three-columns,
  .compact-grid {
    grid-template-columns: 1fr;
  }

  .empty-state {
    min-height: 112px;
  }
}
</style>
