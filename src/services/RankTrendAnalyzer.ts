// src/services/RankTrendAnalyzer.ts
import { EventManager } from '../utils/eventManager'

// ========== 配置常量 ==========
const RANK_ANALYZER_CONFIG = {
  // 多周期参数（快照数量）
  PERIODS: {
    SHORT: 1, // 30分钟
    MID: 5, // 2.5小时
    LONG: 10, // 5小时（约半天）
    EXTRA: 20, // 10小时（约1天）
  },

  // 5周期动量配置（斐波那契数列）
  MOMENTUM_PERIODS: {
    periods: [3, 5, 8, 13, 21] as number[],
    weights: [0.15, 0.2, 0.25, 0.25, 0.15] as number[],
    thresholds: {
      buy: [5, 8, 12, 15, 20] as number[],
      sell: [-5, -8, -12, -15, -20] as number[],
    },
  },

  // MACD参数（针对排名数据优化，更敏感）
  MACD: {
    FAST: 6, // 快线周期
    SLOW: 12, // 慢线周期
    SIGNAL: 5, // 信号线周期
  },
}

export interface RankTrendResult {
  code: string
  currentRank: number
  change: number
  rawChange: number
  ma5: number
  ma10: number
  maTrend: 'up' | 'down' | 'steady'
  macd: number
  macdSignal: number
  macdHistogram: number
  macdCross: 'golden' | 'death' | 'none'
  signal: 'buy' | 'sell' | 'hold'
  confidence: number

  // 3个排名趋势信号（方向一致性、动量加速度、零线交叉）
  directionSignal: 'buy' | 'sell' | 'hold'
  directionConfidence: number
  accelerationSignal: 'buy' | 'sell' | 'hold'
  accelerationConfidence: number
  crossSignal: 'buy' | 'sell' | 'hold'
  crossConfidence: number

  // MACD确认信号
  finalSignal: 'buy' | 'sell' | 'hold'
  finalConfidence: number
  updateTime: number
}

// ========== 类型定义 ==========

interface RankSignalResult {
  signal: 'buy' | 'sell' | 'hold'
  confidence: number
  score: number
  factors: string[]
  breakdown?: {
    rankTrendScore: number
    multiPeriodConsistency: number
    acceleration: number
    factors: string[]
  }
}

// ========== 主类 ==========
class RankTrendAnalyzer {
  private static instance: RankTrendAnalyzer
  private isRunning = false
  private initPromise: Promise<void> | null = null

  private rankHistoryCache: Map<
    string,
    { ranks: number[]; percentiles: number[]; totalCounts: number[] }
  > = new Map()

  private constructor() {
    this.initPromise = this.start()
  }

  static getInstance(): RankTrendAnalyzer {
    if (!RankTrendAnalyzer.instance) {
      RankTrendAnalyzer.instance = new RankTrendAnalyzer()
    }
    return RankTrendAnalyzer.instance
  }

  async start() {
    if (this.isRunning) return
    this.isRunning = true

    // 动态获取 dataLayer
    const dataLayer = await this.getDataLayer()

    let retries = 0
    while (dataLayer.getStocks().length === 0 && retries < 10) {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      retries++
    }

    // 监听数据更新事件，自动清除缓存
    EventManager.on('data:stocks-updated', () => {
      console.log('[RankTrendAnalyzer] 数据版本变化，清除缓存')
      this.invalidateCache()
    })

    // 监听快照更新
    EventManager.on('snapshots:updated', () => {
      console.log('[RankTrendAnalyzer] 快照更新，清除缓存')
      this.invalidateCache()
    })
  }

  private invalidateCache() {
    this.rankHistoryCache.clear()
  }

  /**
   * 计算指定周期的动量
   * @param percentiles 百分位数组（按时间正序）
   * @param period 回顾周期数
   */
  private calculatePeriodMomentum(percentiles: number[], period: number): number {
    if (percentiles.length < period + 1) return 0

    const current = percentiles[percentiles.length - 1]
    const past = percentiles[percentiles.length - 1 - period]

    return current - past
  }

