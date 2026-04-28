import { debugLog } from '@/utils/logger'
// src/services/big-order/BigOrderMarker.ts
import type { BigOrderItem } from '@/types/big-order'
import { MARKER_THRESHOLDS, TIME_WINDOWS } from '@/config/constants'

export class BigOrderMarker {
  private static instance: BigOrderMarker

  private constructor() {}

  static getInstance(): BigOrderMarker {
    if (!BigOrderMarker.instance) {
      BigOrderMarker.instance = new BigOrderMarker()
    }
    return BigOrderMarker.instance
  }

  /**
   * 计算所有标记（点火/砸盘/买活跃/承接好）
   * 完全按照原始 C# 逻辑实现
   */
  calculateMarkers(orders: BigOrderItem[]): BigOrderItem[] {
    if (!orders || orders.length === 0) {
      console.warn('[BigOrderMarker] 订单列表为空')
      return orders
    }

    // 按时间升序排列
    const sortedOrders = [...orders].sort(
      (a, b) => new Date(a.time).getTime() - new Date(b.time).getTime(),
    )

    let prevActiveSellAvg = 0
    let prevActiveBuyAvg = 0
    let igniteCount = 0
    let smashCount = 0
    let buyActiveCount = 0
    let goodSupportCount = 0

    for (let i = 0; i < sortedOrders.length; i++) {
      const order = sortedOrders[i]
      const currentTime = new Date(order.time)

      // 重置标记
      order.fundMarker = ''
      order.buyMarker = ''

      // 只计算交易时间内的数据
      if (!this.isTradingTime(currentTime)) {
        continue
      }

      const timeRanges = this.getTimeRanges(currentTime, sortedOrders, i)

      // 计算资金标记（点火/砸盘）
      this.calculateFundMarker(order, timeRanges.source2)

      // 计算买盘标记（买活跃/承接好）
      this.calculateBuyMarker(
        order,
        timeRanges.source,
        timeRanges.source3,
        i,
        prevActiveBuyAvg,
        prevActiveSellAvg,
      )

      // 统计标记数量
      if (order.fundMarker === '点火') igniteCount++
      if (order.fundMarker === '砸盘') smashCount++
      if (order.buyMarker === '买活跃') buyActiveCount++
      if (order.buyMarker === '承接好') goodSupportCount++

      // 更新上一行平均值
      if (timeRanges.source3.length > 0) {
        const stats = this.calculateAverages(timeRanges.source3)
        prevActiveSellAvg = stats.sellAvg
        prevActiveBuyAvg = stats.buyAvg
      }
    }

    return sortedOrders
  }

  /**
   * 判断是否为交易时间
   */
  private isTradingTime(time: Date): boolean {
    const hours = time.getHours()
    const minutes = time.getMinutes()
    const timeValue = hours * 60 + minutes

    // 上午：9:30-11:30
    const morningStart = 9 * 60 + 30
    const morningEnd = 11 * 60 + 30
    // 下午：13:00-15:00
    const afternoonStart = 13 * 60
    const afternoonEnd = 15 * 60

    return (
      (timeValue >= morningStart && timeValue <= morningEnd) ||
      (timeValue >= afternoonStart && timeValue <= afternoonEnd)
    )
  }

  /**
   * 获取各个时间范围的数据
   */
  private getTimeRanges(currentTime: Date, orders: BigOrderItem[], currentIndex: number) {
    const sixSecondsAgo = new Date(currentTime.getTime() - TIME_WINDOWS.PAST_6S * 1000)
    const fiftySecondsAgo = new Date(currentTime.getTime() - TIME_WINDOWS.PAST_50S * 1000)
    const sixSecondsLater = new Date(currentTime.getTime() + TIME_WINDOWS.FUTURE_6S * 1000)

    return {
      // 过去6秒的数据（不包括当前）
      source: orders.slice(0, currentIndex).filter((o) => new Date(o.time) >= sixSecondsAgo),
      // 过去50秒的数据（不包括当前）
      source2: orders.slice(0, currentIndex).filter((o) => new Date(o.time) >= fiftySecondsAgo),
      // 未来6秒的数据（包括当前）
      source3: orders.slice(currentIndex).filter((o) => new Date(o.time) <= sixSecondsLater),
    }
  }

