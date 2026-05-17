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

onMounted(() => {
  loadEntries()
  loadStats()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" style="position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;display:flex;align-items:center;justify-content:center" @click.self="close">
      <div style="width:1120px;max-width:calc(100vw - 32px);max-height:88vh;background:#fff;border-radius:8px;display:flex;flex-direction:column;overflow:hidden">
        <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #e0e0e0">
          <h2 style="margin:0;font-size:16px">历史交易日志</h2>
          <button style="background:none;border:none;font-size:18px;cursor:pointer" @click="close">✕</button>
        </div>

        <div style="display:flex;flex:1;overflow:hidden">
          <!-- Left: Entry List -->
          <div style="flex:1;min-width:280px;max-width:380px;border-right:1px solid #e0e0e0;display:flex;flex-direction:column">
            <div style="display:flex;flex-wrap:wrap;gap:4px;padding:8px">
              <input v-model="filterStock" placeholder="搜索标的..." @input="loadEntries" style="flex:1;padding:4px;border:1px solid #ddd;border-radius:4px;font-size:12px" />
              <select v-model="filterDirection" @change="loadEntries" style="flex:1;padding:4px;border:1px solid #ddd;border-radius:4px;font-size:12px">
                <option value="">全部</option>
                <option value="buy">买入</option>
                <option value="sell">卖出</option>
              </select>
              <select v-model="filterStatus" @change="loadEntries" style="flex:1 1 96px;padding:4px;border:1px solid #ddd;border-radius:4px;font-size:12px">
                <option v-for="option in STATUS_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
              <button @click="resetForm()" style="padding:4px 12px;background:#1565c0;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px">+ 新增交易记录</button>
            </div>
            <div v-if="errorMessage" style="margin:0 8px 8px;padding:8px;background:#fff3e0;color:#b45f06;border:1px solid #ffcc80;border-radius:4px;font-size:12px;line-height:1.5">{{ errorMessage }}</div>
            <div style="flex:1;overflow-y:auto" v-if="!loading">
              <div
                v-for="entry in filteredEntries"
                :key="entry.id"
                :style="{ display:'flex', gap:'6px', padding:'6px 8px', cursor:'pointer', borderBottom:'1px solid #f0f0f0', fontSize:'13px', alignItems:'center', background: entry.id === selectedId ? '#e3f2fd' : '' }"
                @click="selectEntry(entry)"
              >
                <span style="min-width:42px;color:#1565c0;font-size:12px">{{ optionLabel(STATUS_OPTIONS, entry.status) }}</span>
                <span style="font-family:monospace;min-width:60px">{{ entry.stockCode }}</span>
                <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ entry.stockName }}</span>
                <span :style="{ color: entry.direction === 'buy' ? '#e53935' : '#43a047', fontWeight:'bold', minWidth:'20px' }">{{ entry.direction === 'buy' ? '买' : '卖' }}</span>
                <span v-if="entry.pnl != null" :style="{ color: entry.pnl >= 0 ? '#e53935' : '#43a047', minWidth:'60px', textAlign:'right' }">{{ entry.pnl >= 0 ? '+' : '' }}{{ entry.pnl.toFixed(0) }}</span>
              </div>
              <div v-if="!filteredEntries.length" style="padding:24px 12px;text-align:center;color:#888;font-size:13px">暂无历史交易记录</div>
            </div>
            <div v-else style="padding:24px 12px;text-align:center;color:#888;font-size:13px">加载中...</div>
          </div>

          <!-- Right: Form -->
          <div style="flex:2;padding:12px 16px;overflow-y:auto">
            <template v-if="!selectedEntry || selectedEntry.tradeType !== 'exit'">
              <h3 style="font-size:14px;margin:12px 0 8px;padding-bottom:4px;border-bottom:1px solid #eee">{{ selectedId ? '编辑交易记录' : '新增交易记录' }}</h3>
              <div style="margin-bottom:8px">
                <label style="display:block;font-size:12px;color:#666;margin-bottom:2px">标的</label>
                <div style="display:flex;gap:4px;align-items:center">
                  <input v-model="form.stockCode" placeholder="代码" style="flex:1;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px" />
                  <input v-model="form.stockName" placeholder="名称" style="flex:1;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px" />
                </div>
              </div>
              <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:8px">
                <div>
                  <label style="display:block;font-size:12px;color:#666;margin-bottom:2px">状态</label>
                  <select v-model="form.status" style="width:100%;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px">
                    <option v-for="option in ENTRY_STATUS_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
                  </select>
                </div>
              </div>
              <h3 style="font-size:14px;margin:12px 0 8px;padding-bottom:4px;border-bottom:1px solid #eee">成交信息</h3>
              <div style="display:flex;gap:8px;margin-bottom:8px">
                <div style="flex:1">
                  <label style="display:block;font-size:12px;color:#666;margin-bottom:2px">方向</label>
                  <select v-model="form.direction" style="width:100%;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px">
                    <option value="buy">买入</option>
                    <option value="sell">卖出</option>
                  </select>
                </div>
                <div style="flex:1">
                  <label style="display:block;font-size:12px;color:#666;margin-bottom:2px">价格</label>
                  <input v-model.number="form.price" type="number" step="0.01" style="width:100%;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px" />
                </div>
                <div style="flex:1">
                  <label style="display:block;font-size:12px;color:#666;margin-bottom:2px">数量(股)</label>
                  <input v-model.number="form.volume" type="number" style="width:100%;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px" />
                </div>
              </div>
              <div style="margin-bottom:8px">
                <label style="display:block;font-size:12px;color:#666;margin-bottom:2px">笔记</label>
                <textarea v-model="form.notes" rows="3" style="width:100%;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px"></textarea>
              </div>
              <div v-if="form.signalsSnapshot" style="background:#f5f5f5;padding:8px;border-radius:4px;margin:8px 0;font-size:12px">
                <h4 style="margin:0 0 4px">信号快照</h4>
                <div v-if="form.signalsSnapshot.dragon"><strong>龙头:</strong> {{ form.signalsSnapshot.dragon.primaryRole }} | {{ form.signalsSnapshot.dragon.authorityClass }} | {{ form.signalsSnapshot.dragon.tradeability }}</div>
                <div v-if="form.signalsSnapshot.sentiment"><strong>情绪:</strong> {{ form.signalsSnapshot.sentiment.emotionPhase }} ({{ form.signalsSnapshot.sentiment.breathScore }})</div>
                <div v-if="form.signalsSnapshot.rankTrend"><strong>排名趋势:</strong> {{ form.signalsSnapshot.rankTrend.candidateTier }} | 动量:{{ form.signalsSnapshot.rankTrend.momentumComposite }} | {{ form.signalsSnapshot.rankTrend.attentionStage }} | {{ form.signalsSnapshot.rankTrend.decision }}</div>
              </div>
              <button @click="saveEntry" style="background:#1565c0;color:#fff;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;margin-top:8px">保存</button>
            </template>

            <template v-if="selectedEntry && selectedEntry.tradeType !== 'exit' && !selectedEntry.linkedEntryId">
              <h3 style="font-size:14px;margin:12px 0 8px;padding-bottom:4px;border-bottom:1px solid #eee">记录出场</h3>
              <div style="margin-bottom:8px">
                <label style="display:block;font-size:12px;color:#666;margin-bottom:2px">卖出价格</label>
                <input v-model.number="exitPrice" type="number" step="0.01" style="width:100%;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px" />
              </div>
              <div style="margin-bottom:8px">
                <label style="display:block;font-size:12px;color:#666;margin-bottom:2px">卖出数量(默认全部)</label>
                <input v-model.number="exitVolume" type="number" :placeholder="String(selectedEntry.volume)" style="width:100%;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px" />
              </div>
              <div style="margin-bottom:8px">
                <label style="display:block;font-size:12px;color:#666;margin-bottom:2px">复盘笔记</label>
                <textarea v-model="entryNotes" rows="3" style="width:100%;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px"></textarea>
              </div>
              <button @click="recordExit" :disabled="!exitPrice" style="background:#1565c0;color:#fff;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;margin-top:8px">记录出场</button>
            </template>

            <template v-if="selectedEntry">
              <h3 style="font-size:14px;margin:12px 0 8px;padding-bottom:4px;border-bottom:1px solid #eee">复盘结果</h3>
              <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:8px">
                <div>
                  <label style="display:block;font-size:12px;color:#666;margin-bottom:2px">复盘结果</label>
                  <select v-model="form.reviewOutcome" style="width:100%;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px">
                    <option v-for="option in REVIEW_OUTCOME_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
                  </select>
                </div>
                <div>
                  <label style="display:block;font-size:12px;color:#666;margin-bottom:2px">模型结果</label>
                  <select v-model="form.modelResult" style="width:100%;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px">
                    <option v-for="option in MODEL_RESULT_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
                  </select>
                </div>
                <div>
                  <label style="display:block;font-size:12px;color:#666;margin-bottom:2px">执行结果</label>
                  <select v-model="form.executionResult" style="width:100%;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px">
                    <option v-for="option in EXECUTION_RESULT_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
                  </select>
                </div>
              </div>
              <div style="margin-bottom:8px">
                <label style="display:block;font-size:12px;color:#666;margin-bottom:2px">复盘结论</label>
                <textarea v-model="form.reviewNotes" rows="3" style="width:100%;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px"></textarea>
              </div>
              <button @click="saveEntry" style="background:#1565c0;color:#fff;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;margin:0 0 8px">保存复盘</button>

              <h3 style="font-size:14px;margin:12px 0 8px;padding-bottom:4px;border-bottom:1px solid #eee">复盘标签</h3>
              <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">
                <span v-for="tag in selectedEntry.reviewTags" :key="tag" style="background:#e3f2fd;color:#1565c0;padding:2px 8px;border-radius:12px;font-size:12px">{{ tag }}</span>
              </div>
              <div style="display:flex;gap:4px;margin-bottom:8px">
                <input v-model="reviewTagsInput" placeholder="添加标签（逗号分隔）" style="flex:1;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px" />
                <button @click="addReviewTags" style="padding:4px 8px;font-size:12px;border:1px solid #ddd;border-radius:4px;cursor:pointer">添加</button>
              </div>
              <div style="display:flex;flex-wrap:wrap;gap:4px;margin:4px 0 8px">
                <span v-for="tag in PRESET_TAGS" :key="tag" @click="reviewTagsInput = tag" style="background:#f5f5f5;padding:2px 8px;border-radius:8px;font-size:11px;cursor:pointer">{{ tag }}</span>
              </div>
              <h3 style="font-size:14px;margin:12px 0 8px;padding-bottom:4px;border-bottom:1px solid #eee">截图</h3>
              <div style="display:flex;flex-wrap:wrap;gap:8px;margin:8px 0">
                <div v-for="path in selectedEntry.screenshotPaths" :key="path">
                  <img :src="`/api/static/${path}`" :alt="path" style="max-width:120px;max-height:80px;border:1px solid #ddd;border-radius:4px" />
                </div>
              </div>
              <input type="file" accept="image/png,image/jpeg,image/webp" @change="(e) => { const f = (e.target as HTMLInputElement).files?.[0]; if (f) uploadScreenshot(f) }" />
              <button @click="deleteEntry(selectedEntry.id)" style="background:#c62828;color:#fff;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;margin-top:16px">删除记录</button>
            </template>
          </div>
        </div>

        <div v-if="stats" style="display:flex;gap:16px;padding:8px 16px;background:#f5f5f5;border-top:1px solid #e0e0e0;font-size:13px">
          <span>总盈亏: <strong :style="{ color: stats.totalPnl >= 0 ? '#e53935' : '#43a047' }">{{ stats.totalPnl >= 0 ? '+' : '' }}{{ stats.totalPnl.toFixed(0) }}</strong></span>
          <span>胜率: <strong>{{ (stats.winRate * 100).toFixed(1) }}%</strong></span>
          <span>已平仓: <strong>{{ stats.totalExits }}</strong>笔</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>