  /**
   * 获取指定类型的快照（通用接口）
   */
  public async getSnapshotsByType(
    type: 'quarter_hour' | 'half_hour' | 'hourly' | 'daily',
    options?: {
      limit?: number
      minRequired?: number
      fromDate?: Date
      toDate?: Date
    },
  ): Promise<Array<{ date: string; timestamp: number; snapshot: any }>> {
    const dataLayer = await this.getDataLayer()
    const allDates = await dataLayer.getSnapshotDates()

    if (allDates.length === 0) return []

    // 只取最近 N 个日期，避免遍历全部
    const maxDates = options?.limit ? Math.min(allDates.length, options.limit * 2) : 100
    const recentDates = allDates.slice(-maxDates)

    const snapshots: Array<{ date: string; timestamp: number; snapshot: any }> = []

    // 分批加载，每批10个
    const batchSize = 10
    for (let i = 0; i < recentDates.length; i += batchSize) {
      const batch = recentDates.slice(i, i + batchSize)
      const batchResults = await Promise.all(
        batch.map(async (date) => {
          try {
            const snapshot = await dataLayer.getSnapshotFromDB(date)
            if (snapshot?.type === type && snapshot?.timestamp) {
              return { date, timestamp: snapshot.timestamp, snapshot }
            }
          } catch (e) {
            // 忽略单个快照错误
          }
          return null
        }),
      )
      snapshots.push(...batchResults.filter((r): r is NonNullable<typeof r> => r !== null))

      // 如果已经收集到足够的数据，提前退出
      if (options?.minRequired && snapshots.length >= options.minRequired) {
        break
      }
    }

    // 按时间排序
    snapshots.sort((a, b) => a.timestamp - b.timestamp)

    // 检查数量
    if (options?.minRequired && snapshots.length < options.minRequired) {
      return []
    }

    // 取最近 limit 个
    if (options?.limit && options.limit > 0 && snapshots.length > options.limit) {
      return snapshots.slice(-options.limit)
    }

    return snapshots
  }

  // ========== 核心方法：获取排名趋势 ==========
  async getRankTrends(rankMap: Map<string, number>): Promise<Map<string, RankTrendResult>> {
    const results = new Map<string, RankTrendResult>()
    const dataLayer = await this.getDataLayer()
    const allDates = await dataLayer.getSnapshotDates()

    if (allDates.length === 0) return results

    const recentSnapshots = await this.loadRequiredSnapshots()
    if (recentSnapshots.length === 0) {
      console.log('[RankTrendAnalyzer] 快照不足，跳过计算')
      return results
    }

    // 预计算所有股票的百分位历史
    const allPercentiles = this.buildPercentilesHistory(recentSnapshots)

    // 预计算所有股票的动量数据
    const allMomentum = this.buildMomentumData(allPercentiles)

    // 获取前一交易日的排名快照（用于显示变化）
    const { prevRankMap, prevTotalCount } = await this.getPreviousDayRankSnapshot(recentSnapshots)
    const currentTotalCount = rankMap.size

    // 建立快照映射
    const snapshotsMap = this.buildSnapshotsMap(recentSnapshots)
    const weekdays = recentSnapshots.map((item) => item.date)

    // 并行计算所有股票
    const computePromises: Promise<[string, RankTrendResult]>[] = []
    for (const [code, currentRank] of rankMap.entries()) {
      computePromises.push(
        this.computeStockRankTrend(
          code,
          currentRank,
          currentTotalCount,
          prevRankMap,
          prevTotalCount,
          weekdays,
          snapshotsMap,
          allMomentum,
        ),
      )
    }

    const computedResults = await Promise.all(computePromises)
    for (const [code, result] of computedResults) {
      if (result) results.set(code, result)
    }

    await this.batchUpdateSignals(results)
    return results
  }

