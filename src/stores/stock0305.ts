// src/stores/stock.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Stock, MarketMode } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import { dataLayer } from '@/services/DataLayer'
import { dragonAnalyzer } from '@/services/DragonAnalyzer'

export const useStockStore = defineStore('stock', () => {
  const stocks = ref<Stock[]>([])
  const loading = ref(false)
  const lastUpdate = ref<number | null>(null)
  const selectedCode = ref<string | null>(null)
  const error = ref<string | null>(null)
  const marketMode = ref<MarketMode>('hybrid')
  const version = ref(0)

  // ✅ 新增：数据就绪状态
  const isReady = computed(() => stocks.value.length > 0 && !loading.value)

  // ===== 计算属性 =====
  const totalCount = computed(() => stocks.value.length)
  const leaders = computed(() => stocks.value.filter((s) => s.isSectorLeader))
  const leadersByLevel = computed(() => {
    const result: Record<string, Stock[]> = {
      总龙头: [],
      连板龙头: [],
      板块龙头: [],
      中军龙头: [],
      情绪龙头: [],
    }
    leaders.value.forEach((leader) => {
      if (result[leader.leaderLevel]) {
        result[leader.leaderLevel].push(leader)
      }
    })
    return result
  })
  const selectedStock = computed(() => stocks.value.find((s) => s.code === selectedCode.value))

  // ===== 个股热度分计算 =====
  function calculateHotScore(stock: Stock): number {
    let score = 0
    if (stock.change && stock.change > 9.5) {
      score += 100
      if (stock.continuousDays && stock.continuousDays > 1) {
        score += (stock.continuousDays - 1) * 50
      }
    }
    if (stock.isSectorLeader) {
      switch (stock.leaderLevel) {
        case '总龙头':
          score += 200
          break
        case '连板龙头':
          score += 150
          break
        case '板块龙头':
          score += 100
          break
        case '中军龙头':
          score += 80
          break
        case '情绪龙头':
          score += 60
          break
        default:
          score += 50
      }
    }
    if (stock.compRank && stock.compRank <= 50) {
      score += Math.max(0, 50 - stock.compRank)
    }
    if (stock.zlje && stock.zlje > 0) {
      score += Math.floor(stock.zlje / 10000000)
    }
    if (stock.turnover && stock.turnover > 0) {
      score += Math.floor(stock.turnover / 100000000)
    }
    return score
  }

  // ===== 加载股票数据 =====
  async function loadStocks(force = false) {
    if (loading.value && !force) return

    loading.value = true
    error.value = null

    try {
      const data = dataLayer.getStocks()

      if (data && data.length > 0) {
        stocks.value = data.map((stock) => ({
          ...stock,
          name: stock.name || stock.code || '-',
          hotScore: calculateHotScore(stock),
        }))
        lastUpdate.value = Date.now()
        version.value++

        // ✅ 触发就绪事件
        EventManager.emit('stock:ready', {
          count: stocks.value.length,
          version: version.value,
        })
      } else {
        stocks.value = []

        // ✅ 设置一个重试定时器
        setTimeout(() => {
          if (stocks.value.length === 0 && !loading.value) {
            loadStocks()
          }
        }, 3000)
      }
    } catch (err) {
      console.error('[StockStore] ❌ 加载失败:', err)
      error.value = err instanceof Error ? err.message : '加载失败'
      stocks.value = []
    } finally {
      loading.value = false
    }
  }

  // ===== 刷新龙头数据 =====
  function refreshLeaders() {
    if (stocks.value.length === 0) return 0

    const leaders = dragonAnalyzer.getAllLeaders?.() || []
    const leaderMap = new Map()
    leaders.forEach((leader) => {
      leaderMap.set(leader.code, {
        isSectorLeader: true,
        leaderLevel: leader.levelName,
        leaderScore: leader.score,
        leaderReasons: leader.reasons,
        continuousDays: leader.continuousDays,
      })
    })
    let updatedCount = 0
    stocks.value = stocks.value.map((stock) => {
      const leaderInfo = leaderMap.get(stock.code)
      if (leaderInfo) {
        updatedCount++
        return { ...stock, ...leaderInfo }
      }
      return {
        ...stock,
        isSectorLeader: false,
        leaderLevel: '非龙头',
        leaderScore: 0,
        leaderReasons: [],
        continuousDays: stock.continuousDays || 1,
      }
    })
    if (updatedCount > 0) {
    }
    return updatedCount
  }

  // ===== 切换市场模式 =====
  async function setMarketMode(mode: MarketMode) {
    if (marketMode.value === mode) return
    marketMode.value = mode
    await loadStocks()
    EventManager.emit('market:mode-changed', {
      from: marketMode.value,
      to: mode,
      timestamp: Date.now(),
    })
  }

  // ===== 其他方法 =====
  function selectStock(code: string | null) {
    selectedCode.value = code
    if (code) {
      EventManager.emit(AppEvents.STOCK.SELECTED, { code })
    }
  }

  function updateStock(code: string, data: Partial<Stock>) {
    const index = stocks.value.findIndex((s) => s.code === code)
    if (index !== -1) {
      stocks.value[index] = {
        ...stocks.value[index],
        ...data,
        hotScore: calculateHotScore({ ...stocks.value[index], ...data }),
      }
    }
  }

  function batchUpdate(updates: Array<{ code: string; data: Partial<Stock> }>) {
    updates.forEach(({ code, data }) => updateStock(code, data))
  }

  function getStockByCode(code: string): Stock | undefined {
    return stocks.value.find((s) => s.code === code)
  }

  // ===== 同步数据 =====
  function syncFromDataLayer() {
    const data = dataLayer.getStocks()
    if (data && data.length > 0) {
      stocks.value = data.map((stock) => ({
        ...stock,
        hotScore: calculateHotScore(stock),
      }))
      version.value++
    }
  }

  // ===== 等待数据就绪 =====
  async function waitForReady(timeout = 10000): Promise<boolean> {
    if (stocks.value.length > 0) return true

    const startTime = Date.now()

    while (Date.now() - startTime < timeout) {
      if (stocks.value.length > 0) return true
      await new Promise((resolve) => setTimeout(resolve, 200))
    }

    return false
  }

  // ===== 初始化 =====
  let unsubscribe: (() => void) | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null

  function init() {
    if (unsubscribe) return unsubscribe

    // 保存所有取消函数
    const unsubscribeFns: (() => void)[] = []

    // DataLayer 订阅
    const unsubStocks = dataLayer.subscribe('merged.stocks', () => {
      if (retryTimer) {
        clearTimeout(retryTimer)
        retryTimer = null
      }
      loadStocks()
    })
    unsubscribeFns.push(unsubStocks)

    // EventManager 订阅
    const handleSectorUpdate = () => {
      syncFromDataLayer()
    }
    const unsubSector = EventManager.on('sector:updated', handleSectorUpdate)
    unsubscribeFns.push(unsubSector)

    // 立即加载一次
    loadStocks()

    // 返回清理函数，清理所有订阅
    return () => {
      unsubscribeFns.forEach((fn) => fn())
      if (retryTimer) {
        clearTimeout(retryTimer)
        retryTimer = null
      }
    }
  }

  function cleanup() {
    if (unsubscribe) {
      unsubscribe()
      unsubscribe = null
    }
    if (retryTimer) {
      clearTimeout(retryTimer)
      retryTimer = null
    }
  }

  return {
    stocks,
    loading,
    lastUpdate,
    selectedCode,
    error,
    marketMode,
    version,
    isReady, // ✅ 新增
    totalCount,
    leaders,
    leadersByLevel,
    selectedStock,
    loadStocks,
    selectStock,
    updateStock,
    batchUpdate,
    getStockByCode,
    calculateHotScore,
    refreshLeaders,
    setMarketMode,
    syncFromDataLayer,
    waitForReady, // ✅ 新增
    init,
    cleanup,
  }
})
