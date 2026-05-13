import { debugLog } from '@/utils/logger'
// src/stores/stock.ts
import { defineStore } from 'pinia'
import { ref, computed, shallowRef } from 'vue'
import type { Stock, MarketMode } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import { dataLayer } from '@/services/DataLayer'
import type { MergedStock } from '@/types'
import { dragonReviewService } from '@/services/dragon/DragonReviewService'

// 批量更新配置
const BATCH_UPDATE_DELAY = 100 // 100ms
const MAX_BATCH_SIZE = 50

export const useStockStore = defineStore('stock', () => {
  // ===== 状态定义 =====
  const stocks = shallowRef<Stock[]>([])
  const loading = ref(false)
  const lastUpdate = ref<number | null>(null)
  const selectedCode = ref<string | null>(null)
  const error = ref<string | null>(null)
  const marketMode = ref<MarketMode>('hybrid')
  const version = ref(0)

  // 批量更新队列
  const pendingUpdates = new Map<string, Partial<Stock>>()
  let batchTimer: ReturnType<typeof setTimeout> | null = null

  // 缓存 Map
  const stockMap = new Map<string, Stock>()

  function normalizeStock(stock: MergedStock): Stock {
    return {
      ...stock,
      name: stock.name || stock.code || '-',
      emRank: stock.emRank ?? 9999,
      thsRank: stock.thsRank ?? 9999,
      kplRank: stock.kplRank ?? 9999,
      tdxRank: stock.tdxRank ?? 9999,
      xqRank: stock.xqRank ?? 9999,
      clsRank: stock.clsRank ?? 9999,
      tgbRank: stock.tgbRank ?? 9999,
      dzhRank: stock.dzhRank ?? 9999,
      platforms: stock.platforms ?? 0,
      avgRankNum: stock.avgRankNum ?? 9999,
      avgRank: stock.avgRank ?? '-',
      compRank: stock.compRank ?? 9999,
      compScore: stock.compScore ?? 0,
      isSectorLeader: (stock as Stock).isSectorLeader ?? false,
      leaderLevel: (stock as Stock).leaderLevel ?? '非龙头',
      leaderScore: (stock as Stock).leaderScore ?? 0,
      continuousDays: stock.continuousDays ?? 1,
      themes: stock.themes ?? [],
      updatedAt: stock.updatedAt ?? Date.now(),
      hotScore: 0,
    }
  }

  // 缓存计算值 - 移除 private
  const leadersCache = computed(() => stocks.value.filter((s) => s.isSectorLeader))
  const leadersByLevelCache = new Map<string, Stock[]>()

  // 重试相关
  let retryCount = 0
  const maxRetries = 5
  let retryTimer: ReturnType<typeof setTimeout> | null = null

  // ===== 计算属性 =====
  const isReady = computed(() => stocks.value.length > 0 && !loading.value)
  const totalCount = computed(() => stocks.value.length)

  const leaders = computed(() => leadersCache.value)

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

    // 更新缓存
    Object.entries(result).forEach(([level, list]) => {
      leadersByLevelCache.set(level, list)
    })

    return result
  })

  const selectedStock = computed(() =>
    selectedCode.value ? stockMap.get(selectedCode.value) : undefined
  )

  // ===== 工具函数 =====
  const scheduleRetry = () => {
    if (retryCount >= maxRetries) {
      console.warn('[StockStore] 达到最大重试次数，停止重试')
      return
    }

    const delay = Math.min(3000 * Math.pow(2, retryCount), 30000)
    debugLog(`[StockStore] 计划重试 (${retryCount + 1}/${maxRetries})，${delay}ms后`)

    if (retryTimer) {
      clearTimeout(retryTimer)
    }

    retryTimer = setTimeout(() => {
      retryCount++
      loadStocks(true)
    }, delay)
  }

  // ===== 个股热度分计算 =====
  function calculateHotScore(stock: Stock): number {
    let score = 0
    const { change, continuousDays, isSectorLeader, leaderLevel, compRank, zlje, turnover } = stock

    // 涨停加成
    if (change && change > 9.5) {
      score += 100
      if (continuousDays && continuousDays > 1) {
        score += Math.min((continuousDays - 1) * 50, 200) // 上限200分
      }
    }

    // 龙头加成
    if (isSectorLeader) {
      const leaderScores: Record<string, number> = {
        总龙头: 200,
        连板龙头: 150,
        板块龙头: 100,
        中军龙头: 80,
        情绪龙头: 60,
      }
      score += leaderScores[leaderLevel] || 50
    }

    // 排名加成（前50名）
    if (compRank && compRank <= 50) {
      score += Math.max(0, 50 - compRank)
    }

    // 资金加成（上限100分）
    if (zlje && zlje > 0) {
      score += Math.min(Math.floor(zlje / 10000000), 100)
    }

    // 成交额加成（上限50分）
    if (turnover && turnover > 0) {
      score += Math.min(Math.floor(turnover / 100000000), 50)
    }

    return score
  }

  // ===== 更新股票缓存 =====
  function updateStockCache() {
    stockMap.clear()
    stocks.value.forEach(stock => {
      stockMap.set(stock.code, stock)
    })
  }

  // ===== 应用批量更新 =====
  function applyBatchUpdates() {
    if (pendingUpdates.size === 0) return

    const startTime = performance.now()
    let updatedCount = 0

    const newStocks = stocks.value.map(stock => {
      const updates = pendingUpdates.get(stock.code)
      if (updates) {
        updatedCount++
        const updatedStock = { ...stock, ...updates }
        updatedStock.hotScore = calculateHotScore(updatedStock)
        return updatedStock
      }
      return stock
    })

    stocks.value = newStocks

    // 更新缓存
    updateStockCache()

    // 清空队列
    pendingUpdates.clear()

    // 触发版本更新
    version.value++

    if (updatedCount > 0) {
      debugLog(`[StockStore] 📦 批量更新完成: ${updatedCount}只股票`)
    }
  }

  // ===== 添加到更新队列 =====
  function queueUpdate(code: string, data: Partial<Stock>) {
    const existing = pendingUpdates.get(code) || {}
    pendingUpdates.set(code, { ...existing, ...data })

    if (!batchTimer) {
      batchTimer = setTimeout(() => {
        batchTimer = null
        applyBatchUpdates()
      }, BATCH_UPDATE_DELAY)
    }

    // 如果队列太大，立即处理
    if (pendingUpdates.size >= MAX_BATCH_SIZE && batchTimer) {
      clearTimeout(batchTimer)
      batchTimer = null
      applyBatchUpdates()
    }
  }

  // ===== 加载股票数据 =====
  async function loadStocks(force = false) {
    if (loading.value && !force) return

    const startTime = performance.now()
    loading.value = true
    error.value = null

    try {
      const data = dataLayer.getStocks()

      if (data && data.length > 0) {
        // 批量计算热度分
        const processedData = data.map((stock) => {
          const normalized = normalizeStock(stock)
          normalized.hotScore = calculateHotScore(normalized)
          return normalized
        })

        stocks.value = processedData
        updateStockCache()

        lastUpdate.value = Date.now()
        version.value++

        // 重置重试计数
        retryCount = 0


        // 触发就绪事件
        EventManager.emit('stock:ready', {
          count: stocks.value.length,
          version: version.value,
        })

        debugLog(`[StockStore] ✅ 加载完成: ${stocks.value.length}只股票`)
      } else {
        stocks.value = []
        stockMap.clear()
        console.warn('[StockStore] ⚠️ 无数据，计划重试')
        scheduleRetry()
      }
    } catch (err) {
      console.error('[StockStore] ❌ 加载失败:', err)
      error.value = err instanceof Error ? err.message : '加载失败'
      stocks.value = []
      stockMap.clear()

      scheduleRetry()
    } finally {
      loading.value = false
    }
  }

  // ===== 刷新龙头数据 =====
  function refreshLeaders() {
    if (stocks.value.length === 0) return 0

    const leaders = dragonReviewService.getAllLeaders?.() || []
    const leaderMap = new Map()

    leaders.forEach((leader: any) => {
      leaderMap.set(leader.code, {
        isSectorLeader: true,
        leaderLevel: leader.levelName,
        leaderScore: leader.score,
        leaderReasons: leader.reasons,
        continuousDays: leader.continuousDays,
      })
    })

    let updatedCount = 0
    const newStocks = stocks.value.map(stock => {
      const leaderInfo = leaderMap.get(stock.code)
      if (leaderInfo) {
        updatedCount++
        const updatedStock = { ...stock, ...leaderInfo }
        updatedStock.hotScore = calculateHotScore(updatedStock)
        return updatedStock
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

    stocks.value = newStocks
    updateStockCache()
    version.value++

    if (updatedCount > 0) {
      debugLog(`[StockStore] 🔄 刷新龙头: ${updatedCount}只`)
    }

    return updatedCount
  }

  // ===== 更新单个股票 =====
  function updateStock(code: string, data: Partial<Stock>) {
    queueUpdate(code, data)
  }

  // ===== 批量更新 =====
  function batchUpdate(updates: Array<{ code: string; data: Partial<Stock> }>) {
    updates.forEach(({ code, data }) => {
      const existing = pendingUpdates.get(code) || {}
      pendingUpdates.set(code, { ...existing, ...data })
    })

    if (!batchTimer) {
      batchTimer = setTimeout(() => {
        batchTimer = null
        applyBatchUpdates()
      }, BATCH_UPDATE_DELAY)
    }
  }

  // ===== 获取股票 =====
  function getStockByCode(code: string): Stock | undefined {
    return stockMap.get(code)
  }

  // ===== 切换市场模式 =====
  async function setMarketMode(mode: MarketMode) {
    if (marketMode.value === mode) return

    const oldMode = marketMode.value
    marketMode.value = mode
    await loadStocks()

    EventManager.emit('market:mode-changed', {
      from: oldMode,
      to: mode,
      timestamp: Date.now(),
    })
  }

  // ===== 选择股票 =====
  function selectStock(code: string | null) {
    selectedCode.value = code
    if (code) {
      EventManager.emit(AppEvents.STOCK.SELECTED, { code })
    }
  }

  // ===== 等待数据就绪 =====
  async function waitForReady(timeout = 10000): Promise<boolean> {
    if (stocks.value.length > 0) return true

    return new Promise((resolve) => {
      const startTime = Date.now()
      const checkInterval = setInterval(() => {
        if (stocks.value.length > 0) {
          clearInterval(checkInterval)
          resolve(true)
        } else if (Date.now() - startTime > timeout) {
          clearInterval(checkInterval)
          resolve(false)
        }
      }, 200)
    })
  }

  // ===== 监听增量更新器的事件 =====
  function setupIncrementalListeners(): (() => void)[] {
    const listeners: (() => void)[] = []

    // 监听行情更新（WebSocket）
    const unsubQuotes = EventManager.on(AppEvents.STOCK.QUOTES_UPDATED, (data: any) => {
      if (data?.changes?.length > 0) {
        const updates = data.changes.map((change: any) => ({
          code: change.code,
          data: {
            price: change.price,
            change: change.change,
            volume: change.volume,
            turnover: change.turnover,
            turnoverRate: change.turnoverRate,
            updatedAt: Date.now(),
          }
        }))
        batchUpdate(updates)
      }
    })
    listeners.push(unsubQuotes)

    // 监听龙头变化
    const unsubDragon = EventManager.on(AppEvents.DRAGON.UPDATED, (data: any) => {
      if (data?.changes) {
        refreshLeaders()
      }
    })
    listeners.push(unsubDragon)

    // 监听题材更新
    const unsubSector = EventManager.on(AppEvents.SECTOR.UPDATED, () => {
      loadStocks()
    })
    listeners.push(unsubSector)

    // 监听增量更新器任务失败（可选）
    const unsubTaskFailed = EventManager.on('incremental:task-failed', (data: any) => {
      console.warn('[StockStore] 增量更新任务失败:', data)
    })
    listeners.push(unsubTaskFailed)

    return listeners
  }

  // ===== 监听刷新管理器的事件 =====
  function setupRefreshListeners(): (() => void)[] {
    const listeners: (() => void)[] = []

    // 监听增量刷新请求
    const unsubIncremental = EventManager.on(AppEvents.REFRESH.INCREMENTAL_REQUESTED, () => {
      debugLog('[StockStore] 📥 收到增量刷新请求')
    })
    listeners.push(unsubIncremental)

    // 监听全量刷新完成
    const unsubFullComplete = EventManager.on(AppEvents.REFRESH.COMPLETE, (data: any) => {
      if (data?.type === 'full') {
        debugLog('[StockStore] 📥 全量刷新完成，重新加载数据')
        loadStocks()
      }
    })
    listeners.push(unsubFullComplete)

    // 监听刷新失败
    const unsubRefreshFailed = EventManager.on(AppEvents.REFRESH.FAILED, (data: any) => {
      console.warn('[StockStore] 刷新失败:', data)
    })
    listeners.push(unsubRefreshFailed)

    return listeners
  }

  // ===== 初始化 =====
  function init() {
    debugLog('[StockStore] 📊 初始化...')

    // 保存所有取消函数
    const unsubscribeFns: (() => void)[] = []

    // 设置监听器
    unsubscribeFns.push(...setupIncrementalListeners())
    unsubscribeFns.push(...setupRefreshListeners())

    // 保留 DataLayer 订阅作为后备
    const unsubStocks = dataLayer.subscribe('merged.stocks', () => {
      debugLog('[StockStore] 📥 收到 DataLayer 更新')
      if (retryTimer) {
        clearTimeout(retryTimer)
        retryTimer = null
        retryCount = 0
      }
      loadStocks()
    })
    unsubscribeFns.push(unsubStocks)

    // 监听数据合并事件
    const unsubMerged = EventManager.on(AppEvents.DATA.MERGED, () => {
      debugLog('[StockStore] 📥 收到数据合并事件')
      loadStocks()
    })
    unsubscribeFns.push(unsubMerged)

    // 立即加载一次
    loadStocks()

    debugLog('[StockStore] ✅ 初始化完成')

    // 返回清理函数
    return () => {
      debugLog('[StockStore] 🧹 清理监听器')
      unsubscribeFns.forEach(fn => fn())
      if (retryTimer) {
        clearTimeout(retryTimer)
        retryTimer = null
      }
      if (batchTimer) {
        clearTimeout(batchTimer)
        batchTimer = null
      }
      pendingUpdates.clear()
      stockMap.clear()
    }
  }

  return {
    // 状态
    stocks,
    loading,
    lastUpdate,
    selectedCode,
    error,
    marketMode,
    version,

    // 计算属性
    isReady,
    totalCount,
    leaders,
    leadersByLevel,
    selectedStock,

    // 方法
    loadStocks,
    selectStock,
    updateStock,
    batchUpdate,
    getStockByCode,
    calculateHotScore,
    refreshLeaders,
    setMarketMode,
    waitForReady,
    init,

    // 调试用
    getPendingUpdatesCount: () => pendingUpdates.size,
  }
})
