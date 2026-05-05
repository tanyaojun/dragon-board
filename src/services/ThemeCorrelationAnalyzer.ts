// src/services/ThemeCorrelationAnalyzer.ts
import { dataLayer } from './DataLayer'
import { analyzeThemeCorrelationInput } from './theme/ThemeCorrelationEngine'
import { themeFacade } from './theme/ThemeFacade'

export interface StockCorrelation {
  code: string
  name: string
  change: number
  volumeRatio: number
  mainNetInflow: number
  avgCorrelation: number
  leaderCorrelation: number
  directionConsistency: number
  changeDiff: number
  role: 'leader' | 'follower' | 'independent'
}

export interface ThemeCorrelationDetail {
  themeId: string
  themeName: string
  overallCorrelation: number
  stocks: Map<string, StockCorrelation>
  coreStocks: string[]
  followerStocks: string[]
  independentStocks: string[]
  lastUpdate: number
  leader?: {
    code: string
    name: string
    score: number
    confidence: number
    change: number
    lianban: string
    fengdan: number
    price: number
    volumeRatio: number
    popularity: number
    popularityChange: number
    mainBuy: number
    mainSell: number
    maxFengdan: number
    circulatingMarketCap: number
    largeOrder300w: number
    firstZtTime?: string
    turnoverRate?: number
    leadStatus?: string
    leadTimes?: number
    institutionBuy?: number
  }
  stats?: {
    totalStocks: number
    avgChange: number
    totalZtCount: number
    avgVolumeRatio: number
    totalMainInflow: number
  }
}

export class ThemeCorrelationAnalyzer {
  private static instance: ThemeCorrelationAnalyzer

  private constructor() {}

  static getInstance(): ThemeCorrelationAnalyzer {
    if (!ThemeCorrelationAnalyzer.instance) {
      ThemeCorrelationAnalyzer.instance = new ThemeCorrelationAnalyzer()
    }
    return ThemeCorrelationAnalyzer.instance
  }

  /**
   * 分析指定题材的联动性（供 rotationService 调用）
   * 只分析主线题材，不预加载全部
   */
  async analyzeThemeCorrelation(
    themeCode: string,
    themeName: string,
    options?: { force?: boolean },
  ): Promise<ThemeCorrelationDetail> {
    // 检查缓存（5分钟有效）
    const cached = dataLayer.getThemeCorrelation(themeCode)
    if (cached && Date.now() - cached.lastUpdate < 5 * 60 * 1000 && !options?.force) {
      return cached
    }

    // 获取该板块的个股
    const stockMap = themeFacade.getThemeStockMap()
    const rawStocks = Object.values(stockMap).filter((stock: any) =>
      stock.blocks?.includes(themeName),
    ) as any[]

    if (rawStocks.length < 2) {
      return this.getEmptyCorrelation(themeCode, themeName)
    }

    // ✅ 增强 stocks 数据，补充 price 字段
    const stocks = rawStocks.map((stock: any) => {
      const fullStock = dataLayer.getStock(stock.code)
      return {
        ...stock,
        price: fullStock?.price || 0,
      }
    })

    const typedResult = analyzeThemeCorrelationInput({
      themeId: themeCode,
      themeName,
      stocks,
    })
    dataLayer.updateThemeCorrelation(themeCode, typedResult)
    return typedResult
  }

  /**
   * 识别龙头（带得分和置信度）
   */
  private identifyLeaderWithConfidence(stocks: any[]): {
    leader: any | null
    leaderScore: number
    confidence: number
  } {
    if (stocks.length === 0) return { leader: null, leaderScore: 0, confidence: 0 }

    const scored = stocks.map((stock) => ({
      stock,
      score: this.calculateStockScore(stock),
    }))

    scored.sort((a, b) => b.score - a.score)

    const leader = scored[0]?.stock || null
    const leaderScore = scored[0]?.score || 0
    const secondScore = scored[1]?.score || 0

    // 置信度 = 第一名得分 / (第一名得分 + 第二名得分) * 100
    const confidence =
      leaderScore + secondScore > 0
        ? Math.round((leaderScore / (leaderScore + secondScore)) * 100)
        : 100

    return { leader, leaderScore, confidence }
  }

