// src/stores/ui.ts
import { defineStore } from 'pinia'
import { ref, computed, shallowRef } from 'vue'
import type { Stock, SortConfig, FilterConfig, PaginationConfig, ViewConfig } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import { dataLayer } from '@/services/DataLayer'
import { dragonAnalyzer } from '@/services/DragonAnalyzer'

export const useUIStore = defineStore('ui', () => {
  // ========== 表格状态 ==========
  const selectedCode = ref<string | null>(null)
  const hoveredCode = ref<string | null>(null)
  const expandedRows = ref<Set<string>>(new Set())

  // 排序
  const sort = ref<SortConfig>({
    field: 'compRank',
    order: 'asc',
  })

  // 过滤
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

  // 分页
  const pagination = ref<PaginationConfig>({
    page: 1,
    pageSize: 50,
  })

  // 视图配置
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
      'rankChange',
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

  // 表格滚动位置
  const scrollPosition = ref(0)

  // 数据版本
  const dataVersion = ref(0)

  // ========== 数据计算 ==========
  const rawStocks = computed(() => dataLayer.getStocks())

  // 应用过滤
  const filteredStocks = computed(() => {
    let result = rawStocks.value

    if (filters.value.onlyLeaders) {
      result = result.filter((s) => dragonAnalyzer.isLeader(s.code))
    }

    if (filters.value.onlyFavorites) {
      // 从 favoriteStore 获取
      const favoriteStore = useFavoriteStore()
      result = result.filter((s) => favoriteStore.favoriteCodes.has(s.code))
    }

    if (filters.value.searchKeyword) {
      const keyword = filters.value.searchKeyword.toLowerCase()
      result = result.filter(
        (s) => s.code.includes(keyword) || s.name?.toLowerCase().includes(keyword),
      )
    }

    if (filters.value.minChange > -20) {
      result = result.filter((s) => (s.change || 0) >= filters.value.minChange)
    }

    if (filters.value.maxChange < 20) {
      result = result.filter((s) => (s.change || 0) <= filters.value.maxChange)
    }

    return result
  })

  // 应用排序
  const sortedStocks = computed(() => {
    const result = [...filteredStocks.value]
    const { field, order } = sort.value

    dataVersion.value

    result.sort((a, b) => {
      let aVal: any = a[field as keyof Stock]
      let bVal: any = b[field as keyof Stock]

      if (aVal === undefined || aVal === null) aVal = field.includes('Rank') ? 999 : 0
      if (bVal === undefined || bVal === null) bVal = field.includes('Rank') ? 999 : 0

      if (order === 'asc') {
        return aVal > bVal ? 1 : -1
      } else {
        return aVal < bVal ? 1 : -1
      }
    })

    return result
  })

  // 分页数据
  const paginatedStocks = computed(() => {
    const start = (pagination.value.page - 1) * pagination.value.pageSize
    const end = start + pagination.value.pageSize
    return sortedStocks.value.slice(start, end)
  })

  // 统计数据
  const stats = computed(() => ({
    total: rawStocks.value.length,
    filtered: filteredStocks.value.length,
    leaders: rawStocks.value.filter((s) => dragonAnalyzer.isLeader(s.code)).length,
    totalPages: Math.ceil(filteredStocks.value.length / pagination.value.pageSize),
  }))

  // ========== 操作方法 ==========
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
    if (expandedRows.value.has(code)) {
      expandedRows.value.delete(code)
    } else {
      expandedRows.value.add(code)
    }
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

  // ========== 初始化 ==========
  function init() {
    console.log('[UIStore] 初始化...')

    const unsubMerged = EventManager.on(AppEvents.DATA.MERGED, updateDataVersion)
    const unsubDragon = EventManager.on(AppEvents.DRAGON.UPDATED, updateDataVersion)

    return () => {
      unsubMerged()
      unsubDragon()
    }
  }

  return {
    // 状态
    selectedCode,
    hoveredCode,
    expandedRows,
    sort,
    filters,
    pagination,
    view,
    scrollPosition,
    dataVersion,

    // 计算属性
    rawStocks,
    filteredStocks,
    sortedStocks,
    paginatedStocks,
    stats,

    // 方法
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
