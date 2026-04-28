import { debugLog } from '@/utils/logger'
// src/services/big-order/BigOrderService.ts
// 注意：已移除增量刷新相关代码，只保留全量刷新

import { ref } from 'vue'
import { apiService } from '@/services/apiService'
import { dataLayer } from '@/services/DataLayer'
import { BigOrderMarker } from './BigOrderMarker'
import { isTradingTime } from '@/utils/time'
import { voiceService } from '@/services/VoiceService'
import type {
  BigOrderItem,
  BigOrderStatistics,
  PeriodStatistics,
  BigOrderFilter,
  DenseOrderAlert,
} from '@/types/big-order'
import { MARKER_THRESHOLDS, PERIODS } from '@/config/constants'

const BIG_ORDER_CONTEXT = 'big-order' as any

function toTime(value: string | Date): number {
  return new Date(value).getTime()
}

export class BigOrderService {
  private static instance: BigOrderService
  private marker = BigOrderMarker.getInstance()

  // 请求跟踪
  private pendingRequests = new Map<string, Promise<any>>()

  // 添加预加载状态
  public preloadedStocks = new Set<string>() // 已预加载的股票
  private preloadPending = new Set<string>() // 预加载去重

  // 响应式状态
  public loading = ref(false)
  public error = ref<string | null>(null)
  public progress = ref(0)

  private constructor() {
    debugLog('[BigOrderService] 初始化完成')

    // 延迟启动预加载，给 dataLayer 一点时间初始化
    setTimeout(() => {
      this.autoPreload()
    }, 3000) // 3秒后自动预加载
  }

  /**
   * 自动预加载（内部调用）
   */
  private async autoPreload(): Promise<void> {
    setTimeout(() => {
      this.preloadHotStocks(3) // 只预加载3只
    }, 5000)
  }

  static getInstance(): BigOrderService {
    if (!BigOrderService.instance) {
      BigOrderService.instance = new BigOrderService()
    }
    return BigOrderService.instance
  }

  // ==================== 核心API方法 ====================
  /**
   * 获取全天大单数据
   */
  async fetchAllDay(
    stockCode: string,
    money: number = 0,
  ): Promise<{
    allOrders: BigOrderItem[]
    total: number
  }> {
    const requestKey = `allDay_${stockCode}_${money}`

    // 检查是否正在请求中
    if (this.pendingRequests.has(requestKey)) {
      return this.pendingRequests.get(requestKey)!
    }

    this.loading.value = true
    this.error.value = null
    this.progress.value = 0

    const promise = (async () => {
      try {
        const url = `/api/big-order/all-day?stockCode=${stockCode}&money=${money}`
        const response = await apiService.get(url, { context: BIG_ORDER_CONTEXT })

        if (!response || response.error) {
          return { allOrders: [], total: 0 }
        }

        const list = response.List || []
        if (!Array.isArray(list) || list.length === 0) {
          return { allOrders: [], total: 0 }
        }

        const allOrders = await this.parseOrdersBatched(list)
        this.progress.value = 100

        return { allOrders, total: list.length }
      } catch (error) {
        console.error('[BigOrderService] 获取失败:', error)
        this.error.value = error instanceof Error ? error.message : '获取失败'
        return { allOrders: [], total: 0 }
      } finally {
        this.loading.value = false
        this.pendingRequests.delete(requestKey)
        setTimeout(() => {
          this.progress.value = 0
        }, 1000)
      }
    })()

    this.pendingRequests.set(requestKey, promise)
    return promise
  }

