import { debugLog } from '@/utils/logger'
// src/stores/ui.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Stock } from '../types'
import { EventManager } from '../utils/eventManager'
import { AppEvents } from '../types'
import { dataLayer } from '../services/DataLayer'
import {
  getSynergyTier,
} from '@/services/rankTrend/tierDisplay'

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

/** 档位等级（S 最高 → E 最低）；unknown/缺失为 null 排最后。五维度（synergy）与周期（lifecycle）共用 */
const SYNERGY_TIER_LEVEL: Record<string, number> = { S: 5, A: 4, B: 3, C: 2, D: 1, E: 0 }

/** 生命周期分值（投影优先，回退 observation.lifecycle.score；周期同档位组内次级排序用） */
function getLifecycleScoreOf(stock: any): number | null {
  if (stock?._lifecyclePct !== undefined) return toFiniteNumber(stock._lifecyclePct)
  return toFiniteNumber(getRankTrendAnalysis(stock)?.observation?.lifecycle?.score)
}

/** 生命周期档位（observation.lifecycle.signalTier；缺失返回 null） */
function getLifecycleTierOf(stock: any): string | null {
  const tier = getRankTrendAnalysis(stock)?.observation?.lifecycle?.signalTier
  return typeof tier === 'string' && tier !== 'unknown' ? tier : null
}

/**
 * 方向排序组（2026-08-24）：buy/up=1、中性/未知=0、sell/down=-1。
 * 四信号（共振/趋势/热度/量价）方向组**固定**「向上恒前」，不随 order 反转（见
 * isDirectionFixedSortField）；组内数值%仍随 order 升降。
 */
const dirRankOf = (dir: unknown): number =>
  dir === 'buy' || dir === 'up' ? 1 : dir === 'sell' || dir === 'down' ? -1 : 0

/**
 * 2026-08-24：共振/趋势/热度/量价四信号——方向组固定「向上（buy/up）恒前」，
 * 不随 order 反转（升序/降序都向上优先）；五维度/周期不走方向组
 * （2026-08-26 起改为纯档位排序，见 sortedStocks 专用分支）。
 */
function isDirectionFixedSortField(field: SortField): boolean {
  return (
    field === 'resonanceIntensity' ||
    field === 'rankTrendStrength' ||
    field === 'crossSection' ||
    field === 'volumePriceQuadrant'
  )
}

function getResonanceDirectionOf(stock: any): unknown {
  const resonance = getRankTrendAnalysis(stock)?.resonance
  return resonance?.status === 'ok' ? resonance.direction ?? 'hold' : 'hold'
}

function getRankTrendStrengthScoreOf(stock: any): number | null {
  if (stock?._rankTrendPct !== undefined) return toFiniteNumber(stock._rankTrendPct)
  return toFiniteNumber(getRankTrendAnalysis(stock)?.observation?.rankTrend?.score)
}

function getRankTrendDirectionOf(stock: any): unknown {
  return (
    stock?._rankTrendDirection ??
    getRankTrendAnalysis(stock)?.observation?.rankTrend?.direction ??
    'hold'
  )
}

function getVolumePriceDirectionOf(stock: any): unknown {
  return (
    stock?._volumePriceDirection ??
    getRankTrendAnalysis(stock)?.observation?.volumePrice?.direction ??
    'neutral'
  )
}

function getCrossSectionPercentileOf(stock: any): number | null {
  return toFiniteNumber(getRankTrendAnalysis(stock)?.observation?.crossSection?.percentile)
}

function getCrossSectionDirectionOf(stock: any): unknown {
  const pct = getCrossSectionPercentileOf(stock)
  if (pct == null) return 'neutral'
  return pct >= 50 ? 'buy' : 'sell'
}

