<!-- src/components/panels/HotlistLimitStocksPanel.vue -->
<!-- 涨停池成分股明细面板（2026-09-25）：热榜概览三容器（热榜池涨停/全市场涨停/昨日热榜涨停）
     点击进入。结构对齐 SectorDetail 三页签语言：涨停概览 / 成分股 / 历史趋势；
     数据源 = /api/hotlist-sentiment/limit-stocks（三份名单）+ hotlist-sentiment/series（历史聚合）。 -->
<template>
  <Teleport to="body">
    <div v-if="visible" class="limit-stocks-panel" :style="panelStyle" ref="panelRef">
      <div class="panel-header">
        <div class="header-left">
          <button class="back-btn" @click="close">← 返回</button>
          <h3>🔥 涨停池明细 <span class="version-badge">v{{ version }}</span></h3>
          <span v-if="dataTimeLabel" class="time-badge" :title="dataTimeTitle">{{ dataTimeLabel }}</span>
        </div>
        <div class="panel-actions">
          <button class="btn-icon" :disabled="detailLoading" title="刷新" @click="reload">
            <span :class="{ 'ls-rotate': detailLoading }">🔄</span>
          </button>
          <button class="btn-icon" title="关闭" @click="close">✕</button>
        </div>
      </div>

      <div class="panel-tabs">
        <div class="tabs-left">
          <button v-for="tab in TABS" :key="tab.key" class="tab-btn" :class="{ active: view === tab.key }"
            @click="view = tab.key">
            {{ tab.icon }} {{ tab.label }}
            <span v-if="tab.key === 'stocks'" class="tab-count">{{ currentRows.length }}</span>
          </button>
        </div>
      </div>

      <div class="kind-selector">
        <button v-for="(label, key) in KIND_LABELS" :key="key" class="kind-btn"
          :class="{ active: kind === key }" @click="setKind(key)">
          {{ label }}
        </button>
      </div>

      <div class="panel-content">
        <div v-if="detailLoading && !detail" class="state-block"><span class="spinner"></span>正在加载涨停池名单…</div>
        <div v-else-if="detailError && !detail" class="state-block error">
          ⚠️ {{ detailError }}
          <button class="retry-btn" @click="reload">重试</button>
        </div>
        <div v-else-if="!detail" class="state-block">暂无涨停池明细数据</div>

        <template v-else>
          <!-- ① 涨停概览：当日聚合卡（summary = 最新日文档 limitEvidence，与热榜概览容器同源） -->
          <section v-show="view === 'overview'" class="tab-pane">
            <div v-if="overviewPrimary.length" class="metrics-grid">
              <div v-for="card in overviewPrimary" :key="card.label" class="metric-card">
                <div class="metric-icon">{{ card.icon }}</div>
                <div class="metric-content">
                  <div class="metric-label">{{ card.label }}</div>
                  <div class="metric-value" :class="card.toneClass">{{ card.value }}</div>
                </div>
              </div>
            </div>
            <div v-if="overviewSecondary.length" class="grid-4">
              <div v-for="card in overviewSecondary" :key="card.label" class="fund-card">
                <div class="fund-content">
                  <div class="fund-label">{{ card.label }}</div>
                  <div class="fund-value" :class="card.toneClass">{{ card.value }}</div>
                </div>
              </div>
            </div>
            <div v-if="!overviewPrimary.length && !overviewSecondary.length" class="empty-row">
              暂无当日聚合数据（summary 缺失）
            </div>
            <div v-if="currentNote" class="note-line">{{ currentNote }}</div>
          </section>

          <!-- ② 成分股：搜索 + 排序 + 名单表（stocks-table 语言） -->
          <section v-show="view === 'stocks'" class="tab-pane">
            <div class="stocks-header">
              <div class="search-box">
                <input v-model="searchKeyword" type="text" class="search-input" placeholder="搜索股票代码或名称..." />
                <span v-if="searchKeyword" class="search-clear" @click="searchKeyword = ''">✕</span>
              </div>
              <div class="sort-controls">
                <select v-model="sortBy" class="sort-select">
                  <option v-for="field in sortFields" :key="field.key" :value="field.key">{{ field.label }}</option>
                </select>
                <button class="sort-btn" @click="sortDesc = !sortDesc">{{ sortDesc ? '↓ 降序' : '↑ 升序' }}</button>
              </div>
            </div>
            <div class="stocks-stats">
              显示 {{ filteredRows.length }} / {{ currentRows.length }} 只
              <span v-if="filteredRows.length !== currentRows.length" class="filter-hint">(过滤后)</span>
            </div>
            <div v-if="filteredRows.length" class="ls-table-container">
              <!-- 热榜池涨停 -->
              <table v-if="kind === 'pool'" class="ls-table">
                <thead>
                  <tr>
                    <th>#</th><th>代码</th><th>名称</th><th>涨跌幅</th><th>排名</th><th>连板</th>
                    <th>主力净额</th><th>状态</th><th>标记</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, i) in sortedPoolRows" :key="row.code" class="zt-row">
                    <td>{{ i + 1 }}</td>
                    <td><span class="ls-code">{{ row.code }}</span></td>
                    <td>{{ row.name || '-' }}</td>
                    <td class="num change" :class="row.change >= 0 ? 'up-text' : 'down-text'">
                      {{ formatPercent(row.change) }}
                    </td>
                    <td class="num">{{ formatNullableCount(row.rank) }}</td>
                    <td class="num">{{ formatBoard(row.boardHeight) }}</td>
                    <td class="num" :class="row.mainNet >= 0 ? 'up-text' : 'down-text'">{{ formatMoney(row.mainNet) }}</td>
                    <td>{{ row.statusLabel || '--' }}</td>
                    <td>
                      <span v-if="row.nearLimitUp" class="ls-badge warn">近涨停</span>
                      <span v-if="row.zhaban" class="ls-badge down">炸板</span>
                      <span v-if="!row.nearLimitUp && !row.zhaban">--</span>
                    </td>
                  </tr>
                </tbody>
              </table>
              <!-- 全市场涨停 -->
              <table v-else-if="kind === 'market'" class="ls-table">
                <thead>
                  <tr>
                    <th>#</th><th>代码</th><th>名称</th><th>涨跌幅</th><th>连板</th><th>首次涨停</th>
                    <th>最后涨停</th><th>换手率</th><th>开板</th><th>涨停原因</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, i) in sortedMarketRows" :key="row.code" class="zt-row">
                    <td>{{ i + 1 }}</td>
                    <td><span class="ls-code">{{ row.code }}</span></td>
                    <td>{{ row.name || '-' }}</td>
                    <td class="num change" :class="changeTone(row.change)">
                      {{ formatPercent(row.change) }}
                    </td>
                    <td class="num">{{ formatBoard(row.boardHeight) }}</td>
                    <td class="num">{{ row.firstLimitUpTime || '--' }}</td>
                    <td class="num">{{ row.lastLimitUpTime || '--' }}</td>
                    <td class="num">{{ typeof row.turnoverRate === 'number' && row.turnoverRate > 0 ? `${row.turnoverRate.toFixed(1)}%` : '--' }}</td>
                    <td class="num">{{ typeof row.openNum === 'number' ? String(row.openNum) : '--' }}</td>
                    <td><span class="ls-reason" :title="row.reasonType || ''">{{ row.reasonType || '--' }}</span></td>
                  </tr>
                </tbody>
              </table>
              <!-- 昨日热榜涨停 -->
              <table v-else class="ls-table">
                <thead>
                  <tr>
                    <th>#</th><th>代码</th><th>名称</th><th>昨日涨幅</th><th>连板</th>
                    <th>今日涨跌幅</th><th>今日排名</th><th>表现</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, i) in sortedYesterdayRows" :key="row.code"
                    :class="{ 'exit-row': !row.matched }">
                    <td>{{ i + 1 }}</td>
                    <td><span class="ls-code">{{ row.code }}</span></td>
                    <td>{{ row.name || '-' }}</td>
                    <td class="num change" :class="row.yesterdayChange >= 0 ? 'up-text' : 'down-text'">
                      {{ formatPercent(row.yesterdayChange) }}
                    </td>
                    <td class="num">{{ formatBoard(row.boardHeight) }}</td>
                    <td class="num change" :class="changeTone(row.todayChange)">
                      {{ row.todayChange === null ? '未匹配' : formatPercent(row.todayChange) }}
                    </td>
                    <td class="num">{{ row.matched ? formatNullableCount(row.todayRank) : '--' }}</td>
                    <td>
                      <span v-if="row.retained" class="ls-badge entry">留榜</span>
                      <span v-if="row.positive" class="ls-badge up">正收益</span>
                      <span v-if="row.weakened" class="ls-badge down">走弱</span>
                      <span v-if="row.failedOrWeak" class="ls-badge warn">冲板失败</span>
                      <span v-if="!row.retained && !row.positive && !row.weakened && !row.failedOrWeak">--</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty-row">无匹配成分股</div>
            <div v-if="currentNote" class="note-line">{{ currentNote }}</div>
          </section>

          <!-- ③ 历史趋势：时间范围 + 指标开关 + ECharts + 统计卡（序列聚合口径） -->
          <section v-show="view === 'history'" class="tab-pane">
            <div class="time-range-selector">
              <button v-for="range in HISTORY_RANGES" :key="range.key" class="time-btn"
                :class="{ active: historyRange === range.key }" @click="setHistoryRange(range.key)">
                {{ range.label }}
              </button>
            </div>
            <div class="indicator-selector">
              <button v-for="ind in currentIndicators" :key="ind.key" class="indicator-btn"
                :class="{ active: historyIndicators.includes(ind.key) }" @click="toggleHistoryIndicator(ind.key)">
                {{ ind.icon }} {{ ind.label }}
              </button>
            </div>
            <div v-if="historyNote" class="note-line">{{ historyNote }}</div>
            <div v-if="!historyPoints.length" class="empty-row">暂无历史序列数据</div>
            <template v-else>
              <div class="ls-chart" ref="historyChartRef"></div>
              <div class="ls-stats-grid">
                <div v-for="card in historyStats" :key="card.label" class="ls-stat-card">
                  <div class="stat-label">{{ card.label }}</div>
                  <div class="stat-value">{{ card.value }}</div>
                  <div class="stat-time">{{ card.sub }}</div>
                </div>
              </div>
            </template>
          </section>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { HotListLimitEvidence } from '@/types/hotlistSentiment'
