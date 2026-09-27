<template>
  <div class="sector-rotation-tab">
    <div class="rotation-toolbar">
      <span class="rotation-updated">{{ dataTimeText }}</span>
      <button class="refresh-btn" :class="{ loading }" title="刷新" @click="loadData(true)">
        <span :class="{ 'rotate-animation': loading }">🔄</span>
      </button>
    </div>

    <div v-if="error" class="rotation-error">
      <span>⚠️</span>
      <span>{{ error }}</span>
      <button class="retry-btn" @click="loadData(true)">重试</button>
    </div>
    <div v-else-if="!summary" class="rotation-empty">
      <span>{{ loading ? '加载中…' : '暂无轮动数据' }}</span>
      <button v-if="!loading" class="retry-btn" @click="loadData(true)">重试</button>
    </div>

    <template v-else>
      <section class="rotation-summary">
        <div class="summary-row phase-row">
          <span class="phase-badge" :class="phaseTone">{{ phaseLabel }}</span>
          <span class="summary-metric">轮动速度 {{ formatNumber(rotationSummary?.rotationSpeed, 2) }}</span>
          <span class="summary-metric">主线集中度 {{ formatPercent(rotationSummary?.mainlineConcentration) }}</span>
          <span class="summary-metric">最高连板 {{ formatNumber(rotationSummary?.maxBoardHeight, 0) }}</span>
        </div>
        <div class="summary-row">
          <span class="row-label">主线</span>
          <template v-if="mainLineNames.length">
            <span v-for="name in mainLineNames" :key="name" class="theme-chip chip-mainline">{{ name }}</span>
          </template>
          <span v-else class="no-mainline">引擎判定无主线</span>
        </div>
        <div class="summary-row">
          <span class="row-label">流入</span>
          <span v-for="theme in inflowPreview" :key="theme.themeId" class="theme-chip chip-inflow">{{ theme.themeName }}</span>
          <span v-if="inflowRestCount > 0" class="chip-rest">等 {{ inflowRestCount }}</span>
          <span v-if="!inflowThemes.length" class="row-empty">—</span>
        </div>
        <div class="summary-row">
          <span class="row-label">流出</span>
          <span v-for="theme in outflowPreview" :key="theme.themeId" class="theme-chip chip-outflow">{{ theme.themeName }}</span>
          <span v-if="outflowRestCount > 0" class="chip-rest">等 {{ outflowRestCount }}</span>
          <span v-if="!outflowThemes.length" class="row-empty">—</span>
        </div>
        <div class="summary-row state-distribution">
          <span class="row-label">分布</span>
          <span v-for="bucket in stateBuckets" :key="bucket.state" class="state-count" :class="stateToneOf(bucket.state)">
            {{ stateLabelOf(bucket.state) }} {{ bucket.count }}
          </span>
        </div>
      </section>

      <section class="rotation-tree-section">
        <SectorRotationTree
          :statuses="statuses"
          :category="stateFilter"
          @update:category="stateFilter = $event"
        />
      </section>

      <section class="rotation-table-section">
        <button class="table-toggle" @click="tableOpen = !tableOpen">
          {{ tableOpen ? '收起题材状态表' : `展开题材状态表（${statuses.length}）` }}
        </button>
        <div v-if="tableOpen" class="rotation-table-wrap">
          <table class="rotation-table">
            <thead>
              <tr>
                <th
                  v-for="col in columns"
                  :key="col.key"
                  :class="{ sortable: col.sortable, sorted: sortKey === col.key }"
                  @click="col.sortable && toggleSort(col.key)"
                >
                  {{ col.label }}<span v-if="col.sortable && sortKey === col.key">{{ sortDir === 1 ? ' ▲' : ' ▼' }}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in visibleRows" :key="row.entityKey">
                <td>{{ row.entityName }}</td>
                <td>{{ row.rank ?? '—' }}</td>
                <td :class="trendClass(row.rankChange)">{{ formatSigned(row.rankChange) }}</td>
                <td><span class="state-badge" :class="stateToneOf(row.rotationState)">{{ stateLabelOf(row.rotationState) }}</span></td>
                <td>{{ formatNumber(row.rotationScore, 1) }}</td>
                <td>{{ formatNumber(row.factorBreakdown?.strength, 1) }}</td>
                <td>{{ formatNumber(row.factorBreakdown?.flow, 1) }}</td>
                <td>{{ formatNumber(row.factorBreakdown?.breadth, 1) }}</td>
                <td>{{ formatNumber(row.factorBreakdown?.crowding, 1) }}</td>
                <td :class="trendClass(row.flowTrend)">{{ formatFlowTrend(row.flowTrend) }}</td>
                <td>{{ row.qualityFlags?.length ? row.qualityFlags.join(',') : '—' }}</td>
              </tr>
              <tr v-if="visibleRows.length === 0">
                <td colspan="11" class="row-empty">该筛选下无题材</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  getRotationSummary,
  type ThemeRotationStatusRow,
  type ThemeRotationSummary,
} from '@/services/theme/ThemeFacade'
import {
  countRotationStates,
  MARKET_PHASE_META,
  marketPhaseLabel,
  rotationStateLabel,
  ROTATION_STATE_META,
  type RotationCategory,
} from '@/services/theme/rotationDisplay'
import SectorRotationTree from './SectorRotationTree.vue'