  /**
   * 加载所需的快照
   */
  private async loadRequiredSnapshots(): Promise<
    Array<{ date: string; timestamp: number; snapshot: any }>
  > {
    const requiredSnapshots = Math.max(
      RANK_ANALYZER_CONFIG.MACD.SLOW,
      RANK_ANALYZER_CONFIG.PERIODS.LONG,
      30,
    )

    return await this.getSnapshotsByType('quarter_hour', {
      limit: 50,
      minRequired: requiredSnapshots,
    })
  }

  /**
   * 构建所有股票的百分位历史
   */
  private buildPercentilesHistory(
    snapshots: Array<{ date: string; timestamp: number; snapshot: any }>,
  ): Map<string, number[]> {
    const allPercentiles = new Map<string, number[]>()

    for (const item of snapshots) {
      const hotlist = item.snapshot.hotlist
      for (const stock of hotlist) {
        const code = stock.code
        if (!allPercentiles.has(code)) {
          allPercentiles.set(code, [])
        }
        const rank = hotlist.findIndex((s: any) => s.code === code) + 1
        const total = hotlist.length
        const percentile = ((total - rank + 1) / total) * 100
        allPercentiles.get(code)!.push(percentile)
      }
    }

    return allPercentiles
  }

  /**
   * 构建所有股票的动量数据
   */
  private buildMomentumData(allPercentiles: Map<string, number[]>): Map<
    string,
    {
      values: number[]
      prevValues: number[]
      score: number
      signal: 'buy' | 'sell' | 'hold'
      confidence: number
    } | null
  > {
    const { periods, weights, thresholds } = RANK_ANALYZER_CONFIG.MOMENTUM_PERIODS
    const maxPeriod = Math.max(...periods)
    const minRequiredData = maxPeriod + 1

    const allMomentum = new Map()

    for (const [code, percentiles] of allPercentiles.entries()) {
      if (percentiles.length < minRequiredData) {
        allMomentum.set(code, null)
        continue
      }

      // 计算各周期动量值
      const values: number[] = []
      const prevValues: number[] = []

      for (let i = 0; i < periods.length; i++) {
        const period = periods[i]
        values.push(this.calculatePeriodMomentum(percentiles, period))
        prevValues.push(this.calculatePrevPeriodMomentum(percentiles, period))
      }

      // 计算加权总分
      let totalScore = 0
      for (let i = 0; i < periods.length; i++) {
        const value = values[i]
        const weight = weights[i]
        const buyThreshold = thresholds.buy[i]
        const sellThreshold = thresholds.sell[i]

        let periodScore = 0
        if (value > buyThreshold) periodScore = 100 * weight
        else if (value > buyThreshold * 0.6) periodScore = 70 * weight
        else if (value > 0) periodScore = 40 * weight
        else if (value < sellThreshold) periodScore = -100 * weight
        else if (value < sellThreshold * 0.6) periodScore = -70 * weight
        else if (value < 0) periodScore = -40 * weight
        totalScore += periodScore
      }
      totalScore = Math.max(-100, Math.min(100, totalScore))

      // 信号转换
      let signal: 'buy' | 'sell' | 'hold' = 'hold'
      let confidence = 50
      if (totalScore >= 50) {
        signal = 'buy'
        confidence = 70 + Math.min(25, (totalScore - 50) / 2)
      } else if (totalScore <= -50) {
        signal = 'sell'
        confidence = 70 + Math.min(25, (Math.abs(totalScore) - 50) / 2)
      }

      allMomentum.set(code, { values, prevValues, score: totalScore, signal, confidence })
    }

    return allMomentum
  }

  /**
   * 构建快照映射（date -> snapshot）
   */
  private buildSnapshotsMap(
    snapshots: Array<{ date: string; timestamp: number; snapshot: any }>,
  ): Map<string, any> {
    const map = new Map<string, any>()
    for (const item of snapshots) {
      map.set(item.date, item.snapshot)
    }
    return map
  }