import {
  fetchHotlistLimitStocks,
  fetchHotlistSentimentSeries,
  type HotlistLimitStockKind,
  type HotlistMarketLimitStockRow,
  type HotlistPoolLimitStockRow,
  type HotlistYesterdayLimitStockRow,
} from '@/services/hotlist/hotlistSentimentApi'

const props = defineProps<{
  visible: boolean
  initialKind: HotlistLimitStockKind
  summary: HotListLimitEvidence | null
  triggerRect?: DOMRect | null
}>()
const emit = defineEmits<{ (e: 'close'): void }>()

const version = '6.0.0'
const TABS = [
  { key: 'overview', label: '涨停概览', icon: '📊' },
  { key: 'stocks', label: '成分股', icon: '📋' },
  { key: 'history', label: '历史趋势', icon: '📈' },
] as const
type ViewKey = (typeof TABS)[number]['key']

const KIND_LABELS: Record<HotlistLimitStockKind, string> = {
  pool: '🔥 热榜池涨停',
  market: '🌐 全市场涨停',
  yesterday: '📜 昨日热榜涨停',
}

// ---------- 基础格式化（fail-visible：缺失显示 --，不伪造 0） ----------
function formatNullableCount(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(Math.round(value)) : '--'
}
function formatShare(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 100)}%` : '--'
}
function formatPercent(value?: number | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}
function formatMoney(value?: number | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--'
  const abs = Math.abs(value)
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(value / 1e4).toFixed(0)}万`
  return String(Math.round(value))
}
function formatBoard(height?: number | null): string {
  if (typeof height !== 'number' || !Number.isFinite(height) || height <= 0) return '--'
  return `${height}板`
}
function changeTone(value: number | null): string {
  if (value === null) return ''
  return value >= 0 ? 'up-text' : 'down-text'
}

