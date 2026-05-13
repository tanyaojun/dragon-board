<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { dataLayer } from '@/services/DataLayer'
import { dragonReviewService } from '@/services/dragon/DragonReviewService'
import { dragonBreathAnalyzer } from '@/services/DragonBreathAnalyzer'
import { getRankTrendAnalysis } from '@/services/rankTrend/compat'

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
  createdAt: string
  updatedAt: string
}

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

const entries = ref<JournalEntry[]>([])
const loading = ref(false)
const selectedId = ref<string | null>(null)
const filterStock = ref('')
const filterDirection = ref('')

const form = ref({
  stockCode: '',
  stockName: '',
  direction: 'buy' as 'buy' | 'sell',
  tradeType: 'entry' as 'entry' | 'exit',
  price: 0,
  volume: 0,
  tradeTime: new Date().toISOString(),
  linkedEntryId: null as string | null,
  notes: '',
  signalsSnapshot: null as Record<string, any> | null,
})

const reviewTagsInput = ref('')
const entryNotes = ref('')
const exitPrice = ref(0)
const exitVolume = ref(0)

const PRESET_TAGS = ['追高', '卖早', '信号正确未执行', '信号正确执行到位', '信号错误', '止损', '止盈', '恐慌卖出', '仓位过重', '仓位过轻']

const selectedEntry = computed(() => entries.value.find(e => e.id === selectedId.value) || null)

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

const stats = ref<{ tagCounts: Record<string, number>; totalPnl: number; winRate: number; totalExits: number } | null>(null)

async function loadEntries() {
  loading.value = true
  try {
    const params = new URLSearchParams({ limit: '100' })
    if (filterStock.value) params.set('stockCode', filterStock.value)
    if (filterDirection.value) params.set('direction', filterDirection.value)
    const res = await fetch(`/api/journal/entries?${params}`)
    const data = await res.json()
    entries.value = data.entries || []
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    const res = await fetch('/api/journal/stats')
    stats.value = await res.json()
  } catch { /* ignore when backend unavailable */ }
}

function captureSignals(stockCode: string) {
  const stock = dataLayer.getStock(stockCode)
  const review = dragonReviewService.getLatestReview()
  const sentiment = dragonBreathAnalyzer.getMarketSentiment()
  const rankTrend = stock ? getRankTrendAnalysis(stock) : null

  const dragonRecord = review
    ? (review.trueLeaders || []).find((r: any) => r.code === stockCode)
      || (review.heightBoard || []).find((r: any) => r.code === stockCode)
      || (review.attentionBoard || []).find((r: any) => r.code === stockCode)
      || review.marketCore
    : null

  form.value.signalsSnapshot = {
    dragon: dragonRecord ? {
      primaryRole: (dragonRecord as any).primaryRole,
      authorityClass: (dragonRecord as any).authority,
      tradeability: (dragonRecord as any).tradeability,
    } : null,
    sentiment: {
      emotionPhase: sentiment?.phaseName || sentiment?.phase || '',
      breathScore: sentiment?.overall ?? 0,
    },
    rankTrend: rankTrend ? {
      candidateTier: rankTrend.strategy?.candidateTier || 'N_NEUTRAL',
      momentumComposite: rankTrend.technical.momentumProfile.composite,
      attentionStage: rankTrend.cycle.stage,
      decision: rankTrend.decision.final.signal,
    } : null,
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
  }

  let res: Response
  if (selectedId.value) {
    res = await fetch(`/api/journal/entries/${selectedId.value}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  } else {
    res = await fetch('/api/journal/entries', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  }

  if (res.ok) {
    resetForm()
    await loadEntries()
    await loadStats()
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
  }
  const res = await fetch('/api/journal/entries', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(exitPayload),
  })
  if (res.ok) {
    const pnl = (exitPayload.price - selectedEntry.value.price) * exitPayload.volume
    const pnlPct = ((exitPayload.price - selectedEntry.value.price) / selectedEntry.value.price) * 100
    await fetch(`/api/journal/entries/${selectedEntry.value.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pnl, pnl_pct: pnlPct }),
    })
    exitPrice.value = 0
    exitVolume.value = 0
    entryNotes.value = ''
    await loadEntries()
    await loadStats()
  }
}