  /**
   * 获取前一交易日的排名快照（用于显示排名变化）
   */
  private async getPreviousDayRankSnapshot(
    recentSnapshots: Array<{ date: string; timestamp: number; snapshot: any }>,
  ): Promise<{ prevRankMap: Map<string, number>; prevTotalCount: number }> {
    // 按日期分组
    const snapshotsByDate = new Map<string, typeof recentSnapshots>()
    for (const snapshot of recentSnapshots) {
      const match = snapshot.date.match(/(\d{4}-\d{2}-\d{2})/)
      if (!match) continue
      const date = match[1]
      if (!snapshotsByDate.has(date)) {
        snapshotsByDate.set(date, [])
      }
      snapshotsByDate.get(date)!.push(snapshot)
    }

    // 获取所有交易日的日期列表（按时间倒序）
    const tradingDates = Array.from(snapshotsByDate.keys()).sort().reverse()

    let prevSnapshot = null
    if (tradingDates.length >= 2) {
      const prevDate = tradingDates[1]
      const prevDaySnapshots = snapshotsByDate.get(prevDate) || []
      if (prevDaySnapshots.length > 0) {
        prevDaySnapshots.sort((a, b) => a.timestamp - b.timestamp)
        prevSnapshot = prevDaySnapshots[prevDaySnapshots.length - 1]
      }
    }

    //回退到前一个快照
    if (!prevSnapshot && recentSnapshots.length >= 2) {
      prevSnapshot = recentSnapshots[recentSnapshots.length - 2]
    }

    const prevTotalCount = prevSnapshot?.snapshot?.hotlist?.length || 200
    const prevRankMap = new Map<string, number>()

    if (prevSnapshot?.snapshot?.hotlist) {
      prevSnapshot.snapshot.hotlist.forEach((item: any, idx: number) =>
        prevRankMap.set(item.code, idx + 1),
      )
    }

    return { prevRankMap, prevTotalCount }
  }

  /**
   * 计算前一期指定周期的动量
   * @param percentiles 百分位数组（按时间正序）
   * @param period 回顾周期数
   */
  private calculatePrevPeriodMomentum(percentiles: number[], period: number): number {
    if (percentiles.length < period + 2) return 0

    const current = percentiles[percentiles.length - 2]
    const past = percentiles[percentiles.length - 2 - period]

    return current - past
  }