// ECharts 画布不解析 CSS 变量，渲染时取计算值（主题切换后下一次渲染生效）
function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

// ---------- 面板状态 ----------
const view = ref<ViewKey>('stocks')
const kind = ref<HotlistLimitStockKind>(props.initialKind)
const detail = ref<Awaited<ReturnType<typeof fetchHotlistLimitStocks>> | null>(null)
const detailLoading = ref(false)
const detailError = ref<string | null>(null)
const searchKeyword = ref('')
const sortBy = ref('')
const sortDesc = ref(true)

const panelRef = ref<HTMLElement | null>(null)

const panelStyle = computed(() => {
  const rect = props.triggerRect
  const width = 900
  if (!rect) return { left: `${Math.max(8, (window.innerWidth - width) / 2)}px`, top: '48px' }
  const left = Math.max(8, Math.min(window.innerWidth - width - 8, rect.left + rect.width / 2 - width / 2))
  return { left: `${left}px`, top: `${Math.max(8, Math.min(rect.top, window.innerHeight - 620))}px` }
})

const dataTimeLabel = computed(() => {
  if (!detail.value?.tradingDate) return ''
  const marketNote = detail.value.market.degraded ? ' · 市场名单降级' : ''
  return `${detail.value.tradingDate}${marketNote}`
})
const dataTimeTitle = computed(() => {
  const parts = [`交易日: ${detail.value?.tradingDate || '--'}`]
  if (detail.value?.prevTradingDate) parts.push(`上一交易日: ${detail.value.prevTradingDate}`)
  if (detail.value?.reason) parts.push(`reason: ${detail.value.reason}`)
  return parts.join('\n')
})

