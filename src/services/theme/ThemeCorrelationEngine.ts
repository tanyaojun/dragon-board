import type { ThemeCorrelationDetail, StockCorrelation } from '@/services/ThemeCorrelationAnalyzer'
import type { MergedStock } from '@/types'
import { toFiniteNumber } from './utils'

type CorrelationInput = {
  themeId: string
  themeName: string
  stocks: Array<Partial<MergedStock> & { code: string; name?: string }>
  timestamp?: number
}

type StockWithCode = Partial<MergedStock> & { code: string; name?: string }

function calcStockScore(stock: StockWithCode): number {
  const change = Math.max(0, toFiniteNumber(stock.change))
  const volumeRatio = Math.max(0, toFiniteNumber(stock.volumeRatio))
  const leadBonus = String((stock as any).leadStatus || '').includes('龙') ? 25 : 0
  const limitBonus = change >= 9.5 ? 20 : 0
  return change * 4 + Math.min(20, volumeRatio * 4) + leadBonus + limitBonus
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

  // Precompute scores and directions in a single pass
  const scoreByCode = new Map<string, number>()
  const directionByCode = new Map<string, number>()
  let positiveCount = 0
  let negativeCount = 0

  for (const stock of stocks) {
    scoreByCode.set(stock.code, calcStockScore(stock))
    const dir = Math.sign(toFiniteNumber(stock.change))
    directionByCode.set(stock.code, dir)
    if (dir > 0) positiveCount++
    else if (dir < 0) negativeCount++
  }
  const validDirectionCount = positiveCount + negativeCount

  const sorted = [...stocks].sort((a, b) => scoreByCode.get(b.code)! - scoreByCode.get(a.code)!)
  const leader = sorted[0]
  const leaderCode = leader?.code
  const stockCorrelations = new Map<string, StockCorrelation>()
  const coreStocks: string[] = []
  const followerStocks: string[] = []
  const independentStocks: string[] = []

  let sumChange = 0
  let sumVolumeRatio = 0
  let sumMainInflow = 0
  let ztCount = 0

  for (const stock of stocks) {
    const change = toFiniteNumber(stock.change)
    const volumeRatio = toFiniteNumber(stock.volumeRatio)
    const mainInflow = toFiniteNumber((stock as any).mainNetInflow)
    sumChange += change
    sumVolumeRatio += volumeRatio
    sumMainInflow += mainInflow
    if (change >= 9.5) ztCount++

    const dir = directionByCode.get(stock.code)!
    const consistency = dir !== 0 && validDirectionCount > 0
      ? (dir > 0 ? positiveCount : negativeCount) / validDirectionCount
      : 0
    const score = scoreByCode.get(stock.code)!
    const role =
      stock.code === leaderCode && score > 0 ? 'leader' : consistency >= 0.6 ? 'follower' : 'independent'

    const correlation: StockCorrelation = {
      code: stock.code,
      name: stock.name || '',
      change,
      volumeRatio,
      mainNetInflow: mainInflow,
      avgCorrelation: consistency,
      leaderCorrelation: stock.code === leaderCode ? 1 : consistency,
      directionConsistency: consistency,
      changeDiff: Math.abs(change - toFiniteNumber(leader?.change)),
      role,
    }
    stockCorrelations.set(stock.code, correlation)
    if (role === 'leader') coreStocks.push(stock.code)
    else if (role === 'follower') followerStocks.push(stock.code)
    else independentStocks.push(stock.code)
  }

  const overallCorrelation =
    Array.from(stockCorrelations.values()).reduce(
      (sum, item) => sum + item.directionConsistency,
      0,
    ) / stockCorrelations.size

  const leaderScore = leader ? scoreByCode.get(leader.code)! : 0

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
      leader && leaderScore > 0
        ? {
            code: leader.code,
            name: leader.name || '',
            score: leaderScore,
            confidence: sorted[1] ? Math.round((leaderScore / (leaderScore + scoreByCode.get(sorted[1].code)!)) * 100) : 100,
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
      avgChange: sumChange / stocks.length,
      totalZtCount: ztCount,
      avgVolumeRatio: sumVolumeRatio / stocks.length,
      totalMainInflow: sumMainInflow,
    },
  }
}