  // ========== 计算单只股票的排名趋势 ==========
  private async computeStockRankTrend(
    code: string,
    currentRank: number,
    currentTotalCount: number,
    prevRankMap: Map<string, number>,
    prevTotalCount: number,
    weekdays: string[],
    snapshots: Map<string, any>,
    allMomentum: Map<
      string,
      {
        values: number[]
        prevValues: number[]
        score: number
        signal: 'buy' | 'sell' | 'hold'
        confidence: number
      } | null
    >,
  ): Promise<[string, RankTrendResult]> {
    let rankHistoryData = this.rankHistoryCache.get(code)
    const dataLayer = await this.getDataLayer()

    if (!rankHistoryData) {
      const ranks: number[] = []
      const percentiles: number[] = []
      const totalCounts: number[] = []

      for (const date of weekdays) {
        const snapshot = snapshots.get(date)
        const item = snapshot?.hotlist?.find((i: any) => i.code === code)
        if (item?.rank && snapshot?.hotlist?.length) {
          ranks.push(item.rank)
          percentiles.push(this.calculatePercentileRank(item.rank, snapshot.hotlist.length))
          totalCounts.push(snapshot.hotlist.length)
        }
      }
      rankHistoryData = { ranks, percentiles, totalCounts }
      this.rankHistoryCache.set(code, rankHistoryData)
    }

    const { ranks, percentiles, totalCounts } = rankHistoryData

    if (ranks.length < RANK_ANALYZER_CONFIG.MACD.SLOW) {
      return [code, null as any]
    }

    const currentPercentile = this.calculatePercentileRank(currentRank, currentTotalCount)
    const prevRank = prevRankMap.get(code)
    const prevPercentile = prevRank
      ? this.calculatePercentileRank(prevRank, prevTotalCount)
      : currentPercentile
    const displayChange = prevRank ? currentPercentile - prevPercentile : 0

    // 计算技术指标
    const ma5 = this.calculateMA(percentiles, RANK_ANALYZER_CONFIG.PERIODS.MID)
    const ma10 = this.calculateMA(percentiles, RANK_ANALYZER_CONFIG.PERIODS.LONG)
    const maTrend: 'up' | 'down' | 'steady' = ma5 > ma10 ? 'up' : ma5 < ma10 ? 'down' : 'steady'

    const macdData = this.calculateMACD(percentiles)
    const stock = dataLayer.getStock(code)
    const stockChange = stock?.change || 0

    // ========== 获取3个排名趋势信号 ==========
    const momentumData = allMomentum.get(code) || null
    const rankSignals = this.calculateRankTrendSignal(percentiles, stockChange, momentumData)

    // ========== 投票统计 ==========
    let buyVotes = 0
    let sellVotes = 0

    if (rankSignals.directionSignal === 'buy') buyVotes++
    else if (rankSignals.directionSignal === 'sell') sellVotes++

    if (rankSignals.accelerationSignal === 'buy') buyVotes++
    else if (rankSignals.accelerationSignal === 'sell') sellVotes++

    if (rankSignals.crossSignal === 'buy') buyVotes++
    else if (rankSignals.crossSignal === 'sell') sellVotes++

    // ========== 初步综合信号 ==========
    let tempSignal: 'buy' | 'sell' | 'hold' = 'hold'
    let tempConfidence = 50

    if (buyVotes >= 2) {
      tempSignal = 'buy'
      tempConfidence = buyVotes === 3 ? 85 : 70
    } else if (sellVotes >= 2) {
      tempSignal = 'sell'
      tempConfidence = sellVotes === 3 ? 85 : 70
    }

    // ========== MACD 确认信号 ==========
    let finalSignal = tempSignal
    let finalConfidence = tempConfidence

    if (macdData.cross === 'golden') {
      if (tempSignal === 'buy') {
        finalConfidence = Math.min(95, finalConfidence + 10)
      } else if (tempSignal === 'sell') {
        finalSignal = 'hold'
        finalConfidence = 50
      } else if (tempSignal === 'hold') {
        finalSignal = 'buy'
        finalConfidence = 55
      }
    } else if (macdData.cross === 'death') {
      if (tempSignal === 'sell') {
        finalConfidence = Math.min(95, finalConfidence + 10)
      } else if (tempSignal === 'buy') {
        finalSignal = 'hold'
        finalConfidence = 50
      } else if (tempSignal === 'hold') {
        finalSignal = 'sell'
        finalConfidence = 55
      }
    }

    return [
      code,
      {
        code,
        currentRank,
        change: displayChange,
        rawChange: ranks[0] - ranks[ranks.length - 1],
        ma5,
        ma10,
        maTrend,
        macd: macdData.macd,
        macdSignal: macdData.signal,
        macdHistogram: macdData.histogram,
        macdCross: macdData.cross,
        signal: tempSignal,
        confidence: tempConfidence,
        directionSignal: rankSignals.directionSignal,
        directionConfidence: rankSignals.directionConfidence,
        accelerationSignal: rankSignals.accelerationSignal,
        accelerationConfidence: rankSignals.accelerationConfidence,
        crossSignal: rankSignals.crossSignal,
        crossConfidence: rankSignals.crossConfidence,
        finalSignal: finalSignal,
        finalConfidence: finalConfidence,
        updateTime: Date.now(),
      },
    ]
  }