async function loadDetail() {
  if (detailLoading.value) return
  detailLoading.value = true
  detailError.value = null
  try {
    const result = await fetchHotlistLimitStocks()
    detail.value = result
    if (!result.ok && result.reason) detailError.value = result.reason
    // detail 晚于历史序列完成时，图表容器此刻才挂载，需补一次渲染
    if (view.value === 'history') nextTick(() => renderHistoryChart())
  } catch (err) {
    detailError.value = err instanceof Error ? err.message : '加载失败'
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

function reload() {
  void loadDetail()
  void loadHistory()
}

function setKind(next: HotlistLimitStockKind) {
  if (kind.value === next) return
  kind.value = next
  searchKeyword.value = ''
  sortBy.value = ''
  // 指标开关按新池默认值重置，历史图表重渲染
  historyIndicators.value = defaultIndicators(next)
  if (view.value === 'history' && historyPoints.value.length) {
    nextTick(() => renderHistoryChart())
  }
}

function close() {
  emit('close')
}

// ---------- 当前名单行 ----------
const currentRows = computed<any[]>(() => {
  if (!detail.value) return []
  if (kind.value === 'pool') return detail.value.pool.rows
  if (kind.value === 'market') return detail.value.market.rows
  return detail.value.yesterday.rows
})

const currentNote = computed(() => {
  if (!detail.value) return ''
  const notes: string[] = []
  if (kind.value === 'market' && detail.value.market.degraded) {
    notes.push(`全市场名单降级：${detail.value.market.reason || '未知原因'}`)
  }
  for (const item of detail.value.diagnostics) notes.push(item)
  return notes.join('；')
})

// 排序字段定义（按池类型）
const sortFields = computed(() => {
  if (kind.value === 'pool') {
    return [
      { key: 'change', label: '涨跌幅' },
      { key: 'rank', label: '排名' },
      { key: 'boardHeight', label: '连板' },
      { key: 'mainNet', label: '主力净额' },
    ]
  }
  if (kind.value === 'market') {
    return [
      { key: 'change', label: '涨跌幅' },
      { key: 'boardHeight', label: '连板' },
      { key: 'turnoverRate', label: '换手率' },
      { key: 'openNum', label: '开板次数' },
    ]
  }
  return [
    { key: 'todayChange', label: '今日涨跌幅' },
    { key: 'yesterdayChange', label: '昨日涨幅' },
    { key: 'boardHeight', label: '连板' },
    { key: 'rank', label: '昨日排名' },
  ]
})

function rowValue(row: any, key: string): number {
  const value = row[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : -Infinity
}

const sortedPoolRows = computed<HotlistPoolLimitStockRow[]>(() => filterAndSort(detail.value?.pool.rows ?? []))
const sortedMarketRows = computed<HotlistMarketLimitStockRow[]>(() => filterAndSort(detail.value?.market.rows ?? []))
const sortedYesterdayRows = computed<HotlistYesterdayLimitStockRow[]>(() =>
  filterAndSort(detail.value?.yesterday.rows ?? []),
)
// 当前池类型过滤+排序后的行（页签统计行用）
const filteredRows = computed<any[]>(() => {
  if (kind.value === 'pool') return sortedPoolRows.value
  if (kind.value === 'market') return sortedMarketRows.value
  return sortedYesterdayRows.value
})

function filterAndSort<T>(rows: T[]): T[] {
  let result = rows
  const keyword = searchKeyword.value.trim().toLowerCase()
  if (keyword) {
    result = result.filter((row: any) => {
      const code = String(row.code || '').toLowerCase()
      const name = String(row.name || '').toLowerCase()
      return code.includes(keyword) || name.includes(keyword)
    })
  }
  const key = sortBy.value
  if (!key) return result
  return [...result].sort((a: any, b: any) => {
    const av = rowValue(a, key)
    const bv = rowValue(b, key)
    return sortDesc.value ? bv - av : av - bv
  })
}

// 缺省排序：打开即按当前排序字段首项降序
watch(sortFields, (fields) => {
  if (!sortBy.value && fields.length) sortBy.value = fields[0].key
}, { immediate: true })

// ---------- 涨停概览卡（summary 与热榜概览容器同源：最新日文档 limitEvidence） ----------
interface OverviewCard { icon: string; label: string; value: string; toneClass?: string }

const overviewPrimary = computed<OverviewCard[]>(() => {
  const s = props.summary
  if (!s) return []
  if (kind.value === 'pool') {
    const it = s.intersection
    return [
      { icon: '📈', label: '全池涨停', value: `${formatNullableCount(it.top100LimitUpCount)}（${formatShare(it.top100LimitUpShare)}）`, toneClass: 'up' },
      { icon: '🔥', label: '近涨停', value: formatNullableCount(it.top100NearLimitUpCount) },
      { icon: '🧱', label: '二板以上', value: formatNullableCount(it.top100Board2PlusCount) },
      { icon: '🏆', label: '最高板', value: `${formatNullableCount(it.top100MaxBoardHeight)} 板` },
    ]
  }
  if (kind.value === 'market') {
    const m = s.market
    return [
      { icon: '📈', label: '全市场涨停', value: formatNullableCount(m.ztCount), toneClass: 'up' },
      { icon: '🏦', label: '封板率', value: typeof m.fengbanRate === 'number' ? `${m.fengbanRate.toFixed(0)}%` : '--' },
      { icon: '💥', label: '全市场炸板', value: formatNullableCount(m.zhabanCount), toneClass: 'down' },
      { icon: '🏆', label: '最高连板', value: `${formatNullableCount(m.maxContinuousDays)} 板` },
    ]
  }
  const y = s.yesterdayHotLimit
  return [
    { icon: '📋', label: '昨日涨停数', value: formatNullableCount(y.count) },
    { icon: '🔁', label: '留榜数', value: formatNullableCount(y.retainedTop100Count) },
    { icon: '💹', label: '今日均涨', value: formatPercent(y.avgChange), toneClass: changeTone(y.avgChange) },
    { icon: '💪', label: '正收益率', value: formatShare(y.positiveRate), toneClass: 'up' },
  ]
})

const overviewSecondary = computed<OverviewCard[]>(() => {
  const s = props.summary
  if (!s) return []
  if (kind.value === 'pool') {
    const it = s.intersection
    return [
      { icon: '📊', label: '前50 涨停', value: formatNullableCount(it.top50LimitUpCount) },
      { icon: '📊', label: '前20 涨停', value: formatNullableCount(it.top20LimitUpCount) },
      { icon: '💥', label: '池内炸板', value: `${formatNullableCount(it.top100ZhabanCount)}（${formatShare(it.top100ZhabanShare)}）`, toneClass: 'down' },
    ]
  }
  if (kind.value === 'market') {
    const m = s.market
    return [
      { icon: '🥇', label: '首板', value: formatNullableCount(m.board1) },
      { icon: '🥈', label: '2板', value: formatNullableCount(m.board2) },
      { icon: '🥉', label: '3板', value: formatNullableCount(m.board3) },
      { icon: '🏅', label: '4板+', value: formatNullableCount(m.board4Plus) },
      { icon: '💥', label: 'THS 炸板池', value: formatNullableCount(m.thsPools?.failedCount), toneClass: 'down' },
      { icon: '📉', label: 'THS 回撤榜', value: formatNullableCount(m.thsPools?.drawdownCount), toneClass: 'down' },
    ]
  }
  const y = s.yesterdayHotLimit
  return [
    { icon: '📈', label: '正收益率', value: formatShare(y.positiveRate), toneClass: 'up' },
    { icon: '📉', label: '走弱率', value: formatShare(y.weakeningRate), toneClass: 'down' },
    { icon: '💥', label: '冲板失败率', value: formatShare(y.failedOrWeakRate), toneClass: 'down' },
  ]
})

// ---------- 历史趋势（序列聚合：series 日文档 limitEvidence，与三容器聚合同源） ----------
const HISTORY_RANGES = [
  { key: '3d', label: '3日', days: 3 },
  { key: '1w', label: '1周', days: 5 },
  { key: '1m', label: '1月', days: 20 },
] as const
type HistoryRangeKey = (typeof HISTORY_RANGES)[number]['key']

interface HistoryIndicator {
  key: string
  label: string
  icon: string
  type: 'bar' | 'line'
  color: string
  axis: 0 | 1
  unit: '%' | ''
  pick: (doc: Awaited<ReturnType<typeof fetchHotlistSentimentSeries>>['items'][number]) => number | null
}

function rate(rate?: number | null): number | null {
  return typeof rate === 'number' ? Math.round(rate * 1000) / 10 : null
}

const INDICATOR_SETS: Record<HotlistLimitStockKind, HistoryIndicator[]> = {
  pool: [
    { key: 'limitUp', label: '涨停数', icon: '📈', type: 'bar', color: '#ff4757', axis: 0, unit: '', pick: (d) => d.metrics?.limitEvidence?.intersection?.top100LimitUpCount ?? null },
    { key: 'near', label: '近涨停', icon: '🔥', type: 'bar', color: '#ff7f50', axis: 0, unit: '', pick: (d) => d.metrics?.limitEvidence?.intersection?.top100NearLimitUpCount ?? null },
    { key: 'board2', label: '二板以上', icon: '🧱', type: 'bar', color: '#ffd700', axis: 0, unit: '', pick: (d) => d.metrics?.limitEvidence?.intersection?.top100Board2PlusCount ?? null },
    { key: 'zhaban', label: '炸板', icon: '💥', type: 'bar', color: '#2ed573', axis: 0, unit: '', pick: (d) => d.metrics?.limitEvidence?.intersection?.top100ZhabanCount ?? null },
  ],
  market: [
    { key: 'zt', label: '涨停数', icon: '📈', type: 'bar', color: '#ff4757', axis: 0, unit: '', pick: (d) => d.metrics?.limitEvidence?.market?.ztCount ?? null },
    { key: 'zhaban', label: '炸板数', icon: '💥', type: 'bar', color: '#2ed573', axis: 0, unit: '', pick: (d) => d.metrics?.limitEvidence?.market?.zhabanCount ?? null },
    { key: 'fengban', label: '封板率', icon: '🏦', type: 'line', color: '#4a90e2', axis: 1, unit: '%', pick: (d) => d.metrics?.limitEvidence?.market?.fengbanRate ?? null },
    { key: 'board1', label: '首板', icon: '🥇', type: 'bar', color: '#ffb142', axis: 0, unit: '', pick: (d) => d.metrics?.limitEvidence?.market?.board1 ?? null },
  ],
  yesterday: [
    { key: 'count', label: '名单数', icon: '📋', type: 'bar', color: '#ffd700', axis: 0, unit: '', pick: (d) => d.metrics?.limitEvidence?.yesterdayHotLimit?.count ?? null },
    { key: 'retained', label: '留榜数', icon: '🔁', type: 'bar', color: '#4a90e2', axis: 0, unit: '', pick: (d) => d.metrics?.limitEvidence?.yesterdayHotLimit?.retainedTop100Count ?? null },
    { key: 'positive', label: '正收益率', icon: '💪', type: 'line', color: '#ff4757', axis: 1, unit: '%', pick: (d) => rate(d.metrics?.limitEvidence?.yesterdayHotLimit?.positiveRate) },
    { key: 'weaken', label: '走弱率', icon: '📉', type: 'line', color: '#2ed573', axis: 1, unit: '%', pick: (d) => rate(d.metrics?.limitEvidence?.yesterdayHotLimit?.weakeningRate) },
    { key: 'failed', label: '冲板失败率', icon: '💥', type: 'line', color: '#ffb142', axis: 1, unit: '%', pick: (d) => rate(d.metrics?.limitEvidence?.yesterdayHotLimit?.failedOrWeakRate) },
  ],
}

const DEFAULT_INDICATORS: Record<HotlistLimitStockKind, string[]> = {
  pool: ['limitUp', 'near', 'zhaban'],
  market: ['zt', 'zhaban', 'fengban'],
  yesterday: ['count', 'retained', 'positive'],
}

function defaultIndicators(next: HotlistLimitStockKind): string[] {
  return [...DEFAULT_INDICATORS[next]]
}

const currentIndicators = computed(() => INDICATOR_SETS[kind.value])
const historyRange = ref<HistoryRangeKey>('3d')
const historyIndicators = ref<string[]>(defaultIndicators(props.initialKind))
const historyDocs = ref<Awaited<ReturnType<typeof fetchHotlistSentimentSeries>>['items']>([])
const historyLoading = ref(false)
const historyError = ref<string | null>(null)
const historyLoaded = ref(false)
const historyChartRef = ref<HTMLElement | null>(null)
let historyChart: echarts.ECharts | null = null
// 代际守卫：快速连切档位时旧响应直接丢弃，最新请求独占缓存写入权
let historyReqId = 0

const historyPoints = computed(() => {
  const days = HISTORY_RANGES.find((r) => r.key === historyRange.value)?.days ?? 3
  return historyDocs.value.slice(-days)
})

const historyNote = computed(() => {
  if (historyLoading.value) return '正在加载历史序列…'
  if (historyError.value) return `历史序列不可用：${historyError.value}`
  if (!historyPoints.value.length) return ''
  const pts = historyPoints.value
  const rangeLabel = pts.length > 1 ? `${pts[0].tradingDate?.slice(5)} ~ ${pts[pts.length - 1].tradingDate?.slice(5)}` : pts[0].tradingDate || ''
  return `${rangeLabel} · 日线口径（EOD 终值）`
})

async function loadHistory() {
  const reqId = ++historyReqId
  historyLoading.value = true
  historyError.value = null
  try {
    const days = HISTORY_RANGES.find((r) => r.key === historyRange.value)?.days ?? 3
    const result = await fetchHotlistSentimentSeries(days)
    if (reqId !== historyReqId) return // 已有更新请求在途，过期响应丢弃
    if (result.degraded || !result.items.length) {
      historyError.value = result.reason || '热榜情绪序列暂不可用'
      historyDocs.value = []
      return
    }
    historyDocs.value = result.items
    historyLoaded.value = true
  } catch (err) {
    if (reqId !== historyReqId) return
    historyError.value = err instanceof Error ? err.message : '加载历史序列失败'
  } finally {
    if (reqId === historyReqId) {
      historyLoading.value = false
      if (view.value === 'history') nextTick(() => renderHistoryChart())
    }
  }
}

function setHistoryRange(range: HistoryRangeKey) {
  if (historyRange.value === range) return
  historyRange.value = range
  void loadHistory()
}

function toggleHistoryIndicator(key: string) {
  const current = historyIndicators.value
  if (current.includes(key)) {
    if (current.length === 1) return // 至少保留一个序列，避免图表空白
    historyIndicators.value = current.filter((k) => k !== key)
  } else {
    // 按声明顺序重排，保持图例顺序稳定
    historyIndicators.value = currentIndicators.value
      .map((i) => i.key)
      .filter((k) => current.includes(k) || k === key)
  }
  nextTick(() => renderHistoryChart())
}

function renderHistoryChart() {
  if (!historyChartRef.value || !historyPoints.value.length) return
  // 空态 v-if 切换会卸载并重挂图表容器：旧实例绑定的 DOM 已分离，必须 dispose 后重建
  if (historyChart && historyChart.getDom() !== historyChartRef.value) {
    historyChart.dispose()
    historyChart = null
  }
  if (!historyChart) {
    historyChart = echarts.init(historyChartRef.value)
  }

  const points = historyPoints.value
  const active = currentIndicators.value.filter((ind) => historyIndicators.value.includes(ind.key))
  const series = active.map((ind) => {
    const data = points.map((doc) => ind.pick(doc))
    if (ind.type === 'bar') {
      return { name: ind.label, type: 'bar', data, itemStyle: { color: ind.color }, barWidth: 8, yAxisIndex: ind.axis }
    }
    return {
      name: ind.label,
      type: 'line',
      data,
      smooth: true,
      symbol: 'circle',
      symbolSize: 5,
      connectNulls: false,
      lineStyle: { color: ind.color, width: 2 },
      yAxisIndex: ind.axis,
    }
  })

  const textColor = cssVar('--text-secondary', '#9aa0a6')
  const borderColor = cssVar('--border-color', '#333333')
  const fmt: Record<string, string> = {}
  for (const ind of active) fmt[ind.label] = ind.unit

  historyChart.setOption(
    {
      grid: { left: '8%', right: '8%', top: '15%', bottom: '10%', containLabel: true },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        confine: true,
        formatter: (params: any) => {
          const list = Array.isArray(params) ? params : [params]
          if (!list.length) return ''
          const idx = list[0].dataIndex
          const doc = points[idx]
          const rows = list
            .map((it: any) => {
              const value = typeof it.value === 'object' ? it.value?.value : it.value
              const unit = fmt[it.seriesName] ?? ''
              const text = value === null || value === undefined ? '--' : `${value}${unit}`
              return `<div>${it.marker}${it.seriesName}：${text}</div>`
            })
            .join('')
          const stageColor = cssVar('--color-highlight', '#ffb142')
          const stage = doc?.stage ? `<div style="color:${stageColor};margin-bottom:4px;">阶段：${doc.stage}</div>` : ''
          const date = doc?.tradingDate || ''
          return `<div style="font-weight:600;margin-bottom:4px;">${date}</div>${stage}${rows}`
        },
      },
      legend: {
        data: series.map((s) => s.name),
        bottom: 0,
        itemWidth: 12,
        itemHeight: 8,
        textStyle: { color: textColor, fontSize: 10 },
      },
      xAxis: {
        type: 'category',
        data: points.map((doc) => (doc.tradingDate || '').slice(5) || '--'),
        axisLabel: { color: textColor, fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: borderColor } },
      },
      yAxis: [
        {
          type: 'value',
          name: '数量',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { lineStyle: { color: borderColor, type: 'dashed' } },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: '%',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
      ],
      series,
      backgroundColor: 'transparent',
    },
    // 指标开关减少序列时必须整体替换，merge 模式下旧序列会残留
    { notMerge: true },
  )
  historyChart.resize()
}

// 图下统计卡：按当前池类型给出均值/峰值，缺失 '--'
const historyStats = computed(() => {
  const pts = historyPoints.value
  const valuesOf = (key: string) => {
    const ind = currentIndicators.value.find((i) => i.key === key)
    if (!ind) return [] as Array<number | null>
    return pts.map((doc) => ind.pick(doc))
  }
  const nonNull = (values: Array<number | null>) => values.filter((v): v is number => v !== null)
  const avgOf = (values: Array<number | null>) => {
    const nums = nonNull(values)
    return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null
  }
  const peakOf = (values: Array<number | null>) => {
    const nums = nonNull(values)
    if (!nums.length) return null
    const max = Math.max(...nums)
    const index = values.indexOf(max)
    return { value: max, date: pts[index]?.tradingDate?.slice(5) || '' }
  }
  const sub = pts.length ? `共 ${pts.length} 日` : ''
  const card = (label: string, value: number | null, unit: string, time = '') => ({
    label,
    value: value === null ? '--' : `${unit === '%' ? value.toFixed(1) : Math.round(value)}${unit}`,
    sub: time || sub,
  })
  if (kind.value === 'pool') {
    const peak = peakOf(valuesOf('limitUp'))
    return [
      { label: '涨停峰值', value: peak?.value === null || peak === null ? '--' : String(peak.value), sub: peak?.date || sub },
      card('平均涨停数', avgOf(valuesOf('limitUp')), ''),
      card('平均近涨停', avgOf(valuesOf('near')), ''),
      card('平均炸板', avgOf(valuesOf('zhaban')), ''),
    ]
  }
  if (kind.value === 'market') {
    const peak = peakOf(valuesOf('zt'))
    return [
      { label: '涨停峰值', value: peak?.value === null || peak === null ? '--' : String(peak.value), sub: peak?.date || sub },
      card('平均涨停数', avgOf(valuesOf('zt')), ''),
      card('平均封板率', avgOf(valuesOf('fengban')), '%'),
      card('炸板峰值', (() => { const p = peakOf(valuesOf('zhaban')); return p?.value ?? null })(), '', (() => { const p = peakOf(valuesOf('zhaban')); return p?.date || '' })()),
    ]
  }
  const peak = peakOf(valuesOf('count'))
  return [
    { label: '名单峰值', value: peak?.value === null || peak === null ? '--' : String(peak.value), sub: peak?.date || sub },
    card('平均留榜数', avgOf(valuesOf('retained')), ''),
    card('平均正收益率', avgOf(valuesOf('positive')), '%'),
    card('平均走弱率', avgOf(valuesOf('weaken')), '%'),
  ]
})

// 具名 handler：卸载时移除，避免面板反复开关累积监听器
function handleHistoryChartResize() {
  if (historyChart) historyChart.resize()
}
onMounted(() => {
  window.addEventListener('resize', handleHistoryChartResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', handleHistoryChartResize)
  if (historyChart) {
    historyChart.dispose()
    historyChart = null
  }
})

// 页签/数据变化时渲染历史图表（detail 并入 source：容器晚于序列挂载时补渲染）
watch([view, historyPoints, historyIndicators, detail], ([v]) => {
  if (v === 'history') {
    nextTick(() => renderHistoryChart())
  }
})

// 面板打开：重置到成分股页签并按需加载数据（放在脚本末尾，避免 immediate 回调触碰未初始化状态）
watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      kind.value = props.initialKind
      view.value = 'stocks'
      searchKeyword.value = ''
      if (!detail.value) loadDetail()
      if (!historyLoaded.value) loadHistory()
    }
  },
  { immediate: true },
)
</script>

