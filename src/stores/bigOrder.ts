import { debugLog } from '@/utils/logger'
// src/stores/bigOrder.ts - 无限滚动版
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { bigOrderService } from '@/services/big-order/BigOrderService'
import { dataLayer } from '@/services/DataLayer'
import { quoteCache } from '@/services/LRUCache'
import type {
  BigOrderItem,
  BigOrderStatistics,
  PeriodStatistics,
  BigOrderFilter,
  DenseOrderAlert,
} from '@/types/big-order'

export const useBigOrderStore = defineStore('bigOrder', () => {
  // ==================== 基础状态 ====================
  const currentStockCode = ref('')
  const currentStockName = ref('')

  // 筛选条件
  const currentFilter = ref<BigOrderFilter>({
    minAmount: undefined,
    maxAmount: undefined,
    minVolume: undefined,
    maxVolume: undefined,
    fundMarker: undefined,
    buyMarker: undefined,
    types: undefined,
    timeRange: undefined,
    startTime: undefined,
    endTime: undefined,
  })

  // ==================== 数据状态 ====================
  // 全量数据（直接从 DataLayer 获取）
  const fullOrders = computed(() =>
    currentStockCode.value ? dataLayer.getBigOrders(currentStockCode.value) : [],
  )

  // 分页状态（无限滚动用）
  const loadedCount = ref(0) // 已加载条数
  const totalCount = ref(0) // 总条数
  const hasMore = ref(false) // 是否还有更多

  // 已加载的原始数据（用于分页显示）
  const rawOrders = ref<BigOrderItem[]>([])

  // ==================== 缓存配置 ====================
  const CACHE_KEYS = {
    ORDERS: 'big-order-orders',
    STATS: 'big-order-stats',
    PERIODS: 'big-order-periods',
  }

  // 筛选缓存
  const FILTER_CACHE_TTL = 5000
  const filterCache = new Map<string, { orders: BigOrderItem[]; timestamp: number }>()
  let filterDebounceTimer: number | undefined

  // ==================== 从 DataLayer 获取的计算属性 ====================
  const statistics = computed(() =>
    currentStockCode.value ? dataLayer.getBigOrderStatistics(currentStockCode.value) : null,
  )

  const periods = computed(() =>
    currentStockCode.value ? dataLayer.getBigOrderPeriods(currentStockCode.value) : [],
  )

  const denseAlerts = computed(() => dataLayer.getDenseOrderAlerts(10))

  // ==================== 加载状态 ====================
  const loading = computed(() => bigOrderService.loading.value)
  const error = computed(() => bigOrderService.error.value)

  // ==================== 过滤逻辑 ====================
  const filteredOrders = computed(() => {
    if (!rawOrders.value.length) return []
    if (!hasActiveFilter()) return rawOrders.value
    return fastFilterOrders(rawOrders.value, currentFilter.value)
  })

  const filteredStatistics = computed(() => {
    const orders = filteredOrders.value
    if (!orders.length) return null

    let buyAmount = 0,
      sellAmount = 0
    let mainBuyAmount = 0,
      mainSellAmount = 0
    let igniteCount = 0,
      smashCount = 0
    let buyActiveCount = 0,
      sellActiveCount = 0
    let maxAmount = 0,
      totalAmount = 0

    for (const order of orders) {
      totalAmount += order.amount
      maxAmount = Math.max(maxAmount, order.amount)

      if (order.isBuy) buyAmount += order.amount
      else sellAmount += order.amount

      if (order.type === 2) mainBuyAmount += order.amount
      else if (order.type === 4) mainSellAmount += order.amount

      if (order.fundMarker === '点火') igniteCount++
      else if (order.fundMarker === '砸盘') smashCount++

      if (order.buyMarker === '买活跃') buyActiveCount++
      else if (order.buyMarker === '承接好') sellActiveCount++
    }

    return {
      buyAmount,
      sellAmount,
      netBuy: buyAmount - sellAmount,
      mainBuyAmount,
      mainSellAmount,
      igniteCount,
      smashCount,
      buyActiveCount,
      sellActiveCount,
      totalCount: orders.length,
      avgAmount: totalAmount / orders.length,
      maxAmount,
    }
  })

  function hasActiveFilter(): boolean {
    const f = currentFilter.value
    return !!(
      f.minAmount ||
      f.maxAmount ||
      f.minVolume ||
      f.maxVolume ||
      f.fundMarker ||
      f.buyMarker ||
      (f.types && f.types.length) ||
      f.startTime ||
      f.endTime
    )
  }

  function fastFilterOrders(orders: BigOrderItem[], filter: BigOrderFilter): BigOrderItem[] {
    const filterKey = JSON.stringify(filter)
    const cached = filterCache.get(filterKey)
    if (cached && Date.now() - cached.timestamp < FILTER_CACHE_TTL) {
      return cached.orders
    }

    const result: BigOrderItem[] = []
    const minYuan = filter.minAmount ? filter.minAmount * 10000 : 0
    const maxYuan = filter.maxAmount ? filter.maxAmount * 10000 : Infinity

    for (const order of orders) {
      if (minYuan && order.amount < minYuan) continue
      if (maxYuan !== Infinity && order.amount > maxYuan) continue
      if (filter.minVolume && order.volume < filter.minVolume) continue
      if (filter.maxVolume && order.volume > filter.maxVolume) continue
      if (filter.types?.length && !filter.types.includes(order.type)) continue
      if (filter.fundMarker && order.fundMarker !== filter.fundMarker) continue
      if (filter.buyMarker && order.buyMarker !== filter.buyMarker) continue

      if (filter.startTime || filter.endTime) {
        const orderTime = new Date(order.time).getTime()
        if (filter.startTime && orderTime < filter.startTime) continue
        if (filter.endTime && orderTime > filter.endTime) continue
      }

      result.push(order)
    }

    filterCache.set(filterKey, { orders: result, timestamp: Date.now() })
    if (filterCache.size > 50) {
      const entries = Array.from(filterCache.entries())
      entries.sort((a, b) => a[1].timestamp - b[1].timestamp)
      filterCache.delete(entries[0][0])
    }

    return result
  }

  // ==================== 核心方法 ====================
  async function loadStockData(stockCode: string, stockName: string = '') {
    if (loading.value && currentStockCode.value === stockCode) {
      return rawOrders.value
    }

    currentStockCode.value = stockCode
    currentStockName.value = stockName
    resetFilter()

    try {
      // 先尝试从缓存读取
      const cacheKey = `${CACHE_KEYS.ORDERS}:${stockCode}`
      const cached = quoteCache.get(cacheKey) as BigOrderItem[] | null
      if (cached) {
        debugLog(`[BigOrderStore] 使用缓存数据: ${stockCode}, ${cached.length}条`)
        initPagination(cached)
        return rawOrders.value
      }

      // 尝试从 DataLayer 读取
      const layerData = dataLayer.getBigOrders(stockCode)
      if (layerData.length > 0) {
        debugLog(`[BigOrderStore] 使用 DataLayer 数据: ${stockCode}, ${layerData.length}条`)
        quoteCache.setWithType(cacheKey, layerData, CACHE_KEYS.ORDERS, [stockCode])
        initPagination(layerData)
        return rawOrders.value
      }

      // 从 API 获取
      debugLog(`[BigOrderStore] 从API获取: ${stockCode}`)
      const result = await bigOrderService.fetchAllDay(stockCode)

      if (result.allOrders.length) {
        await bigOrderService.processAndStore(stockCode, stockName, result.allOrders)
        quoteCache.setWithType(cacheKey, result.allOrders, CACHE_KEYS.ORDERS, [stockCode])

        // 初始化分页（只取前500条）
        initPagination(result.allOrders)
      }

      return rawOrders.value
    } catch (error) {
      console.error('[BigOrderStore] 加载失败:', error)
      return []
    }
  }

  function initPagination(allData: BigOrderItem[]) {
    const PAGE_SIZE = 500
    rawOrders.value = allData.slice(0, PAGE_SIZE)
    loadedCount.value = rawOrders.value.length
    totalCount.value = allData.length
    hasMore.value = allData.length > PAGE_SIZE
  }

  async function loadMore() {
    if (!currentStockCode.value || !hasMore.value || loading.value) return

    try {
      const allData = dataLayer.getBigOrders(currentStockCode.value)
      if (!allData?.length) return

      const BATCH_SIZE = 200
      const nextBatch = allData.slice(loadedCount.value, loadedCount.value + BATCH_SIZE)

      if (nextBatch.length) {
        rawOrders.value = [...rawOrders.value, ...nextBatch]
        loadedCount.value += nextBatch.length
        hasMore.value = loadedCount.value < allData.length
      } else {
        hasMore.value = false
      }
    } catch (error) {
      console.error('[BigOrderStore] 加载更多失败:', error)
    }
  }

  async function refresh(limit: number = 100) {
    if (!currentStockCode.value) return []

    try {
      // ✅ 只调用一次，service 会处理一切
      const result = await bigOrderService.fetchLatest(
        currentStockCode.value,
        currentStockName.value, // 传入股票名称，触发自动处理
        limit,
      )

      if (result.orders.length) {
        // ✅ 直接从 dataLayer 获取已处理的数据
        const processedOrders = dataLayer.getBigOrders(currentStockCode.value)

        // 更新无限滚动数据
        rawOrders.value = processedOrders.slice(0, 500)
        loadedCount.value = rawOrders.value.length
        totalCount.value = processedOrders.length
        hasMore.value = processedOrders.length > 500

        // 清除筛选缓存
        filterCache.clear()

        debugLog(`[BigOrderStore] 刷新完成:`, {
          新增: result.newCount,
          总计: processedOrders.length,
          已加载: loadedCount.value,
        })
      }

      return result.orders
    } catch (error) {
      console.error('[BigOrderStore] 刷新失败:', error)
      return []
    }
  }
  // ==================== 筛选方法 ====================
  function setFilter(filter: Partial<BigOrderFilter>) {
    if (filterDebounceTimer) clearTimeout(filterDebounceTimer)
    filterDebounceTimer = setTimeout(() => applyFilter(filter), 300) as unknown as number
  }

  function applyFilter(filter: Partial<BigOrderFilter>) {
    // 互斥逻辑
    if (filter.fundMarker !== undefined) filter.buyMarker = undefined
    if (filter.buyMarker !== undefined) filter.fundMarker = undefined

    currentFilter.value = { ...currentFilter.value, ...filter }
  }

  function setTimeRange(startTime?: number | Date, endTime?: number | Date) {
    const newFilter: Partial<BigOrderFilter> = {}
    if (startTime) newFilter.startTime = new Date(startTime).getTime()
    if (endTime) newFilter.endTime = new Date(endTime).getTime()
    setFilter(newFilter)
  }

  function setTypes(types: (1 | 2 | 3 | 4)[]) {
    setFilter({ types: types?.length ? types : undefined })
  }

  function setVolumeRange(minVolume?: number, maxVolume?: number) {
    setFilter({
      minVolume: minVolume && minVolume > 0 ? minVolume : undefined,
      maxVolume: maxVolume && maxVolume > 0 ? maxVolume : undefined,
    })
  }

  function setAmountRange(minAmount?: number, maxAmount?: number) {
    setFilter({
      minAmount: minAmount && minAmount > 0 ? minAmount : undefined,
      maxAmount: maxAmount && maxAmount > 0 ? maxAmount : undefined,
    })
  }

  function resetFilter() {
    currentFilter.value = {
      minAmount: undefined,
      maxAmount: undefined,
      minVolume: undefined,
      maxVolume: undefined,
      fundMarker: undefined,
      buyMarker: undefined,
      types: undefined,
      timeRange: undefined,
      startTime: undefined,
      endTime: undefined,
    }
  }

  function clear() {
    if (currentStockCode.value) {
      quoteCache.delete(`${CACHE_KEYS.ORDERS}:${currentStockCode.value}`)
      quoteCache.delete(`${CACHE_KEYS.STATS}:${currentStockCode.value}`)
      quoteCache.delete(`${CACHE_KEYS.PERIODS}:${currentStockCode.value}`)
    }

    currentStockCode.value = ''
    currentStockName.value = ''
    rawOrders.value = []
    loadedCount.value = 0
    totalCount.value = 0
    hasMore.value = false
    resetFilter()
    filterCache.clear()
  }

  // ==================== 返回 ====================
  return {
    // 基础状态
    currentStockCode,
    currentStockName,
    currentFilter,

    // 分页状态
    loadedCount,
    totalCount,
    hasMore,

    // 数据
    orders: fullOrders,
    statistics,
    periods,
    denseAlerts,
    filteredOrders,
    filteredStatistics,

    // 加载状态
    loading,
    error,

    // 方法
    loadStockData,
    loadMore,
    refresh,
    setFilter,
    setTimeRange,
    setTypes,
    setVolumeRange,
    setAmountRange,
    resetFilter,
    clear,
  }
})