  /**
   * 计算单只股票的龙头得分
   */
  private calculateStockScore(stock: any): number {
    let score = 0
    const change = Math.abs(stock.change || 0)
    const code = String(stock.code || '')

    const isChiNext = code.startsWith('300') || code.startsWith('301') || code.startsWith('302')
    const isStar = code.startsWith('688')
    const isBeiJiao = code.startsWith('8') || code.startsWith('9')
    const isMainBoard = !isChiNext && !isStar && !isBeiJiao

    // 1. 涨幅得分
    let changeScore = 0
    if (isBeiJiao) changeScore = Math.min(change / 3, 10)
    else if (isChiNext || isStar) changeScore = Math.min(change / 2, 10)
    else changeScore = Math.min(change, 10)
    score += changeScore

    // 2. 封单额（考虑涨停幅度）
    if (stock.fengdan > 0) {
      const fengdanYi = stock.fengdan / 10000
      let baseScore = 0
      if (fengdanYi >= 5) baseScore = 20
      else if (fengdanYi >= 2) baseScore = 15
      else if (fengdanYi >= 1) baseScore = 10
      else if (fengdanYi >= 0.5) baseScore = 5
      else baseScore = 2
      if (isChiNext || isStar) baseScore = Math.min(baseScore * 1.2, 20)
      score += baseScore
    }

    // 3. 量比（根据板块调整阈值）
    const volumeRatio = stock.volumeRatio || 0
    const ratioLow = isChiNext || isStar ? 1.5 : 1.2
    const ratioHigh = isChiNext || isStar ? 3.5 : 2.5

    if (volumeRatio >= ratioLow && volumeRatio <= ratioHigh) score += 10
    else if (volumeRatio > ratioHigh && volumeRatio <= ratioHigh + 2) score += 6
    else if (volumeRatio > ratioHigh + 2 && volumeRatio <= ratioHigh + 4) score += 2
    else if (volumeRatio > ratioHigh + 4) score -= 5
    else if (volumeRatio >= 0.8 && volumeRatio < ratioLow) score += 3

    // 4. 300W大单（最高10分）- 占成交额比例
    if (stock.bigMoney300 > 0 && stock.turnover && stock.turnover > 0) {
      const bigMoneyWan = stock.bigMoney300 / 10000
      const turnoverWan = stock.turnover / 10000
      const ratio = (bigMoneyWan / turnoverWan) * 100

      if (ratio >= 30) score += 10
      else if (ratio >= 20) score += 8
      else if (ratio >= 10) score += 6
      else if (ratio >= 5) score += 4
      else if (ratio >= 2) score += 2
      else score += 1
    }

    // 5. 主力净额（调整区间）
    if (stock.mainNetInflow > 0) {
      const netInflowYi = Math.abs(stock.mainNetInflow) / 10000
      if (netInflowYi >= 1 && netInflowYi <= 3) score += 20
      else if (netInflowYi >= 0.5 && netInflowYi < 1) score += 18
      else if (netInflowYi >= 3 && netInflowYi <= 6) score += 15
      else if (netInflowYi > 0 && netInflowYi < 0.5) score += 12
      else if (netInflowYi > 6) score += 8
    } else {
      score -= 10
    }

    // 6. 人气热度变化
    if (stock.popularityChange && stock.popularityChange > 0) {
      score += Math.min(stock.popularityChange / 100, 10)
    }

    // 7. 领涨状态
    if (stock.leadStatus?.includes('龙')) {
      const match = stock.leadStatus.match(/龙(\d+)/)
      if (match) {
        const rank = parseInt(match[1])
        if (rank === 1) score += 15
        else if (rank === 2) score += 12
        else if (rank === 3) score += 9
        else score += 6
      } else {
        score += 8
      }
    }

    // 8. 连板位置
    const days = this.getLianbanDays(stock.lianban)
    if (days === 2) score += 5
    else if (days === 1) score += 3
    else if (days === 3) score += 2

    // 9. 涨停奖励
    if (change > 9.5) {
      if (isBeiJiao && change > 29.5) score += 5
      else if ((isChiNext || isStar) && change > 19.5) score += 4
      else if (isMainBoard && change > 9.5) score += 3
    }

    // 10. 主力买入占比（主动性）
    if (stock.mainBuy && stock.mainSell && stock.turnover) {
      const mainBuyRatio = (stock.mainBuy / (stock.turnover / 10000)) * 100
      const mainSellRatio = (stock.mainSell / (stock.turnover / 10000)) * 100
      const netActive = mainBuyRatio - mainSellRatio
      if (netActive >= 20) score += 5
      else if (netActive >= 10) score += 3
      else if (netActive >= 5) score += 1
    }

    // 11. 封单稳定性
    if (stock.maxFengdan && stock.fengdan && stock.maxFengdan > 0) {
      const ratio = stock.maxFengdan / stock.fengdan
      if (ratio <= 2) score += 5
      else if (ratio <= 3) score += 3
      else if (ratio <= 5) score += 1
    }

    return Math.min(100, Math.max(0, score))
  }

  /**
   * 计算板块统计
   */
  private calculateThemeStats(stocks: any[]): ThemeCorrelationDetail['stats'] {
    const validStocks = stocks.filter((s) => s.change !== undefined)
    if (validStocks.length === 0) return undefined

    const avgChange = validStocks.reduce((sum, s) => sum + (s.change || 0), 0) / validStocks.length
    const totalZtCount = validStocks.filter((s) => (s.change || 0) > 9.5).length
    const avgVolumeRatio =
      validStocks.reduce((sum, s) => sum + (s.volumeRatio || 0), 0) / validStocks.length
    const totalMainInflow = validStocks.reduce((sum, s) => sum + (s.mainNetInflow || 0), 0)

    return {
      totalStocks: validStocks.length,
      avgChange: Math.round(avgChange * 100) / 100,
      totalZtCount,
      avgVolumeRatio: Math.round(avgVolumeRatio * 100) / 100,
      totalMainInflow,
    }
  }