<style scoped>
/* ========== 面板基础（token 对齐 HotlistEmotionPanel/SectorDetail） ========== */
.limit-stocks-panel {
  position: fixed;
  width: 900px;
  max-width: calc(100vw - 40px);
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10007;
  font-size: 12px;
  overflow: hidden;
  backdrop-filter: blur(10px);
  color: var(--text-primary);
}

/* ========== 头部 ========== */
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}
.header-left { display: flex; align-items: center; gap: 12px; }
.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-highlight);
  display: flex;
  align-items: center;
  gap: 8px;
}
.version-badge {
  font-size: 10px;
  background: var(--color-highlight);
  color: #000;
  padding: 2px 6px;
  border-radius: 12px;
}
.time-badge {
  font-size: 10px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  padding: 2px 6px;
  border-radius: 12px;
  cursor: help;
}
.back-btn {
  padding: 4px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.back-btn:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
  color: var(--color-highlight);
}
.panel-actions { display: flex; gap: 8px; }
.btn-icon {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}
.btn-icon:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}
.btn-icon:disabled { opacity: 0.5; cursor: not-allowed; }
.ls-rotate { display: inline-block; animation: ls-rotate 1s linear infinite; }
@keyframes ls-rotate { to { transform: rotate(360deg); } }

/* ========== 页签 + 池类型选择 ========== */
.panel-tabs {
  display: flex;
  padding: 12px 20px 0;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}