  // ========== 排名趋势信号（3个独立信号）==========
  private calculateRankTrendSignal(
    percentiles: number[],
    stockChange: number,
    momentumData: {
      values: number[]
      prevValues: number[]
      score: number
      signal: 'buy' | 'sell' | 'hold'
      confidence: number
    } | null,
  ): {
    directionSignal: 'buy' | 'sell' | 'hold'
    directionConfidence: number
    accelerationSignal: 'buy' | 'sell' | 'hold'
    accelerationConfidence: number
    crossSignal: 'buy' | 'sell' | 'hold'
    crossConfidence: number
    factors: string[]
  } {
    // 默认返回值
    const defaultResult = {
      directionSignal: 'hold' as const,
      directionConfidence: 50,
      accelerationSignal: 'hold' as const,
      accelerationConfidence: 50,
      crossSignal: 'hold' as const,
      crossConfidence: 50,
      factors: ['数据不足'],
    }

    if (!momentumData || momentumData.values.length < 5) {
      return defaultResult
    }

    const values = momentumData.values // [p3, p5, p8, p13, p21]
    const prevValues = momentumData.prevValues // [p3_prev, p5_prev, ...]
    const factors: string[] = []

    // ========== 信号1：方向一致性 ==========
    const positiveCount = values.filter((v) => v > 0).length
    const negativeCount = values.filter((v) => v < 0).length

    let directionSignal: 'buy' | 'sell' | 'hold' = 'hold'
    let directionConfidence = 50

    if (positiveCount >= 4) {
      directionSignal = 'buy'
      directionConfidence = 85
    } else if (positiveCount >= 3) {
      directionSignal = 'buy'
      directionConfidence = 70
    } else if (negativeCount >= 4) {
      directionSignal = 'sell'
      directionConfidence = 85
    } else if (negativeCount >= 3) {
      directionSignal = 'sell'
      directionConfidence = 70
    }
    factors.push(`方向:${positiveCount}正/${negativeCount}负 → ${directionSignal}`)

    // ========== 信号2：动量加速度 ==========
    const accelerations = []
    for (let i = 1; i < values.length; i++) {
      accelerations.push(values[i] - values[i - 1])
    }
    const accelPositive = accelerations.filter((a) => a > 0).length

    let accelerationSignal: 'buy' | 'sell' | 'hold' = 'hold'
    let accelerationConfidence = 50

    if (accelPositive >= 4) {
      accelerationSignal = 'buy'
      accelerationConfidence = 85
    } else if (accelPositive >= 3) {
      accelerationSignal = 'buy'
      accelerationConfidence = 70
    } else if (accelPositive <= 1) {
      accelerationSignal = 'sell'
      accelerationConfidence = 70
    } else if (accelPositive === 0) {
      accelerationSignal = 'sell'
      accelerationConfidence = 85
    }
    factors.push(`加速度:${accelPositive}/4正 → ${accelerationSignal}`)

    // ========== 信号3：零线交叉（需要前一期数据） ==========
    const p3 = values[0]
    const p5 = values[1]
    const p3Prev = prevValues?.[0] ?? 0
    const p5Prev = prevValues?.[1] ?? 0

    let crossSignal: 'buy' | 'sell' | 'hold' = 'hold'
    let crossConfidence = 50

    // 金叉：前一期 P3<=0 且 当前 P3>0，或者前一期 P5<=0 且 当前 P5>0
    const isGoldenCross = (p3Prev <= 0 && p3 > 0) || (p5Prev <= 0 && p5 > 0)
    // 死叉：前一期 P3>=0 且 当前 P3<0，或者前一期 P5>=0 且 当前 P5<0
    const isDeathCross = (p3Prev >= 0 && p3 < 0) || (p5Prev >= 0 && p5 < 0)

    if (isGoldenCross) {
      crossSignal = 'buy'
      crossConfidence = 85
    } else if (isDeathCross) {
      crossSignal = 'sell'
      crossConfidence = 85
    }
    factors.push(
      `零线:P3:${p3Prev.toFixed(1)}→${p3.toFixed(1)}, P5:${p5Prev.toFixed(1)}→${p5.toFixed(1)} → ${crossSignal}`,
    )

    return {
      directionSignal,
      directionConfidence,
      accelerationSignal,
      accelerationConfidence,
      crossSignal,
      crossConfidence,
      factors,
    }
  }