  /**
   * 获取最新大单数据（用于刷新）- 移除增量逻辑
   */
  async fetchLatest(
    stockCode: string,
    stockName?: string,
    limit: number = 100,
  ): Promise<{
    orders: BigOrderItem[]
    total: number
    newCount: number
  }> {
    const requestKey = `latest_${stockCode}_${limit}`

    // 防抖：避免重复请求
    if (this.pendingRequests.has(requestKey)) {
      return this.pendingRequests.get(requestKey)!
    }

    this.loading.value = true
    this.error.value = null

    const promise = (async () => {
      try {
        // 1. 获取最新数据
        const response = await apiService.get(
          `/api/big-order/main-monitor?stockCode=${encodeURIComponent(stockCode)}&limit=${limit}`,
          {
          context: BIG_ORDER_CONTEXT,
          },
        )

        const list = response.List || []
        const newOrders = this.parseOrders(list)

        let processedOrders: BigOrderItem[] = []
        let newCount = 0

        // 2. 如果有新数据且提供了股票名称，进行合并处理
        if (newOrders.length > 0 && stockName) {
          // 获取现有数据
          const existingData = dataLayer.getBigOrderData(stockCode)
          const existingOrders = existingData?.orders || []

          // 计算新增数量（去重后）
          const existingKeys = new Set(
            existingOrders.map(
              (o: BigOrderItem) => `${Math.floor(toTime(o.time) / 60000)}_${o.amount}_${o.type}`,
            ),
          )

          newCount = newOrders.filter(
            (o) =>
              !existingKeys.has(`${Math.floor(toTime(o.time) / 60000)}_${o.amount}_${o.type}`),
          ).length

          // 如果有真正的新数据，才进行合并处理
          if (newCount > 0) {
            // 合并去重
            const allOrders = this.mergeAndDeduplicate(newOrders, existingOrders)

            // 3. 重新处理所有数据（重新计算标记）
            await this.processAndStore(stockCode, stockName, allOrders, false)

            // 4. 从 dataLayer 获取处理后的数据
            processedOrders = dataLayer.getBigOrders(stockCode)
          } else {
            // 没有新数据，直接返回现有数据
            processedOrders = dataLayer.getBigOrders(stockCode)
          }
        } else if (newOrders.length > 0 && !stockName) {
          // 没有股票名称，返回原始数据（未处理）
          processedOrders = newOrders
          newCount = newOrders.length
        } else {
          // 没有新数据，返回现有数据
          processedOrders = dataLayer.getBigOrders(stockCode)
        }

        return {
          orders: processedOrders,
          total: processedOrders.length,
          newCount,
        }
      } catch (error) {
        console.error('[BigOrderService] 获取最新失败:', error)
        this.error.value = error instanceof Error ? error.message : '获取失败'
        return { orders: [], total: 0, newCount: 0 }
      } finally {
        this.loading.value = false
        this.pendingRequests.delete(requestKey)

        // 延迟重置进度
        setTimeout(() => {
          this.progress.value = 0
        }, 1000)
      }
    })()

    this.pendingRequests.set(requestKey, promise)
    return promise
  }

  private mergeAndDeduplicate(
    newOrders: BigOrderItem[],
    existingOrders: BigOrderItem[],
  ): BigOrderItem[] {
    const seen = new Set()
    const allOrders = [...newOrders, ...existingOrders]

    // 按时间倒序排序（最新的在前）
    const sorted = allOrders.sort((a, b) => toTime(b.time) - toTime(a.time))

    // 去重：使用分钟级时间戳+金额+类型作为唯一标识
    return sorted.filter((order) => {
      const timeKey = Math.floor(toTime(order.time) / 60000) // 分钟级
      const key = `${timeKey}_${order.amount}_${order.type}`

      if (seen.has(key)) {
        return false
      }
      seen.add(key)
      return true
    })
  }