const loading = ref(false)
const error = ref<string | null>(null)
const summary = ref<ThemeRotationSummary | null>(null)
const tableOpen = ref(false)
const stateFilter = ref<RotationCategory>('all')
const sortKey = ref<string>('rank')
const sortDir = ref<1 | -1>(1)

async function loadData(force = false) {
  if (loading.value && !force) return
  loading.value = true
  error.value = null
  try {
    const result = await getRotationSummary({ snapshotType: 'half_hour' })
    if (result) summary.value = result
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (!summary.value) loadData()
})

const rotationSummary = computed(() => summary.value?.frame.rotationSummary ?? null)
const dataTimeText = computed(() => {
  const frame = summary.value?.frame
  return frame ? `数据 ${frame.tradingDate} ${frame.slotTime}` : '未加载'
})
const phaseLabel = computed(() => marketPhaseLabel(rotationSummary.value?.marketPhase))
const phaseTone = computed(() => {
  const phase = rotationSummary.value?.marketPhase
  return (phase && MARKET_PHASE_META[phase]?.tone) || 'phase-unknown'
})
const mainLineNames = computed(() => rotationSummary.value?.mainLines.map((m) => m.themeName) ?? [])
const inflowThemes = computed(() => rotationSummary.value?.inflowThemes ?? [])
const outflowThemes = computed(() => rotationSummary.value?.outflowThemes ?? [])
const PREVIEW_COUNT = 8
const inflowPreview = computed(() => inflowThemes.value.slice(0, PREVIEW_COUNT))
const inflowRestCount = computed(() => Math.max(0, inflowThemes.value.length - PREVIEW_COUNT))
const outflowPreview = computed(() => outflowThemes.value.slice(0, PREVIEW_COUNT))
const outflowRestCount = computed(() => Math.max(0, outflowThemes.value.length - PREVIEW_COUNT))
const statuses = computed(() => summary.value?.statuses ?? [])
const stateBuckets = computed(() => countRotationStates(statuses.value))

const columns = [
  { key: 'entityName', label: '题材', sortable: false },
  { key: 'rank', label: '排名', sortable: true },
  { key: 'rankChange', label: '排名变化', sortable: true },
  { key: 'rotationState', label: '轮动状态', sortable: true },
  { key: 'rotationScore', label: '轮动分', sortable: true },
  { key: 'strength', label: '强度', sortable: true },
  { key: 'flow', label: '资金', sortable: true },
  { key: 'breadth', label: '广度', sortable: true },
  { key: 'crowding', label: '拥挤', sortable: true },
  { key: 'flowTrend', label: '净流入趋势', sortable: true },
  { key: 'qualityFlags', label: '质量标记', sortable: false },
] as const

function toggleSort(key: string) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 1 ? -1 : 1
  } else {
    sortKey.value = key
    sortDir.value = 1
  }
}

const BREAKDOWN_KEYS = new Set(['strength', 'flow', 'breadth', 'crowding'])

function sortValue(row: ThemeRotationStatusRow, key: string): number | string {
  if (key === 'rotationState') return rotationStateLabel(row.rotationState)
  if (BREAKDOWN_KEYS.has(key)) {
    const value = row.factorBreakdown?.[key as 'strength' | 'flow' | 'breadth' | 'crowding']
    return typeof value === 'number' ? value : Number.NEGATIVE_INFINITY
  }
  const direct = (row as unknown as Record<string, unknown>)[key]
  if (typeof direct === 'number') return direct
  if (typeof direct === 'string') return direct
  return Number.NEGATIVE_INFINITY
}

const visibleRows = computed(() => {
  const rows = statuses.value.filter(
    (row) => stateFilter.value === 'all' || (row.rotationState || 'unknown') === stateFilter.value,
  )
  const dir = sortDir.value
  const key = sortKey.value
  return [...rows].sort((a, b) => {
    const va = sortValue(a, key)
    const vb = sortValue(b, key)
    if (typeof va === 'string' || typeof vb === 'string') {
      return String(va).localeCompare(String(vb), 'zh-Hans-CN') * dir
    }
    return (va - vb) * dir
  })
})