function getDirectionalSortRank(stock: any, field: SortField): number {
  // 2026-08-24：共振/趋势/热度/量价 → 方向组（buy/up 高在前；档位不参与，见 getStockSortValue 按数值%）
  if (field === 'resonanceIntensity') {
    return dirRankOf(getResonanceDirectionOf(stock))
  }
  if (field === 'rankTrendStrength') {
    return dirRankOf(getRankTrendDirectionOf(stock))
  }
  if (field === 'crossSection') {
    return dirRankOf(getCrossSectionDirectionOf(stock))
  }
  if (field === 'volumePriceQuadrant') {
    return dirRankOf(getVolumePriceDirectionOf(stock))
  }
  // 五维度/周期（2026-08-26 用户需求）：纯档位排序，不走方向组（见 sortedStocks 专用分支）
  return 0
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
  if (field === 'resonanceIntensity') return getResonanceIntensitySortValue(stock)
  // 2026-08-24：趋势列显示方向+数值%——排序值取排名趋势分（弃热度档位，热度独立成列）
  if (field === 'rankTrendStrength') return getRankTrendStrengthScoreOf(stock)
  // 2026-08-24：热度（技术字段 crossSection）排序值取 percentile
  if (field === 'crossSection') return getCrossSectionPercentileOf(stock)
  // 2026-08-26：周期列排序值取周期档位等级（A=4 → E=0，无 S 档）；同档位组内按分值次级排序（见 sortedStocks）
  if (field === 'lifecycleOpportunity') {
    const tier = getLifecycleTierOf(stock)
    return tier ? SYNERGY_TIER_LEVEL[tier] ?? null : null
  }
  if (field === 'volumePriceQuadrant') {
    // 量价分（0-100）：投影优先，回退 rankTrend.observation.volumePrice.score（与三指标回退口径一致）
    const projected = (stock as any)._volumePriceScore
    if (projected !== undefined) return toFiniteNumber(projected)
    return toFiniteNumber(getRankTrendAnalysis(stock)?.observation?.volumePrice?.score)
  }
  if (field === 'synergyTier') {
    // 四维等级值（S=5 → E=0）；unknown/缺失 → null 排最后
    const tier = getSynergyTier(stock)
    return tier && tier !== 'unknown' ? SYNERGY_TIER_LEVEL[tier] : null
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
    field: 'resonanceIntensity',
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
      result = result.filter((s: Stock) => !!dataLayer.getLeaderByCode(s.code))
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
      // 五维度/周期（2026-08-26 用户需求）：纯档位排序——↓降序=高档（A/S）在前、↑升序=低档（E）在前；
      // 周期同档位组内按分值次级排序；档位缺失（null）恒排最后（fail-visible，不伪装）。
      if (field === 'synergyTier' || field === 'lifecycleOpportunity') {
        const byTier = compareSortValues(getStockSortValue(a, field), getStockSortValue(b, field), order)
        if (byTier !== 0) return byTier
        if (field === 'lifecycleOpportunity') {
          return compareSortValues(getLifecycleScoreOf(a), getLifecycleScoreOf(b), order)
        }
        return 0
      }
      // 方向字段：先按方向组排序；组内再按数值 + order。
      const directionRankA = getDirectionalSortRank(a, field)
      const directionRankB = getDirectionalSortRank(b, field)
      if (directionRankA !== directionRankB) {
        // 2026-08-24：共振/趋势/热度/量价四信号——方向组固定（buy/up 恒前），
        // 不随 order 反转（无论升序降序，「向上」都排前面）；组内数值仍随 order 升降。
        const directionFixed = isDirectionFixedSortField(field)
        if (directionFixed) {
          return directionRankB - directionRankA
        }
        return order === 'asc' ? directionRankB - directionRankA : directionRankA - directionRankB
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
    leaders: rawStocks.value.filter((s) => !!dataLayer.getLeaderByCode(s.code)).length,
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
    const unsubDragon = EventManager.on(AppEvents.DRAGON.UPDATED, updateDataVersion)

    return () => {
      unsubStocksVersion()
      unsubMerged()
      unsubUpdated()
      unsubDragon()
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