  // ========== 技术指标计算 ==========
  /**
   * 计算简单移动平均（MA）
   * @param data 数据数组
   * @param period 周期
   * @returns MA值
   */
  private calculateMA(data: number[], period: number): number {
    if (data.length === 0) return 0

    // 数据不足时，返回所有数据的平均值
    if (data.length < period) {
      return data.reduce((a, b) => a + b, 0) / data.length
    }

    // 数据足够时，返回最近 period 期的平均值
    const slice = data.slice(-period)
    return slice.reduce((a, b) => a + b, 0) / period
  }

  /**
   * 计算 MACD 指标（基于排名百分位）
   * 标准实现：
   * - DIF = EMA6 - EMA12
   * - DEA = EMA5(DIF)
   * - MACD柱 = 2 × (DIF - DEA)
   */
  private calculateMACD(data: number[]): {
    macd: number
    signal: number
    histogram: number
    cross: 'golden' | 'death' | 'none'
    confirmed: boolean // ✅ 新增：确认信号
  } {
    const { FAST, SLOW, SIGNAL } = RANK_ANALYZER_CONFIG.MACD

    // 数据不足，返回默认值
    if (data.length < SLOW) {
      return { macd: 0, signal: 0, histogram: 0, cross: 'none', confirmed: false }
    }

    // 1. 计算 DIF = EMA6 - EMA12
    const emaFast = this.calculateEMA(data, FAST)
    const emaSlow = this.calculateEMA(data, SLOW)
    const dif = emaFast - emaSlow

    // 2. 构建 DIF 历史序列（用于计算 DEA）
    const difHistory: number[] = []
    for (let i = SLOW; i <= data.length; i++) {
      const slice = data.slice(0, i)
      const eFast = this.calculateEMA(slice, FAST)
      const eSlow = this.calculateEMA(slice, SLOW)
      difHistory.push(eFast - eSlow)
    }

    // 3. 计算 DEA = EMA5(DIF)
    let dea = 0
    if (difHistory.length >= SIGNAL) {
      dea = this.calculateEMA(difHistory, SIGNAL)
    } else if (difHistory.length > 0) {
      dea = difHistory.reduce((a, b) => a + b, 0) / difHistory.length
    }

    // 4. MACD柱 = 2 × (DIF - DEA)
    const histogram = 2 * (dif - dea)

    // 5. 判断金叉/死叉
    let cross: 'golden' | 'death' | 'none' = 'none'
    let confirmed = false // ✅ 新增：确认标志

    if (difHistory.length >= 2) {
      const prevDif = difHistory[difHistory.length - 2]

      // 计算前值 DEA
      let prevDea = 0
      if (difHistory.length - 1 >= SIGNAL) {
        const prevDifHistory = difHistory.slice(0, -1)
        prevDea = this.calculateEMA(prevDifHistory, SIGNAL)
      } else if (difHistory.length - 1 > 0) {
        prevDea = difHistory.slice(0, -1).reduce((a, b) => a + b, 0) / (difHistory.length - 1)
      }

      // 金叉：前值 DIF <= 前值 DEA，当前 DIF > 当前 DEA
      if (prevDif <= prevDea && dif > dea) {
        cross = 'golden'

        // ✅ 金叉确认：检查后续是否有至少1期继续强势
        if (difHistory.length >= 3) {
          const afterDif = dif
          const afterDea = dea
          const prevPrevDif = difHistory[difHistory.length - 3]
          const prevPrevDea = this.calculateEMA(difHistory.slice(0, -2), SIGNAL)

          // 确认条件：金叉后 DIF > DEA 且 MACD柱 > 0 持续
          if (afterDif > afterDea && histogram > 0) {
            // 检查金叉前的趋势是否已经反转
            const trendReverse = prevPrevDif <= prevPrevDea
            confirmed = trendReverse && afterDif - afterDea > (prevDif - prevDea) * 1.2
          }
        }
      }
      // 死叉：前值 DIF >= 前值 DEA，当前 DIF < 当前 DEA
      else if (prevDif >= prevDea && dif < dea) {
        cross = 'death'

        // ✅ 死叉确认：检查后续是否有至少1期继续弱势
        if (difHistory.length >= 3) {
          const afterDif = dif
          const afterDea = dea
          const prevPrevDif = difHistory[difHistory.length - 3]
          const prevPrevDea = this.calculateEMA(difHistory.slice(0, -2), SIGNAL)

          // 确认条件：死叉后 DIF < DEA 且 MACD柱 < 0 持续
          if (afterDif < afterDea && histogram < 0) {
            const trendReverse = prevPrevDif >= prevPrevDea
            confirmed = trendReverse && afterDea - afterDif > (prevDea - prevDif) * 1.2
          }
        }
      }
    }

    return { macd: dif, signal: dea, histogram, cross, confirmed }
  }

