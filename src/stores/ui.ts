import { debugLog } from '@/utils/logger'
// src/stores/ui.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Stock } from '../types'
import { EventManager } from '../utils/eventManager'
import { AppEvents } from '../types'
import { dataLayer } from '../services/DataLayer'

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

function getResonanceIntensitySortValue(stock: any): number | null {
  if (stock._resonancePct !== undefined) return toFiniteNumber(stock._resonancePct)
  const resonance = getRankTrendAnalysis(stock)?.resonance
  return resonance?.status === 'ok' ? toFiniteNumber(resonance.score) : null
}

function getObservationSortValue(stock: any, field: '_rankTrendPct' | '_lifecyclePct') {
  if (stock[field] !== undefined) return toFiniteNumber(stock[field])
  const observation = getRankTrendAnalysis(stock)?.observation
  return field === '_rankTrendPct'
    ? toFiniteNumber(observation?.rankTrend?.score)
    : toFiniteNumber(observation?.lifecycle?.score)
}

function getStockSortValue(stock: Stock, field: SortField): string | number | null {
  if (field === 'resonanceIntensity') return getResonanceIntensitySortValue(stock)
  if (field === 'rankTrendStrength') return getObservationSortValue(stock, '_rankTrendPct')
  if (field === 'lifecycleOpportunity') return getObservationSortValue(stock, '_lifecyclePct')
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
