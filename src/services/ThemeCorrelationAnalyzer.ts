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