.tabs-left { display: flex; gap: 4px; flex: 1; }
.tab-btn {
  flex: 1;
  padding: 8px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 8px;
  font-size: 12px;
  transition: all 0.2s;
}
.tab-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.tab-btn.active { background: var(--color-highlight); color: #000; font-weight: 500; }
.tab-count {
  margin-left: 4px;
  padding: 0 4px;
  background: rgba(0, 0, 0, 0.1);
  border-radius: 8px;
  font-size: 9px;
}
.kind-selector { display: flex; gap: 8px; padding: 10px 20px; background: var(--bg-secondary); border-bottom: 1px solid var(--border-color); }
.kind-btn {
  padding: 4px 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.kind-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.kind-btn.active { background: var(--color-highlight); border-color: var(--color-highlight); color: #000; }

/* ========== 内容区 ========== */
.panel-content {
  padding: 16px 20px 20px;
  max-height: calc(85vh - 190px);
  overflow-y: auto;
}
.tab-pane { display: flex; flex-direction: column; gap: 16px; }
.state-block {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 16px; padding: 60px 20px; color: var(--text-secondary);
}
.state-block.error { color: #ff4757; }
.spinner {
  width: 40px; height: 40px; border: 3px solid var(--border-color);
  border-top-color: var(--color-highlight); border-radius: 50%;
  animation: ls-rotate 0.8s linear infinite;
}
.retry-btn {
  background: var(--color-highlight); color: #000; border: none;
  border-radius: 16px; padding: 4px 12px; cursor: pointer; font-size: 12px;
}
.empty-row { color: var(--text-secondary); text-align: center; padding: 8px 0; }
.note-line { font-size: 11px; color: #ffb142; }

/* ========== 概览卡（三级卡体系） ========== */
.metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.metric-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
}
.metric-icon {
  font-size: 28px;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  border-radius: 24px;
  flex-shrink: 0;
}
.metric-content { flex: 1; min-width: 0; }
.metric-label { font-size: 11px; color: var(--text-secondary); margin-bottom: 4px; }
.metric-value { font-size: 22px; font-weight: bold; line-height: 1.2; font-variant-numeric: tabular-nums; }
.metric-value.up { color: #ff4757; }
.metric-value.down { color: #2ed573; }
.grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.fund-card {
  display: flex;
  align-items: center;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
}
.fund-label { font-size: 10px; color: var(--text-secondary); margin-bottom: 2px; }
.fund-value { font-size: 14px; font-weight: bold; font-variant-numeric: tabular-nums; }
.fund-value.up { color: #ff4757; }
.fund-value.down { color: #2ed573; }

/* ========== 成分股表（stocks-table 语言） ========== */
.stocks-header {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.search-box { position: relative; flex: 1; min-width: 200px; }
.search-input {
  width: 100%;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  color: var(--text-primary);
  font-size: 12px;
}
.search-input:focus { outline: none; border-color: var(--color-highlight); }
.search-clear {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 0 4px;
}
.search-clear:hover { color: var(--text-primary); }
.sort-controls { display: flex; gap: 4px; }
.sort-select {
  padding: 6px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  cursor: pointer;
}
.sort-select:hover { border-color: var(--color-highlight); }
.sort-btn {
  padding: 6px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.sort-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.stocks-stats {
  padding: 8px 12px;
  background: var(--bg-tertiary, var(--bg-secondary));
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-primary);
  font-weight: 500;
}
.filter-hint { font-size: 11px; color: var(--text-secondary); margin-left: 4px; }
.ls-table-container {
  max-height: 480px;
  overflow-y: auto;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-primary);
}
.ls-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ls-table th {
  position: sticky;
  top: 0;
  background: var(--bg-header);
  padding: 10px 6px;
  text-align: left;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 2px solid var(--border-color);
  white-space: nowrap;
  z-index: 1;
}
.ls-table td { padding: 8px 6px; border-bottom: 1px solid var(--border-color); white-space: nowrap; }
.ls-table tbody tr { cursor: default; transition: background 0.2s; }
.ls-table tbody tr:hover { background: var(--bg-hover); }
.ls-table tbody tr.zt-row { background: rgba(255, 71, 87, 0.08); }
.ls-table tbody tr.exit-row { background: rgba(46, 213, 115, 0.08); }
.ls-table .num { font-variant-numeric: tabular-nums; text-align: right; }
.ls-code {
  color: var(--color-highlight);
  text-decoration: underline;
  text-decoration-color: rgba(255, 127, 80, 0.5);
  font-weight: 500;
}
.ls-table .up-text { color: #ff4757; }
.ls-table .down-text { color: #2ed573; }
.ls-badge {
  padding: 2px 6px;
  border-radius: 10px;
  font-size: 10px;
  margin-right: 2px;
  display: inline-block;
}
.ls-badge.up { background: rgba(255, 71, 87, 0.15); color: #ff4757; }
.ls-badge.down { background: rgba(46, 213, 115, 0.15); color: #2ed573; }
.ls-badge.warn { background: rgba(255, 177, 66, 0.15); color: #ffb142; }
.ls-badge.entry { background: rgba(74, 144, 226, 0.15); color: #4a90e2; }
.ls-reason {
  display: inline-block;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
  color: var(--text-secondary);
}

/* ========== 历史趋势（时间范围/指标开关/图表/统计卡） ========== */
.time-range-selector, .indicator-selector { display: flex; gap: 8px; flex-wrap: wrap; }
.time-btn, .indicator-btn {
  padding: 4px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.time-btn:hover, .indicator-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.time-btn.active, .indicator-btn.active { background: var(--color-highlight); border-color: var(--color-highlight); color: #000; }
.ls-chart {
  height: 250px;
  width: 100%;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 10px;
}
.ls-stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.ls-stat-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 12px;
  text-align: center;
}
.ls-stat-card .stat-label { font-size: 10px; color: var(--text-secondary); margin-bottom: 4px; }
.ls-stat-card .stat-value {
  font-size: 18px; font-weight: bold; color: var(--text-title);
  line-height: 1.2; font-variant-numeric: tabular-nums;
}
.ls-stat-card .stat-time { font-size: 9px; color: var(--text-secondary); margin-top: 4px; min-height: 12px; }

@media (max-width: 720px) {
  .metrics-grid, .grid-4 { grid-template-columns: repeat(2, 1fr); }
  .limit-stocks-panel { width: calc(100vw - 16px); }
}
</style>