  /**
   * 从文本中提取连板天数
   */
  private getLianbanDays(lianban: string): number {
    if (!lianban) return 0
    if (lianban.includes('首板')) return 1
    const match = lianban.match(/(\d+)(?:连)?板/)
    return match ? parseInt(match[1]) : 0
  }

  /**
   * 计算两只股票的相关性
   * 基于涨幅的相似度和方向一致性
   */
  private calculatePairCorrelation(stockA: any, stockB: any): number {
    const changeA = stockA.change || 0
    const changeB = stockB.change || 0

    // 两者都无涨跌，相关性低
    if (changeA === 0 && changeB === 0) return 0.3

    // 方向相同
    if (changeA * changeB > 0) {
      // 计算涨幅相似度（差值越小越相似）
      const diff = Math.abs(changeA - changeB)
      const maxChange = Math.max(Math.abs(changeA), Math.abs(changeB))

      if (maxChange === 0) return 0.6

      // 相似度：1 - (差值/最大涨幅)
      const similarity = 1 - Math.min(diff / maxChange, 1)

      // 基础分0.5 + 相似度加成0.5，最高1.0
      return 0.5 + similarity * 0.5
    }

    // 方向相反
    if (changeA * changeB < 0) {
      // 反向相关性低，但根据涨幅大小略有浮动
      const absA = Math.abs(changeA)
      const absB = Math.abs(changeB)
      const maxAbs = Math.max(absA, absB)

      // 涨幅越大，负相关越明显，返回0-0.3之间
      return 0.3 * (1 - maxAbs / 20) // 涨幅20%时接近0
    }

    // 一方为0
    return 0.2
  }
  /**
   * 计算个股与板块内其他股票的平均相关性
   */
  private calculateAvgCorrelation(stock: any, allStocks: any[]): number {
    let total = 0
    let count = 0

    allStocks.forEach((other) => {
      if (other.code === stock.code) return
      total += this.calculatePairCorrelation(stock, other)
      count++
    })

    return count > 0 ? total / count : 0
  }

  /**
   * 计算涨跌方向一致性
   * 返回该股票与板块内其他股票方向相同的比例
   */
  private calculateDirectionConsistency(stock: any, allStocks: any[]): number {
    const stockChange = stock.change || 0
    const stockDirection = Math.sign(stockChange)

    // 如果股票本身没涨跌，返回0.5（中性）
    if (stockDirection === 0) return 0.5

    let sameCount = 0
    let totalCount = 0

    allStocks.forEach((other) => {
      if (other.code === stock.code) return

      const otherChange = other.change || 0
      const otherDirection = Math.sign(otherChange)

      // 只统计有涨跌的股票
      if (otherDirection !== 0) {
        if (otherDirection === stockDirection) sameCount++
        totalCount++
      }
    })

    if (totalCount === 0) return 0.5

    return sameCount / totalCount
  }

  /**
   * 计算涨幅差异
   * 返回个股涨幅与板块平均涨幅的差值绝对值（百分比）
   */
  private calculateChangeDiff(stock: any, allStocks: any[]): number {
    const validChanges = allStocks.map((s) => s.change || 0).filter((v) => v !== 0)

    if (validChanges.length === 0) return 0

    const avgChange = validChanges.reduce((sum, v) => sum + v, 0) / validChanges.length
    const stockChange = stock.change || 0

    // 直接返回绝对值，单位是%
    return Math.abs(stockChange - avgChange)
  }

  /**
   * 计算整体联动性
   */
  private calculateOverallCorrelation(correlations: StockCorrelation[]): number {
    if (correlations.length === 0) return 0

    // 计算平均相关性
    const avg = correlations.reduce((sum, c) => sum + c.avgCorrelation, 0) / correlations.length

    // 检查是否有强龙头
    const hasStrongLeader = correlations.some((c) => c.role === 'leader' && c.avgCorrelation > 0.6)

    let result = avg

    // 有强龙头且平均相关性不低时，给予加成
    if (hasStrongLeader && avg > 0.3) {
      result = Math.min(0.95, avg * 1.2) // 最高0.95，避免显示100%
    }

    // 保留两位小数
    return Math.round(result * 100) / 100
  }

  private getEmptyCorrelation(themeId: string, themeName: string): ThemeCorrelationDetail {
    return {
      themeId,
      themeName,
      overallCorrelation: 0,
      stocks: new Map(),
      coreStocks: [],
      followerStocks: [],
      independentStocks: [],
      lastUpdate: Date.now(),
    }
  }
}

export const themeCorrelationAnalyzer = ThemeCorrelationAnalyzer.getInstance()