async function addReviewTags() {
  if (!selectedEntry.value || !reviewTagsInput.value) return
  const newTags = reviewTagsInput.value.split(',').map(t => t.trim()).filter(Boolean)
  const existingTags = selectedEntry.value.reviewTags || []
  const merged = [...new Set([...existingTags, ...newTags])]
  await fetch(`/api/journal/entries/${selectedEntry.value.id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ review_tags: merged }),
  })
  reviewTagsInput.value = ''
  await loadEntries()
  await loadStats()
}

async function deleteEntry(id: string) {
  if (!confirm('确认删除此交易记录？关联的出场记录也会被删除。')) return
  await fetch(`/api/journal/entries/${id}`, { method: 'DELETE' })
  if (selectedId.value === id) selectedId.value = null
  await loadEntries()
  await loadStats()
}

async function uploadScreenshot(file: File) {
  if (!selectedId.value) return
  const formData = new FormData()
  formData.append('file', file)
  await fetch(`/api/journal/entries/${selectedId.value}/screenshot`, {
    method: 'POST',
    body: formData,
  })
  await loadEntries()
}

function resetForm() {
  selectedId.value = null
  form.value = {
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
  }
}

function selectEntry(entry: JournalEntry) {
  selectedId.value = entry.id
  form.value = {
    stockCode: entry.stockCode,
    stockName: entry.stockName,
    direction: entry.direction as 'buy' | 'sell',
    tradeType: entry.tradeType as 'entry' | 'exit',
    price: entry.price,
    volume: entry.volume,
    tradeTime: entry.tradeTime,
    linkedEntryId: entry.linkedEntryId,
    notes: entry.notes,
    signalsSnapshot: entry.signalsSnapshot,
  }
}

onMounted(() => {
  loadEntries()
  loadStats()
})

const stockOptions = computed(() => {
  const stocks = dataLayer.getMergedStocks?.()
  if (!stocks || !Array.isArray(stocks)) return []
  return stocks.slice(0, 200).map((s: any) => ({
    code: s.code,
    name: s.name,
  }))
})
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="trade-journal-overlay" @click.self="emit('update:visible', false); emit('close')">
    <div class="trade-journal-panel">
      <div class="panel-header">
        <h2>交易日记</h2>
        <button class="btn-close" @click="emit('update:visible', false); emit('close')">✕</button>
      </div>

      <div class="panel-body">
        <!-- Left: Entry List -->
        <div class="journal-list">
          <div class="list-header">
            <input v-model="filterStock" placeholder="搜索标的..." @input="loadEntries" />
            <select v-model="filterDirection" @change="loadEntries">
              <option value="">全部</option>
              <option value="buy">买入</option>
              <option value="sell">卖出</option>
            </select>
            <button @click="resetForm()">+ 新增</button>
          </div>
          <div class="entries" v-if="!loading">
            <div
              v-for="entry in filteredEntries"
              :key="entry.id"
              :class="['entry-row', { selected: entry.id === selectedId }]"
              @click="selectEntry(entry)"
            >
              <span :class="`dir-${entry.direction}`">{{ entry.direction === 'buy' ? '买' : '卖' }}</span>
              <span class="code">{{ entry.stockCode }}</span>
              <span class="name">{{ entry.stockName }}</span>
              <span class="price">{{ entry.price }}</span>
              <span v-if="entry.pnl != null" :class="entry.pnl >= 0 ? 'pnl-pos' : 'pnl-neg'">
                {{ entry.pnl >= 0 ? '+' : '' }}{{ entry.pnl.toFixed(0) }}
              </span>
            </div>
          </div>
        </div>

        <!-- Right: Form / Detail -->
        <div class="journal-form">
          <template v-if="!selectedEntry || selectedEntry.tradeType === 'entry'">
            <h3>{{ selectedId ? '编辑入场' : '新增入场' }}</h3>
            <div class="form-group">
              <label>标的</label>
              <div class="stock-picker">
                <input v-model="form.stockCode" placeholder="代码" list="stock-list" />
                <input v-model="form.stockName" placeholder="名称" />
                <datalist id="stock-list">
                  <option v-for="s in stockOptions" :key="s.code" :value="s.code">{{ s.code }} {{ s.name }}</option>
                </datalist>
                <button @click="captureSignals(form.stockCode)" :disabled="!form.stockCode">抓取信号</button>
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>方向</label>
                <select v-model="form.direction">
                  <option value="buy">买入</option>
                  <option value="sell">卖出</option>
                </select>
              </div>
              <div class="form-group">
                <label>价格</label>
                <input v-model.number="form.price" type="number" step="0.01" />
              </div>
              <div class="form-group">
                <label>数量(股)</label>
                <input v-model.number="form.volume" type="number" />
              </div>
            </div>
            <div class="form-group">
              <label>笔记</label>
              <textarea v-model="form.notes" rows="3"></textarea>
            </div>

            <div v-if="form.signalsSnapshot" class="signals-display">
              <h4>信号快照</h4>
              <div v-if="form.signalsSnapshot.dragon" class="signal-block">
                <strong>龙头:</strong>
                {{ form.signalsSnapshot.dragon.primaryRole }} |
                {{ form.signalsSnapshot.dragon.authorityClass }} |
                {{ form.signalsSnapshot.dragon.tradeability }}
              </div>
              <div v-if="form.signalsSnapshot.sentiment" class="signal-block">
                <strong>情绪:</strong>
                {{ form.signalsSnapshot.sentiment.emotionPhase }} ({{ form.signalsSnapshot.sentiment.breathScore }})
              </div>
              <div v-if="form.signalsSnapshot.rankTrend" class="signal-block">
                <strong>排名趋势:</strong>
                {{ form.signalsSnapshot.rankTrend.candidateTier }} |
                动量:{{ form.signalsSnapshot.rankTrend.momentumComposite }} |
                {{ form.signalsSnapshot.rankTrend.attentionStage }} |
                {{ form.signalsSnapshot.rankTrend.decision }}
              </div>
            </div>

            <button class="btn-save" @click="saveEntry">保存</button>
          </template>

          <template v-if="selectedEntry && selectedEntry.tradeType === 'entry' && !selectedEntry.linkedEntryId">
            <h3>记录出场</h3>
            <div class="form-group">
              <label>卖出价格</label>
              <input v-model.number="exitPrice" type="number" step="0.01" />
            </div>
            <div class="form-group">
              <label>卖出数量(默认全部)</label>
              <input v-model.number="exitVolume" type="number" :placeholder="String(selectedEntry.volume)" />
            </div>
            <div class="form-group">
              <label>复盘笔记</label>
              <textarea v-model="entryNotes" rows="3"></textarea>
            </div>
            <button class="btn-save" @click="recordExit" :disabled="!exitPrice">记录出场</button>
          </template>

          <template v-if="selectedEntry">
            <h3>复盘标签</h3>
            <div class="tags-display">
              <span v-for="tag in selectedEntry.reviewTags" :key="tag" class="tag">{{ tag }}</span>
            </div>
            <div class="tag-input-row">
              <input v-model="reviewTagsInput" placeholder="添加标签（逗号分隔）" />
              <button @click="addReviewTags">添加</button>
            </div>
            <div class="preset-tags">
              <span v-for="tag in PRESET_TAGS" :key="tag" class="preset-tag" @click="reviewTagsInput = tag">{{ tag }}</span>
            </div>

            <h3>截图</h3>
            <div class="screenshots">
              <div v-for="path in selectedEntry.screenshotPaths" :key="path" class="screenshot-thumb">
                <img :src="`/api/static/${path}`" :alt="path" />
              </div>
            </div>
            <input type="file" accept="image/png,image/jpeg,image/webp" @change="(e) => { const f = (e.target as HTMLInputElement).files?.[0]; if (f) uploadScreenshot(f) }" />

            <button class="btn-delete" @click="deleteEntry(selectedEntry.id)">删除记录</button>
          </template>
        </div>
      </div>

      <div class="stats-panel" v-if="stats">
        <span>总盈亏: <strong :class="stats.totalPnl >= 0 ? 'pnl-pos' : 'pnl-neg'">{{ stats.totalPnl >= 0 ? '+' : '' }}{{ stats.totalPnl.toFixed(0) }}</strong></span>
        <span>胜率: <strong>{{ (stats.winRate * 100).toFixed(1) }}%</strong></span>
        <span>已平仓: <strong>{{ stats.totalExits }}</strong>笔</span>
      </div>
    </div>
    </div>
  </Teleport>
</template>

<style scoped>
.trade-journal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); z-index: 1000; display: flex; align-items: center; justify-content: center; }
.trade-journal-panel { width: 960px; max-height: 85vh; background: #fff; border-radius: 8px; display: flex; flex-direction: column; overflow: hidden; }
.panel-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid #e0e0e0; }
.panel-header h2 { margin: 0; font-size: 16px; }
.btn-close { background: none; border: none; font-size: 18px; cursor: pointer; }
.panel-body { display: flex; flex: 1; overflow: hidden; }
.journal-list { flex: 1; min-width: 280px; max-width: 380px; border-right: 1px solid #e0e0e0; display: flex; flex-direction: column; }
.list-header { display: flex; gap: 4px; padding: 8px; }
.list-header input, .list-header select { flex: 1; padding: 4px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px; }
.list-header button { padding: 4px 12px; background: #1565c0; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
.entries { flex: 1; overflow-y: auto; }
.entry-row { display: flex; gap: 6px; padding: 6px 8px; cursor: pointer; border-bottom: 1px solid #f0f0f0; font-size: 13px; align-items: center; }
.entry-row.selected { background: #e3f2fd; }
.entry-row:hover { background: #f5f5f5; }
.dir-buy { color: #e53935; font-weight: bold; min-width: 20px; }
.dir-sell { color: #43a047; font-weight: bold; min-width: 20px; }
.code { font-family: monospace; min-width: 60px; }
.name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.price { min-width: 50px; text-align: right; }
.pnl-pos { color: #e53935; min-width: 60px; text-align: right; }
.pnl-neg { color: #43a047; min-width: 60px; text-align: right; }
.journal-form { flex: 2; padding: 12px 16px; overflow-y: auto; }
.journal-form h3 { font-size: 14px; margin: 12px 0 8px; padding-bottom: 4px; border-bottom: 1px solid #eee; }
.form-group { margin-bottom: 8px; }
.form-group label { display: block; font-size: 12px; color: #666; margin-bottom: 2px; }
.form-group input, .form-group select, .form-group textarea { width: 100%; padding: 4px 8px; border: 1px solid #ddd; border-radius: 4px; font-size: 13px; }
.form-row { display: flex; gap: 8px; }
.form-row .form-group { flex: 1; }
.stock-picker { display: flex; gap: 4px; align-items: center; }
.stock-picker input { flex: 1; }
.stock-picker button { padding: 4px 8px; font-size: 12px; white-space: nowrap; }
.signals-display { background: #f5f5f5; padding: 8px; border-radius: 4px; margin: 8px 0; font-size: 12px; }
.signal-block { margin-bottom: 4px; }
.tags-display { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
.tag { background: #e3f2fd; color: #1565c0; padding: 2px 8px; border-radius: 12px; font-size: 12px; }
.preset-tags { display: flex; flex-wrap: wrap; gap: 4px; margin: 4px 0 8px; }
.preset-tag { background: #f5f5f5; padding: 2px 8px; border-radius: 8px; font-size: 11px; cursor: pointer; }
.preset-tag:hover { background: #e0e0e0; }
.tag-input-row { display: flex; gap: 4px; margin-bottom: 8px; }
.tag-input-row input { flex: 1; }
.tag-input-row button { padding: 4px 8px; font-size: 12px; }
.btn-save { background: #1565c0; color: #fff; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; margin-top: 8px; }
.btn-delete { background: #c62828; color: #fff; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; margin-top: 16px; }
.stats-panel { display: flex; gap: 16px; padding: 8px 16px; background: #f5f5f5; border-top: 1px solid #e0e0e0; font-size: 13px; }
.screenshots { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
.screenshot-thumb img { max-width: 120px; max-height: 80px; border: 1px solid #ddd; border-radius: 4px; }
</style>
