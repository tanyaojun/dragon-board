import { debugLog } from '@/utils/logger'
// src/stores/ui.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Stock } from '../types'
import { EventManager } from '../utils/eventManager'
import { AppEvents } from '../types'
import { dataLayer } from '../services/DataLayer'
import {
  getCrossSectionTier,
  getRankTrendTier,
  getResonanceTier,
  getSynergyTier,
  getVolumePriceTier,
} from '@/services/rankTrend/tierDisplay'
import type { RankTrendSignalTier } from '@/services/rankTrend/types'

type SortField = string

interface SortConfig {
  field: SortField
  order: 'asc' | 'desc'
}

function toFiniteNumber(value: unknown): number | null {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

function getRankTrendAnalysis(stock: any) {
  return stock?.rankTrend ?? null
}

/** 档位等级（S 最高 → E 最低）；unknown/缺失为 null 排最后。四信号列（共振/趋势/热度/量价）与五维度（synergy）共用 */
const SIGNAL_TIER_LEVEL: Record<string, number> = { S: 5, A: 4, B: 3, C: 2, D: 1, E: 0 }

/**
 * 生命周期阶段序数（2026-09-19 修复）：周期列显示 stage（点火/扩散/拥挤/反转/冷却），
 * 排序值必须与显示同字段——按阶段序数聚簇，不再按 signalTier（tier 与 stage 是两套轴，
 * tier 排序会让同档内 stage 交错，出现"扩散点火混排"）。unknown/缺失/非法值 → null 恒排最后。
 */
const LIFECYCLE_STAGE_ORDER: Record<string, number> = {
  ignition: 5,
  expansion: 4,
  crowded: 3,
  reversal: 2,
  cooling: 1,
}

/** 生命周期分值（投影优先，回退 observation.lifecycle.score；周期同阶段组内次级排序用） */
function getLifecycleScoreOf(stock: any): number | null {
  if (stock?._lifecyclePct !== undefined) return toFiniteNumber(stock._lifecyclePct)
  return toFiniteNumber(getRankTrendAnalysis(stock)?.observation?.lifecycle?.score)
}

/** 生命周期阶段（投影优先，回退 observation.lifecycle.stage；缺失/未知返回 null）。
 * 样本不足（meta.sampleQuality.status=insufficient，周期列显示覆盖标签「样本不足」）
 * 的股票排序归末组（返回 null）：2026-09-20 用户裁决——显示「样本不足」的行混在
 * 点火等真实阶段组中间，观感即排序错误；样本质量降级的股票不再参与阶段聚簇。 */
function getLifecycleStageOf(stock: any): string | null {
  if (getRankTrendAnalysis(stock)?.meta?.sampleQuality?.status === 'insufficient') return null
  const stage =
    stock?._lifecycleStage ?? getRankTrendAnalysis(stock)?.observation?.lifecycle?.stage ?? null
  return typeof stage === 'string' && stage in LIFECYCLE_STAGE_ORDER ? stage : null
}

function getRankTrendStrengthScoreOf(stock: any): number | null {
  if (stock?._rankTrendPct !== undefined) return toFiniteNumber(stock._rankTrendPct)
  return toFiniteNumber(getRankTrendAnalysis(stock)?.observation?.rankTrend?.score)
}

function getCrossSectionPercentileOf(stock: any): number | null {
  return toFiniteNumber(getRankTrendAnalysis(stock)?.observation?.crossSection?.percentile)
}

/**
 * 四信号列（共振/趋势/热度/量价）档位排序（2026-09-29 用户裁决）：排序与列显示同字段——
 * 按档位等级 S=5→E=0 分组（复用 SIGNAL_TIER_LEVEL），同档位组内按现有分值（score/percentile
 * 投影）次级排序；unknown/缺失 → null 恒排最后（fail-visible）。档位取值复用 tierDisplay
 * （stock.rankTrend.*.signalTier），不新增档位算法；原方向组排序（2026-08-24 的「向上恒前」）
 * 已随本次裁决移除。
 */
const SIGNAL_TIER_SORT_GETTERS: Record<string, (stock: unknown) => RankTrendSignalTier | null> = {
  resonanceIntensity: getResonanceTier,
  rankTrendStrength: getRankTrendTier,
  crossSection: getCrossSectionTier,
  volumePriceQuadrant: getVolumePriceTier,
}

function isSignalTierSortField(field: SortField): boolean {
  return Object.prototype.hasOwnProperty.call(SIGNAL_TIER_SORT_GETTERS, field)
}

function getSignalTierSortValue(stock: Stock, field: SortField): number | null {
  const tier = SIGNAL_TIER_SORT_GETTERS[field]?.(stock)
  return tier && tier !== 'unknown' ? SIGNAL_TIER_LEVEL[tier] : null
}

/** 同档位组内次级排序值：现有分值/percentile 投影（与原数值%排序口径一致） */
function getSignalScoreSortValue(stock: Stock, field: SortField): number | null {
  if (field === 'resonanceIntensity') return getResonanceIntensitySortValue(stock)
  if (field === 'rankTrendStrength') return getRankTrendStrengthScoreOf(stock)
  if (field === 'crossSection') return getCrossSectionPercentileOf(stock)
  if (field === 'volumePriceQuadrant') {
    // 量价分（0-100）：投影优先，回退 rankTrend.observation.volumePrice.score（与三指标回退口径一致）
    const projected = (stock as any)._volumePriceScore
    if (projected !== undefined) return toFiniteNumber(projected)
    return toFiniteNumber(getRankTrendAnalysis(stock)?.observation?.volumePrice?.score)
  }
  return null
}

function getResonanceIntensitySortValue(stock: any): number | null {
  if (stock._resonancePct !== undefined) return toFiniteNumber(stock._resonancePct)
  const resonance = getRankTrendAnalysis(stock)?.resonance
  return resonance?.status === 'ok' ? toFiniteNumber(resonance.score) : null
}

// 涨停相关字段（2026-09-02）：缺失（非涨停/未覆盖）与真实 0（封单 0、开板 0）语义不同，
// 缺失返回 null 恒排最后（fail-visible），不与 0 混排；与题材面板 compareThemeStockRows 语义一致
const LIMIT_UP_MISSING_LAST_SORT_FIELDS = new Set([
  'lianbanStr',
  'firstZtTime',
  'lastZtTime',
  'fengdan',
  'openNum',
  'limitUpReason',
])

function getStockSortValue(stock: Stock, field: SortField): string | number | null {
  // 2026-09-29 用户裁决：共振/趋势/热度/量价四列按档位等级排序（与列显示的 S/A/B/C/D/E 徽章同字段）；
  // 同档位组内按现有分值次级排序（见 sortedStocks）；档位缺失/unknown → null 恒排最后
  if (isSignalTierSortField(field)) return getSignalTierSortValue(stock, field)
  // 2026-09-19 修复：周期列排序值取生命周期阶段序数（与列显示的 stage 同字段，点火=5 → 冷却=1）；
  // 同阶段组内按分值次级排序（见 sortedStocks）；无阶段/缺失 → null 恒排最后
  if (field === 'lifecycleOpportunity') {
    const stage = getLifecycleStageOf(stock)
    return stage ? LIFECYCLE_STAGE_ORDER[stage] ?? null : null
  }
  if (field === 'synergyTier') {
    // synergy 合并档位等级值（S=5 → E=0）；unknown/缺失 → null 排最后
    const tier = getSynergyTier(stock)
    return tier && tier !== 'unknown' ? SIGNAL_TIER_LEVEL[tier] : null
  }
  if (field === 'avgRank') {
    return (
      toFiniteNumber((stock as any).avgRankNum) ??
      toFiniteNumber(stock.avgRank) ??
      999
    )
  }
  if (field === 'themes') {
    const themes = (stock as any).themes
    return Array.isArray(themes) ? themes.join(', ') : String(themes ?? '')
  }

  const value = (stock as unknown as Record<string, unknown>)[field]
  if (value === undefined || value === null || value === '') {
    if (LIMIT_UP_MISSING_LAST_SORT_FIELDS.has(field)) return null
    return field.includes('Rank') ? 999 : 0
  }

  const numeric = toFiniteNumber(value)
  return numeric ?? String(value)
}

function compareSortValues(
  left: string | number | null,
  right: string | number | null,
  order: 'asc' | 'desc',
) {
  if (left == null && right == null) return 0
  if (left == null) return 1
  if (right == null) return -1

  let result = 0
  if (typeof left === 'number' && typeof right === 'number') {
    result = left - right
  } else {
    result = String(left).localeCompare(String(right), 'zh-CN')
  }

  return order === 'asc' ? result : -result
}

interface FilterConfig {
  onlyLeaders: boolean
  onlyFavorites: boolean
  minChange: number
  maxChange: number
  sectors: string[]
  searchKeyword: string
  leaderLevels: string[]
  minVolume: number
}

interface PaginationConfig {
  page: number
  pageSize: number
}

interface ViewConfig {
  mode: string
  density: string
  showColumns: string[]
}

export const useUIStore = defineStore('ui', () => {
  const selectedCode = ref<string | null>(null)
  const hoveredCode = ref<string | null>(null)
  const expandedRows = ref<Set<string>>(new Set())

  const sort = ref<SortConfig>({
    field: 'synergyTier',
    order: 'desc',
  })

  const filters = ref<FilterConfig>({
    onlyLeaders: false,
    onlyFavorites: false,
    minChange: -20,
    maxChange: 20,
    sectors: [],
    searchKeyword: '',
    leaderLevels: [],
    minVolume: 0,
  })

  const pagination = ref<PaginationConfig>({
    page: 1,
    pageSize: 50,
  })

  const view = ref<ViewConfig>({
    mode: 'table',
    density: 'default',
    showColumns: [
      'code',
      'name',
      'themes',
      'price',
      'change',
      'emRank',
      'thsRank',
      'kplRank',
      'tdxRank',
      'xqRank',
      'clsRank',
      'tgbRank',
      'dzhRank',
      'avgRank',
      'compRank',
      'resonanceIntensity',
      'rankTrendStrength',
      'lifecycleOpportunity',
      'zlje',
      'zljzb',
      'cddje',
      'cddjzb',
      'volume',
      'turnover',
      'turnoverRate',
      'cirMV',
      'pe',
      'totalMV',
      'pb',
    ],
  })

  const scrollPosition = ref(0)
  const dataVersion = ref(0)

  const rawStocks = computed<Stock[]>(() => {
    dataVersion.value
    return dataLayer.getStocks() as Stock[]
  })

  const filteredStocks = computed(() => {
    let result = rawStocks.value

    if (filters.value.onlyLeaders) {
      // 真龙复盘引擎已移除（2026-09-26 瘦身），无龙头数据源，过滤结果恒为空
      result = result.filter(() => false)
    }

    if (filters.value.onlyFavorites) {
      // TODO: 收藏过滤依赖 favorite store 的历史类型，后续单独清理后恢复。
      result = result.filter(() => true)
    }

    if (filters.value.searchKeyword) {
      const keyword = filters.value.searchKeyword.toLowerCase()
      result = result.filter(
        (s: Stock) => s.code.includes(keyword) || s.name?.toLowerCase().includes(keyword),
      )
    }

    if (filters.value.minChange > -20) {
      result = result.filter((s: Stock) => (s.change || 0) >= filters.value.minChange)
    }

    if (filters.value.maxChange < 20) {
      result = result.filter((s: Stock) => (s.change || 0) <= filters.value.maxChange)
    }

    return result
  })

  const sortedStocks = computed(() => {
    const result = [...filteredStocks.value]
    const { field, order } = sort.value

    // Access to keep dependency explicit.
    dataVersion.value

    result.sort((a, b) => {
      // 五维度（2026-08-26 用户需求）：纯档位排序——↓降序=高档（A/S）在前、↑升序=低档（E）在前；
      // 四信号列（2026-09-29 用户裁决）：共振/趋势/热度/量价按档位等级分组排序（与列显示的
      // S/A/B/C/D/E 徽章同字段），同档位组内按现有分值（score/percentile 投影）次级排序；
      // 周期（2026-09-19 修复）：按显示的 stage 序数聚簇（点火>扩散>拥挤>反转>冷却），
      // 同阶段组内按分值次级排序；档位/阶段缺失（null）恒排最后（fail-visible，不伪装）。
      if (field === 'synergyTier' || isSignalTierSortField(field) || field === 'lifecycleOpportunity') {
        const byTier = compareSortValues(getStockSortValue(a, field), getStockSortValue(b, field), order)
        if (byTier !== 0) return byTier
        if (field === 'lifecycleOpportunity') {
          return compareSortValues(getLifecycleScoreOf(a), getLifecycleScoreOf(b), order)
        }
        if (isSignalTierSortField(field)) {
          return compareSortValues(getSignalScoreSortValue(a, field), getSignalScoreSortValue(b, field), order)
        }
        return 0
      }
      return compareSortValues(getStockSortValue(a, field), getStockSortValue(b, field), order)
    })

    return result
  })

  const paginatedStocks = computed(() => {
    const start = (pagination.value.page - 1) * pagination.value.pageSize
    const end = start + pagination.value.pageSize
    return sortedStocks.value.slice(start, end)
  })

  const stats = computed(() => ({
    total: rawStocks.value.length,
    filtered: filteredStocks.value.length,
    leaders: 0,
    totalPages: Math.ceil(filteredStocks.value.length / pagination.value.pageSize),
  }))

  function selectStock(code: string | null) {
    selectedCode.value = code
    if (code) {
      EventManager.emit(AppEvents.STOCK.SELECTED, { code })
    }
  }

  function hoverStock(code: string | null) {
    hoveredCode.value = code
  }

  function toggleSort(field: SortConfig['field']) {
    if (sort.value.field === field) {
      sort.value.order = sort.value.order === 'asc' ? 'desc' : 'asc'
    } else {
      sort.value.field = field
      sort.value.order = 'asc'
    }
    pagination.value.page = 1
  }

  function updateFilters(updates: Partial<FilterConfig>) {
    filters.value = { ...filters.value, ...updates }
    pagination.value.page = 1
  }

  function resetFilters() {
    filters.value = {
      onlyLeaders: false,
      onlyFavorites: false,
      minChange: -20,
      maxChange: 20,
      sectors: [],
      searchKeyword: '',
      leaderLevels: [],
      minVolume: 0,
    }
    pagination.value.page = 1
  }

  function toggleExpand(code: string) {
    if (expandedRows.value.has(code)) expandedRows.value.delete(code)
    else expandedRows.value.add(code)
    expandedRows.value = new Set(expandedRows.value)
  }

  function setPage(page: number) {
    pagination.value.page = Math.max(1, Math.min(page, stats.value.totalPages))
  }

  function setPageSize(size: number) {
    pagination.value.pageSize = size
    pagination.value.page = 1
  }

  function saveScrollPosition(pos: number) {
    scrollPosition.value = pos
  }

  function updateDataVersion() {
    dataVersion.value++
  }

  function init() {
    debugLog('[UIStore] init')

    let lastStocksVersion: number | null = null
    const syncStocksVersion = (version: number) => {
      if (lastStocksVersion === version) return
      lastStocksVersion = version
      updateDataVersion()
    }
    const updateFromMergedEvent = () => {
      const stocksVersion = dataLayer.getVersion().stocks
      if (lastStocksVersion === stocksVersion) return
      lastStocksVersion = stocksVersion
      updateDataVersion()
    }

    const unsubStocksVersion = dataLayer.subscribe('version.stocks', syncStocksVersion)
    const unsubMerged = EventManager.on(AppEvents.DATA.MERGED, updateFromMergedEvent)
    const unsubUpdated = EventManager.on(AppEvents.DATA.UPDATED, updateFromMergedEvent)

    return () => {
      unsubStocksVersion()
      unsubMerged()
      unsubUpdated()
    }
  }

  return {
    selectedCode,
    hoveredCode,
    expandedRows,
    sort,
    filters,
    pagination,
    view,
    scrollPosition,
    dataVersion,
    rawStocks,
    filteredStocks,
    sortedStocks,
    paginatedStocks,
    stats,
    selectStock,
    hoverStock,
    toggleSort,
    updateFilters,
    resetFilters,
    toggleExpand,
    setPage,
    setPageSize,
    saveScrollPosition,
    updateDataVersion,
    init,
  }
})
