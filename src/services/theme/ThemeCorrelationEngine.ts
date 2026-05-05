import type { ThemeCorrelationDetail, StockCorrelation } from '@/services/ThemeCorrelationAnalyzer'
import type { MergedStock } from '@/types'
import { toFiniteNumber } from './utils'

type CorrelationInput = {
  themeId: string
  themeName: string
  stocks: Array<Partial<MergedStock> & { code: string; name?: string }>
  timestamp?: number
}

function stockScore(stock: Partial<MergedStock> & { code: string }): number {
  const change = Math.max(0, toFiniteNumber(stock.change))
  const volumeRatio = Math.max(0, toFiniteNumber(stock.volumeRatio))
  const leadBonus = String((stock as any).leadStatus || '').includes('龙') ? 25 : 0
  const limitBonus = change >= 9.5 ? 20 : 0
  return change * 4 + Math.min(20, volumeRatio * 4) + leadBonus + limitBonus
}

function directionConsistency(stock: Partial<MergedStock>, stocks: Partial<MergedStock>[]): number {
  const direction = Math.sign(toFiniteNumber(stock.change))
  if (direction === 0) return 0
  const comparable = stocks.filter((item) => Math.sign(toFiniteNumber(item.change)) !== 0)
  if (comparable.length === 0) return 0
  return comparable.filter((item) => Math.sign(toFiniteNumber(item.change)) === direction).length /
    comparable.length
}

export function analyzeThemeCorrelationInput(input: CorrelationInput): ThemeCorrelationDetail {
  const stocks = input.stocks.filter((stock) => stock.code)
  if (stocks.length === 0) {
    return {
      themeId: input.themeId,
      themeName: input.themeName,
      overallCorrelation: 0,
      stocks: new Map(),
      coreStocks: [],
      followerStocks: [],
      independentStocks: [],
      lastUpdate: input.timestamp || Date.now(),
      stats: {
        totalStocks: 0,
        avgChange: 0,
        totalZtCount: 0,
        avgVolumeRatio: 0,
        totalMainInflow: 0,
      },
    }
  }

  const sorted = [...stocks].sort((a, b) => stockScore(b) - stockScore(a))
  const leader = sorted[0]
  const stockCorrelations = new Map<string, StockCorrelation>()
  const coreStocks: string[] = []
  const followerStocks: string[] = []
  const independentStocks: string[] = []

  stocks.forEach((stock) => {
    const consistency = directionConsistency(stock, stocks)
    const score = stockScore(stock)
    const leaderCode = leader?.code
    const role =
      stock.code === leaderCode && score > 0 ? 'leader' : consistency >= 0.6 ? 'follower' : 'independent'
    const correlation: StockCorrelation = {
      code: stock.code,
      name: stock.name || '',
      change: toFiniteNumber(stock.change),
      volumeRatio: toFiniteNumber(stock.volumeRatio),
      mainNetInflow: toFiniteNumber((stock as any).mainNetInflow),
      avgCorrelation: consistency,
      leaderCorrelation: stock.code === leaderCode ? 1 : consistency,
      directionConsistency: consistency,
      changeDiff: Math.abs(toFiniteNumber(stock.change) - toFiniteNumber(leader?.change)),
      role,
    }
    stockCorrelations.set(stock.code, correlation)
    if (role === 'leader') coreStocks.push(stock.code)
    else if (role === 'follower') followerStocks.push(stock.code)
    else independentStocks.push(stock.code)
  })

  const avgChange = stocks.reduce((sum, stock) => sum + toFiniteNumber(stock.change), 0) / stocks.length
  const avgVolumeRatio =
    stocks.reduce((sum, stock) => sum + toFiniteNumber(stock.volumeRatio), 0) / stocks.length
  const totalMainInflow = stocks.reduce(
    (sum, stock) => sum + toFiniteNumber((stock as any).mainNetInflow),
    0,
  )
  const overallCorrelation =
    Array.from(stockCorrelations.values()).reduce(
      (sum, item) => sum + item.directionConsistency,
      0,
    ) / stockCorrelations.size

  return {
    themeId: input.themeId,
    themeName: input.themeName,
    overallCorrelation,
    stocks: stockCorrelations,
    coreStocks,
    followerStocks,
    independentStocks,
    lastUpdate: input.timestamp || Date.now(),
    leader:
      leader && stockScore(leader) > 0
        ? {
            code: leader.code,
            name: leader.name || '',
            score: stockScore(leader),
            confidence: sorted[1] ? Math.round((stockScore(leader) / (stockScore(leader) + stockScore(sorted[1]))) * 100) : 100,
            change: toFiniteNumber(leader.change),
            lianban: String((leader as any).lianban || ''),
            fengdan: toFiniteNumber((leader as any).fengdan),
            price: toFiniteNumber((leader as any).price),
            volumeRatio: toFiniteNumber(leader.volumeRatio),
            popularity: toFiniteNumber((leader as any).popularity),
            popularityChange: toFiniteNumber((leader as any).popularityChange),
            mainBuy: toFiniteNumber((leader as any).mainBuy),
            mainSell: toFiniteNumber((leader as any).mainSell),
            maxFengdan: toFiniteNumber((leader as any).maxFengdan),
            circulatingMarketCap: toFiniteNumber((leader as any).cirMV),
            largeOrder300w: toFiniteNumber((leader as any).bigMoney300),
          }
        : undefined,
    stats: {
      totalStocks: stocks.length,
      avgChange,
      totalZtCount: stocks.filter((stock) => toFiniteNumber(stock.change) >= 9.5).length,
      avgVolumeRatio,
      totalMainInflow,
    },
  }
}