  /**
   * 计算指数移动平均（EMA）
   * @param data 数据数组
   * @param period 周期
   * @returns EMA值
   */
  private calculateEMA(data: number[], period: number): number {
    if (data.length === 0) return 0

    const multiplier = 2 / (period + 1)

    // 如果数据量小于周期，返回简单平均
    if (data.length < period) {
      return data.reduce((a, b) => a + b, 0) / data.length
    }

    // 先用 SMA 作为初始值
    let ema = 0
    for (let i = 0; i < period; i++) {
      ema += data[i]
    }
    ema = ema / period

    // 递推计算 EMA
    for (let i = period; i < data.length; i++) {
      ema = (data[i] - ema) * multiplier + ema
    }

    return ema
  }

  private calculatePercentileRank(rank: number, totalCount: number): number {
    return ((totalCount - rank + 1) / totalCount) * 100
  }

  // ========== 综合信号计算 ==========

  private async getDataLayer() {
    const { dataLayer } = await import('./DataLayer')
    return dataLayer
  }

  // ========== 批量更新信号 ==========
  private async batchUpdateSignals(results: Map<string, RankTrendResult>): Promise<void> {
    // ✅ 动态导入，避免循环依赖
    const { dataLoader } = await import('./dataLoader')

    const signalUpdates: Array<any> = []
    for (const [code, result] of results) {
      if (!result) continue
      signalUpdates.push({
        code,
        rankChange: result.change,
        macd: result.macd,
        macdSignal: result.macdSignal,
        macdHistogram: result.macdHistogram,
        ma5: result.ma5,
        ma10: result.ma10,
        maTrend: result.maTrend,
        macdCross: result.macdCross,
        directionSignal: result.directionSignal,
        directionConfidence: result.directionConfidence,
        accelerationSignal: result.accelerationSignal,
        accelerationConfidence: result.accelerationConfidence,
        crossSignal: result.crossSignal,
        crossConfidence: result.crossConfidence,
        finalSignal: result.finalSignal,
        finalConfidence: result.finalConfidence,
      })
    }
    if (signalUpdates.length > 0) {
      dataLoader.updateStockSignals(signalUpdates)
    }
  }

  // ========== 生命周期 ==========
  stop() {
    this.isRunning = false
    this.invalidateCache()
  }
}

export const rankTrendAnalyzer = RankTrendAnalyzer.getInstance()

if (typeof window !== 'undefined') {
  ;(window as any).rankTrendAnalyzer = rankTrendAnalyzer
}