  /**
   * 计算资金标记（点火/砸盘）
   */
  private calculateFundMarker(order: BigOrderItem, source2: BigOrderItem[]) {
    if (source2.length === 0) return

    // 过去50秒平均金额（万）
    const totalAmount = source2.reduce((sum, o) => sum + o.amount, 0)
    const avgAmount = totalAmount / source2.length / 10000

    // 当前金额（万）
    const currentAmountWan = order.amount / 10000

    // 检查平均金额是否为0或无效
    if (avgAmount <= 0) return

    // 点火：主动买且金额 >=300万 且 金额/平均 > 2.0
    const isIgnite =
      order.type === 2 &&
      currentAmountWan >= MARKER_THRESHOLDS.IGNITE.MIN_AMOUNT &&
      currentAmountWan / avgAmount > MARKER_THRESHOLDS.IGNITE.RATIO

    // 砸盘：主动卖且金额 >=300万 且 金额/平均 > 2.0
    const isSmash =
      order.type === 4 &&
      currentAmountWan >= MARKER_THRESHOLDS.SMASH.MIN_AMOUNT &&
      currentAmountWan / avgAmount > MARKER_THRESHOLDS.SMASH.RATIO

    // 砸盘优先
    if (isSmash) {
      order.fundMarker = '砸盘'
    } else if (isIgnite) {
      order.fundMarker = '点火'
    }
  }

  /**
   * 计算买盘标记（买活跃/承接好）
   */
  private calculateBuyMarker(
    order: BigOrderItem,
    source: BigOrderItem[],
    source3: BigOrderItem[],
    index: number,
    prevBuyAvg: number,
    prevSellAvg: number,
  ) {
    if (source3.length === 0) return

    // 计算未来6秒的平均值
    const { buyAvg, sellAvg } = this.calculateAverages(source3)

    // 检查前6秒是否有点火
    const hasIgnite = source.some((o) => o.fundMarker === '点火')

    // 买活跃：index>0 && 当前买平均 >= 上一行买平均 && 平均 > 100万 && 前6秒有点火
    const isBuyActive =
      index > 0 &&
      buyAvg >= prevBuyAvg &&
      buyAvg > MARKER_THRESHOLDS.BUY_ACTIVE.MIN_AVG &&
      hasIgnite

    // 承接好：index>0 && 当前卖平均 > 上一行卖平均 && 平均 > 300万
    const isGoodSupport =
      index > 0 && sellAvg > prevSellAvg && sellAvg > MARKER_THRESHOLDS.GOOD_SUPPORT.MIN_AVG

    // 买活跃优先级高于承接好
    if (isBuyActive) {
      order.buyMarker = '买活跃'
    } else if (isGoodSupport) {
      order.buyMarker = '承接好'
    }
  }

  /**
   * 计算平均值
   */
  private calculateAverages(orders: BigOrderItem[]): { buyAvg: number; sellAvg: number } {
    if (orders.length === 0) {
      return { buyAvg: 0, sellAvg: 0 }
    }

    // 主动卖或被动买的平均金额（万）
    let sellTotal = 0
    let sellCount = 0
    // 主动买或被动卖的平均金额（万）
    let buyTotal = 0
    let buyCount = 0

    for (const o of orders) {
      if (o.type === 4 || o.type === 3) {
        sellTotal += o.amount / 10000
        sellCount++
      }
      if (o.type === 2 || o.type === 1) {
        buyTotal += o.amount / 10000
        buyCount++
      }
    }

    const sellAvg = sellCount > 0 ? sellTotal / sellCount : 0
    const buyAvg = buyCount > 0 ? buyTotal / buyCount : 0

    return { buyAvg, sellAvg }
  }

  /**
   * 检测密集大单
   */
  detectDenseOrders(
    orders: BigOrderItem[],
    windowMs: number = MARKER_THRESHOLDS.DENSE_WINDOW,
    threshold: number = MARKER_THRESHOLDS.DENSE_COUNT,
  ): Array<{
    startTime: Date
    endTime: Date
    orders: BigOrderItem[]
    count: number
    totalAmount: number
  }> {
    if (!orders || orders.length < threshold) {
      return []
    }

    const sorted = [...orders].sort(
      (a, b) => new Date(a.time).getTime() - new Date(b.time).getTime(),
    )

    const result: Array<{
      startTime: Date
      endTime: Date
      orders: BigOrderItem[]
      count: number
      totalAmount: number
    }> = []

    let left = 0
    for (let right = 0; right < sorted.length; right++) {
      const currentTime = new Date(sorted[right].time).getTime()
      let startTime = new Date(sorted[left].time).getTime()

      // 如果窗口超出时间范围，移动左指针
      while (currentTime - startTime > windowMs && left < right) {
        left++
        startTime = new Date(sorted[left].time).getTime()
      }

      const windowOrders = sorted.slice(left, right + 1)
      if (windowOrders.length >= threshold) {
        const totalAmount = windowOrders.reduce((sum, o) => sum + o.amount, 0)

        // 检查是否已经存在重叠的窗口
        const lastResult = result[result.length - 1]
        if (!lastResult || new Date(lastResult.endTime).getTime() < startTime) {
          result.push({
            startTime: new Date(startTime),
            endTime: new Date(currentTime),
            orders: windowOrders,
            count: windowOrders.length,
            totalAmount,
          })
        }
      }
    }

    if (result.length > 0) {
      debugLog(`[BigOrderMarker] 检测到 ${result.length} 个密集大单窗口`)
    }

    return result
  }
}