  // ==================== 数据处理 ====================
  /**
   * 解析原始数据为订单对象
   */
  private parseOrders(list: any[]): BigOrderItem[] {
    if (!Array.isArray(list)) return []

    const orders: BigOrderItem[] = []

    for (const item of list) {
      if (!Array.isArray(item) || item.length < 6) continue

      try {
        const orderId = String(item[1]).trim()
        const type = Number(item[0]) as 1 | 2 | 3 | 4
        const volume = Number(item[2])
        const amount = Number(item[3])
        const price = Number(item[4])
        const time = new Date(item[5])

        if (type < 1 || type > 4 || volume <= 0 || amount <= 0 || price <= 0) continue
        if (isNaN(time.getTime())) continue

        const uniqueId = `${orderId}_${Math.random().toString(36).substring(2, 8)}`

        orders.push({
          id: uniqueId,
          type,
          volume,
          amount,
          price,
          time,
          fundMarker: '',
          buyMarker: '',
          typeName: this.getTypeName(type),
          amountStr: this.formatAmount(amount),
          timeStr: this.formatTime(time),
          isBuy: type === 2 || type === 3,
          isSell: type === 1 || type === 4,
        })
      } catch {
        // 忽略解析失败的条目
      }
    }

    return orders
  }

  /**
   * 分批解析原始数据（用于大数据量）
   */
  private async parseOrdersBatched(list: any[]): Promise<BigOrderItem[]> {
    if (!Array.isArray(list)) return []

    const orders: BigOrderItem[] = []
    const BATCH_SIZE = 500

    for (let i = 0; i < list.length; i += BATCH_SIZE) {
      const batch = list.slice(i, i + BATCH_SIZE)
      const batchOrders = this.parseOrders(batch)
      orders.push(...batchOrders)

      this.progress.value = Math.floor(((i + batch.length) / list.length) * 100)
      await new Promise((resolve) => setTimeout(resolve, 0))
    }

    return orders
  }

  /**
   * 处理并存储大单数据 - 移除 isIncremental 参数逻辑
   */
  async processAndStore(
    stockCode: string,
    stockName: string,
    allOrders: BigOrderItem[],
    isFullRefresh: boolean = true, // 改为 isFullRefresh，默认为全量
  ) {
    if (!allOrders.length) {
      return {
        orders: [],
        statistics: this.getEmptyStatistics(),
        periods: this.getEmptyPeriods(),
        denseAlerts: [],
      }
    }

    // 分批计算标记（大数据量时优化）
    const MARK_BATCH_SIZE = 1000
    let markedOrders: BigOrderItem[] = []

    for (let i = 0; i < allOrders.length; i += MARK_BATCH_SIZE) {
      const batch = allOrders.slice(i, i + MARK_BATCH_SIZE)
      const markedBatch = this.marker.calculateMarkers(batch)
      markedOrders = markedOrders.concat(markedBatch)

      // 每批处理后更新UI
      const currentSorted = [...markedOrders].sort(
        (a, b) => new Date(b.time).getTime() - new Date(a.time).getTime(),
      )

      dataLayer.updateBigOrderData(
        stockCode,
        currentSorted,
        this.calculateStatistics(markedOrders),
        this.calculatePeriodStatistics(markedOrders),
      )

      this.progress.value = Math.floor(((i + batch.length) / allOrders.length) * 100)

      // 让出事件循环，避免阻塞UI
      await new Promise((resolve) => setTimeout(resolve, 0))
    }

    // 最终全量数据
    const sortedOrders = markedOrders.sort(
      (a, b) => new Date(b.time).getTime() - new Date(a.time).getTime(),
    )
    const statistics = this.calculateStatistics(markedOrders)
    const periods = this.calculatePeriodStatistics(markedOrders)
    const denseAlerts = this.detectDenseOrders(stockCode, stockName, markedOrders)

    // 存储到 dataLayer
    dataLayer.updateBigOrderData(stockCode, sortedOrders, statistics, periods)

    // 添加密集告警
    denseAlerts.forEach((alert) => dataLayer.addDenseOrderAlert(alert))

    // 全量刷新时才播报
    if (isFullRefresh) {
      const latestOrders = sortedOrders.slice(0, 5)
      latestOrders.forEach((order) => {
        if (order.fundMarker === '点火') {
          voiceService.speak(`${stockName}点火，${order.amountStr}`)
        } else if (order.fundMarker === '砸盘') {
          voiceService.speak(`${stockName}砸盘，${order.amountStr}`)
        }
      })
    }

    return {
      orders: sortedOrders,
      totalOrders: markedOrders.length,
      statistics,
      periods,
      denseAlerts,
    }
  }