function formatNumber(value: number | null | undefined, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—'
}

function formatPercent(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : '—'
}

function formatSigned(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return value > 0 ? `+${value}` : String(value)
}

function formatFlowTrend(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const abs = Math.abs(value)
  const text = abs >= 1e8 ? `${(abs / 1e8).toFixed(1)}亿` : abs >= 1e4 ? `${(abs / 1e4).toFixed(0)}万` : String(abs)
  return (value > 0 ? '+' : value < 0 ? '-' : '') + text
}

function trendClass(value: number | null | undefined) {
  return { 'trend-up': (value ?? 0) > 0, 'trend-down': (value ?? 0) < 0 }
}

function stateLabelOf(state: string | null | undefined): string {
  return rotationStateLabel(state)
}

function stateToneOf(state: string | null | undefined): string {
  return (state && ROTATION_STATE_META[state]?.tone) || 'state-unknown'
}
</script>

<style scoped>
.sector-rotation-tab {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  overflow-y: auto;
}
.rotation-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.rotation-updated {
  font-size: 12px;
  color: var(--text-secondary, #9aa5b1);
}
.refresh-btn,
.retry-btn,
.table-toggle {
  background: var(--bg-tertiary, transparent);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  border-radius: 4px;
  padding: 3px 10px;
  cursor: pointer;
  font-size: 12px;
}
.refresh-btn:hover,
.retry-btn:hover,
.table-toggle:hover {
  border-color: var(--accent-color, #4a9eff);
}
.rotation-error,
.rotation-empty {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  color: var(--text-secondary, #9aa5b1);
  font-size: 13px;
}
.rotation-summary {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  background: var(--bg-secondary, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--border-color);
  border-radius: 6px;
}
.summary-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
}
.row-label {
  color: var(--text-secondary, #9aa5b1);
  min-width: 30px;
}
.phase-badge {
  padding: 2px 10px;
  border-radius: 10px;
  font-weight: 600;
  border: 1px solid var(--border-color);
}
.phase-cooling { color: #5ba3f5; border-color: #5ba3f5; }
.phase-climax { color: #f55b5b; border-color: #f55b5b; }
.phase-rising { color: #f58b5b; border-color: #f58b5b; }
.phase-ice { color: #7fd4ff; border-color: #7fd4ff; }
.phase-chaos { color: #d4a0ff; border-color: #d4a0ff; }
.phase-neutral { color: var(--text-primary); }
.phase-unknown { color: var(--text-secondary, #9aa5b1); }
.summary-metric {
  color: var(--text-primary);
}
.theme-chip {
  padding: 1px 8px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
}
.chip-mainline { color: #f5c15b; border-color: #f5c15b; }
.chip-inflow { color: #f55b5b; border-color: rgba(245, 91, 91, 0.5); }
.chip-outflow { color: #4caf7d; border-color: rgba(76, 175, 125, 0.5); }
.chip-rest { color: var(--text-secondary, #9aa5b1); }
.no-mainline { color: var(--text-secondary, #9aa5b1); }
.state-count,
.state-badge {
  padding: 1px 8px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
}
.state-mainline { color: #f5c15b; border-color: #f5c15b; }
.state-inflow { color: #f55b5b; border-color: rgba(245, 91, 91, 0.5); }
.state-emerging { color: #5bd4f5; border-color: #5bd4f5; }
.state-neutral { color: var(--text-secondary, #9aa5b1); }
.state-outflow { color: #4caf7d; border-color: rgba(76, 175, 125, 0.5); }
.state-cooling { color: #5ba3f5; border-color: rgba(91, 163, 245, 0.5); }
.state-unknown { color: var(--text-secondary, #9aa5b1); }
.rotation-table-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.rotation-table-wrap {
  overflow-x: auto;
}
.rotation-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.rotation-table th,
.rotation-table td {
  padding: 5px 8px;
  border-bottom: 1px solid var(--border-color);
  text-align: right;
  white-space: nowrap;
}
.rotation-table th:first-child,
.rotation-table td:first-child {
  text-align: left;
}
.rotation-table th.sortable {
  cursor: pointer;
  user-select: none;
}
.rotation-table th.sorted {
  color: var(--accent-color, #4a9eff);
}
.trend-up { color: #f55b5b; }
.trend-down { color: #4caf7d; }
.row-empty { color: var(--text-secondary, #9aa5b1); }
.rotate-animation { display: inline-block; animation: rotation-spin 1s linear infinite; }
@keyframes rotation-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
