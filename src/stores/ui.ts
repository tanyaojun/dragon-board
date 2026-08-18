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
  getLifecycleTier,
  getResonanceTier,
  getSynergyTier,
  getVolumePriceTier,
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

/** 四维合并档位等级（S 最高 → E 最低）；unknown/缺失为 null 排最后，与四列打分排序对齐 */
const SYNERGY_TIER_LEVEL: Record<string, number> = { S: 5, A: 4, B: 3, C: 2, D: 1, E: 0 }

/**
 * 统一档位等级（2026-08-18）：共振/趋势/量价/周期 四列排序按徽章档位等级，
 * 不再按方向组 + 数值。S=6 最高 → E=1 最低；unknown/缺失 = 0 排最后。
 * crossSection 值域 A/B/C/D（无 S/E），lifecycle 值域 A/B/D/E（无 C）。
 */
const TIER_LEVEL: Record<string, number> = { S: 6, A: 5, B: 4, C: 3, D: 2, E: 1 }

/** 档位等级（unknown/缺失 = 0 排最后）；共振/趋势/量价/周期排序共用 */
const tierLevelOf = (tier: string | null | undefined): number => {
  if (!tier || tier === 'unknown') return 0
  return TIER_LEVEL[tier] ?? 0
}

/** 生命周期阶段类型等级（2026-08-18：周期列按类型排序，弃分值）——阶段序列：点火→扩散→拥挤→反转→冷却 */
const STAGE_LEVEL: Record<string, number> = {
  ignition: 5,
  expansion: 4,
  crowded: 3,
  reversal: 2,
  cooling: 1,
}

const stageLevelOf = (stage: unknown): number => {
  if (typeof stage !== 'string') return 0
  return STAGE_LEVEL[stage] ?? 0
}

/** 生命周期 stage（投影优先，回退 observation.lifecycle.stage） */
const getLifecycleStageOf = (stock: any): unknown =>
  stock?._lifecycleStage ?? getRankTrendAnalysis(stock)?.observation?.lifecycle?.stage ?? null

/**
 * 三个方向字段（共振强度 / 排名趋势 / 生命周期）的方向排序组：
 * 1 = 上升，0 = 持平/未知，-1 = 下降。方向组固定优先（上升在前、下降在后），
 * 与 asc/desc 无关，避免「下降 90 排在上升 88 前面」这类纯数值排序造成的错觉。
 */
function getDirectionalSortRank(stock: any, field: SortField): number {
  // 2026-08-18：四列（共振/趋势/量价/周期）排序改按徽章档位等级（TIER_LEVEL），
  // 不再按方向组 + 数值。A 档在前、D/E 在后、unknown 排最后。
  if (field === 'resonanceIntensity') {
    return tierLevelOf(getResonanceTier(stock))
  }
  if (field === 'rankTrendStrength') {
    // 趋势列显示横截面徽章（crossSection），排序同徽章口径
    return tierLevelOf(getCrossSectionTier(stock))
  }
  if (field === 'lifecycleOpportunity') {
    // 2026-08-18：周期列按 stage 类型排序（点火→扩散→拥挤→反转→冷却），弃档位/分值
    return stageLevelOf(getLifecycleStageOf(stock))
  }
  if (field === 'volumePriceQuadrant') {
    return tierLevelOf(getVolumePriceTier(stock))
  }
  if (field === 'synergyTier') {
    // 四维方向组：S/A/B 方向一致强买（buy 类）在前，D/E 反向/风险在后；C/unknown/缺失中性
    const tier = getSynergyTier(stock)
    if (tier === 'S' || tier === 'A' || tier === 'B') return 1
    if (tier === 'D' || tier === 'E') return -1
    return 0
  }
  return 0
}

function getResonanceIntensitySortValue(stock: any): number | null {
  if (stock._resonancePct !== undefined) return toFiniteNumber(stock._resonancePct)
  const resonance = getRankTrendAnalysis(stock)?.resonance
  return resonance?.status === 'ok' ? toFiniteNumber(resonance.score) : null
}

function getStockSortValue(stock: Stock, field: SortField): string | number | null {
  if (field === 'resonanceIntensity') return getResonanceIntensitySortValue(stock)
  // 2026-08-18：趋势列显示横截面徽章——排序完全按徽章档位等级（弃百分比 score，避免与显示不一致）
  if (field === 'rankTrendStrength') return tierLevelOf(getCrossSectionTier(stock))
  // 2026-08-18：周期列按 stage 类型排序（弃分值）
  if (field === 'lifecycleOpportunity') return stageLevelOf(getLifecycleStageOf(stock))
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
    field: 'compRank',
    order: 'asc',
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
      // 方向字段：先按档位组排序（2026-08-18：档位等级随 order 反转——双击列头反向排序，
      // 修复方向组固定降序导致切换无效的 bug）；组内再按数值 + order。
      const directionRankA = getDirectionalSortRank(a, field)
      const directionRankB = getDirectionalSortRank(b, field)
      if (directionRankA !== directionRankB) {
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