  // ==================== 辅助方法 ====================
  private formatAmount(amount: number): string {
    const amountWan = amount / 10000
    if (amountWan >= 10000) return `${(amountWan / 10000).toFixed(1)}亿`
    return `${amountWan.toFixed(0)}万`
  }

  private formatTime(time: Date): string {
    return time.toLocaleTimeString('zh-CN', { hour12: false })
  }

  private getTypeName(type: number): string {
    const names = { 1: '被动卖', 2: '主动买', 3: '被动买', 4: '主动卖' }
    return names[type as keyof typeof names] || '未知'
  }

  private getEmptyStatistics(): BigOrderStatistics {
    return {
      buyAmount: 0,
      sellAmount: 0,
      netBuy: 0,
      mainBuyAmount: 0,
      mainSellAmount: 0,
      igniteCount: 0,
      smashCount: 0,
      buyActiveCount: 0,
      sellActiveCount: 0,
      totalCount: 0,
      avgAmount: 0,
      maxAmount: 0,
    }
  }

  private getEmptyPeriods(): PeriodStatistics[] {
    return PERIODS.map((p) => ({
      name: p.name,
      start: p.start,
      end: p.end,
      count: 0,
      buyAmount: 0,
      sellAmount: 0,
      netBuy: 0,
      igniteCount: 0,
      smashCount: 0,
      buyActiveCount: 0,
      sellActiveCount: 0,
    }))
  }

  private calculateStatistics(orders: BigOrderItem[]): BigOrderStatistics {
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

    for (const o of orders) {
      totalAmount += o.amount
      maxAmount = Math.max(maxAmount, o.amount)

      if (o.isBuy) buyAmount += o.amount
      else sellAmount += o.amount

      if (o.type === 2) mainBuyAmount += o.amount
      else if (o.type === 4) mainSellAmount += o.amount

      if (o.fundMarker === '点火') igniteCount++
      else if (o.fundMarker === '砸盘') smashCount++

      if (o.buyMarker === '买活跃') buyActiveCount++
      else if (o.buyMarker === '承接好') sellActiveCount++
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
      avgAmount: orders.length ? totalAmount / orders.length : 0,
      maxAmount,
    }
  }

  private calculatePeriodStatistics(orders: BigOrderItem[]): PeriodStatistics[] {
    return PERIODS.map((period) => {
      const periodOrders = orders.filter((o) => {
        const timeStr = new Date(o.time).toLocaleTimeString('zh-CN', {
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
        })
        return timeStr >= period.start && timeStr < period.end
      })

      const buyAmount = periodOrders.filter((o) => o.isBuy).reduce((s, o) => s + o.amount, 0)
      const sellAmount = periodOrders.filter((o) => o.isSell).reduce((s, o) => s + o.amount, 0)

      return {
        name: period.name,
        start: period.start,
        end: period.end,
        count: periodOrders.length,
        buyAmount,
        sellAmount,
        netBuy: buyAmount - sellAmount,
        igniteCount: periodOrders.filter((o) => o.fundMarker === '点火').length,
        smashCount: periodOrders.filter((o) => o.fundMarker === '砸盘').length,
        buyActiveCount: periodOrders.filter((o) => o.buyMarker === '买活跃').length,
        sellActiveCount: periodOrders.filter((o) => o.buyMarker === '承接好').length,
      }
    })
  }

  private detectDenseOrders(
    stockCode: string,
    stockName: string,
    orders: BigOrderItem[],
  ): DenseOrderAlert[] {
    if (!orders || orders.length < MARKER_THRESHOLDS.DENSE_COUNT) return []

    const sorted = [...orders].sort(
      (a, b) => new Date(a.time).getTime() - new Date(b.time).getTime(),
    )

    const alerts: DenseOrderAlert[] = []
    let left = 0

    for (let right = 0; right < sorted.length; right++) {
      const currentTime = new Date(sorted[right].time).getTime()

      while (left < right) {
        const leftTime = new Date(sorted[left].time).getTime()
        if (currentTime - leftTime <= MARKER_THRESHOLDS.DENSE_WINDOW) break
        left++
      }

      const windowOrders = sorted.slice(left, right + 1)
      if (windowOrders.length >= MARKER_THRESHOLDS.DENSE_COUNT) {
        const totalAmount = windowOrders.reduce((sum, o) => sum + o.amount, 0)

        alerts.push({
          stockCode,
          stockName,
          count: windowOrders.length,
          windowMs: MARKER_THRESHOLDS.DENSE_WINDOW,
          totalAmount,
          avgAmount: totalAmount / windowOrders.length,
          timestamp: Date.now(),
        })
      }
    }

    return alerts
  }

  /**
   * 预加载热门股票的大单数据
   */
  public async preloadHotStocks(limit: number = 5): Promise<void> {
    if (this.preloadPending.size > 0) {
      return
    }

    const stocks = this.getHotStocks(limit)

    for (const stock of stocks) {
      if (this.preloadedStocks.has(stock.code)) continue

      this.preloadPending.add(stock.code)

      this.preloadWithRetry(stock, 3).finally(() => {
        this.preloadPending.delete(stock.code)
      })

      await new Promise((resolve) => setTimeout(resolve, 500))
    }
  }

  private async preloadWithRetry(stock: any, retries: number): Promise<void> {
    for (let i = 0; i < retries; i++) {
      try {
        const result = await this.fetchAllDay(stock.code)

        if (result && result.allOrders && result.allOrders.length > 0) {
          await this.processAndStore(stock.code, stock.name, result.allOrders, true)
          this.preloadedStocks.add(stock.code)
          return
        } else {
          await new Promise((resolve) => setTimeout(resolve, 1000 * (i + 1)))
        }
      } catch (error) {
        if (i === retries - 1) break
        await new Promise((resolve) => setTimeout(resolve, 1000 * (i + 1)))
      }
    }
    console.warn(`[BigOrderService] ⚠️ 预加载放弃: ${stock.code}`)
  }

  // ==================== 刷新管理器接口 - 移除增量方法 ====================

  /**
   * 全量刷新 - 供协调者调用
   */
  async runFullUpdate(): Promise<void> {
    if (!isTradingTime()) return
    const stocks = this.getHotStocks(20)
    if (!stocks.length) return
    await this.batchRefreshStocks(stocks)
  }

  async syncData(): Promise<void> {}

  async runMaintenance(): Promise<void> {}

  private getHotStocks(limit: number = 10): any[] {
    const stocks = dataLayer.getStocks() || []
    return stocks
      .filter((s) => s.compRank && s.compRank < 50)
      .sort((a, b) => (a.compRank || 999) - (b.compRank || 999))
      .slice(0, limit)
  }

  /**
   * 批量刷新股票数据 - 只支持全量刷新
   */
  private async batchRefreshStocks(stocks: any[]): Promise<void> {
    const promises = stocks.map(async (stock) => {
      try {
        // 全量：fetchAllDay 只拿数据，手动处理
        const result = await this.fetchAllDay(stock.code)
        if (result.allOrders.length) {
          await this.processAndStore(stock.code, stock.name, result.allOrders, true)
        }
      } catch (error) {
        console.error(`刷新失败: ${stock.code}`, error)
      }
    })
    await Promise.allSettled(promises)
  }
}

export const bigOrderService = BigOrderService.getInstance()
if (typeof window !== 'undefined') {
  ;(window as any).bigOrderService = bigOrderService
}
