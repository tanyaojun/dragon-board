import { debugLog } from '@/utils/logger'
import { dataLayer } from '../DataLayer'
import { rankTrendAnalyzer } from '../RankTrendAnalyzer'
import { applyRankTrendAnalysis } from '../rankTrend/compat'
import type { RankTrendAnalysisResult } from '../rankTrend/types'
import { extraDataProjector } from './ExtraDataProjector'
import type { StockSignalUpdate } from './types'

function isRankTrendAnalysisResult(value: unknown): value is RankTrendAnalysisResult {
  return !!(
    value &&
    typeof value === 'object' &&
    'meta' in value &&
    'technical' in value &&
    'cycle' in value &&
    'risk' in value &&
    'decision' in value
  )
}

function logCoverageWarning(message: string, coverageWarning: string) {
  if (/^包含 \d+ 个 delayed 快照$/.test(coverageWarning)) {
    debugLog(message, coverageWarning)
    return
  }

  console.warn(message, coverageWarning)
}

export class RankTrendSignalService {
  updateStockSignals(updates: StockSignalUpdate[]) {
    const stocks = dataLayer.getStocks()
    const stockMap = new Map(stocks.map((s) => [s.code, s]))

    for (const update of updates) {
      const stock = stockMap.get(update.code)
      if (stock) {
        applyRankTrendAnalysis(
          stock,
          isRankTrendAnalysisResult(update.rankTrend) ? update.rankTrend : null,
        )
        stock.rankTrendCoverageWarning = update.coverageWarning || undefined
      }
    }

    const mergedStocks = Array.from(stockMap.values())
    return mergedStocks
  }

  async refreshRankTrendSignals(): Promise<ReturnType<RankTrendSignalService['updateStockSignals']>> {
    const stocks = dataLayer.getStocks()
    if (!stocks.length) return []

    const rankMap = new Map<string, number>()
    stocks.forEach((stock, index) => {
      rankMap.set(stock.code, index + 1)
    })

    const results = await rankTrendAnalyzer.getRankTrends(rankMap, {
      updateSignalStore: false,
    })
    const coverageWarning = this.extractRankTrendCoverageWarning(results)

    const updates: StockSignalUpdate[] = []
    for (const [code, rankTrend] of results.entries()) {
      updates.push({ code, rankTrend, coverageWarning })
    }

    if (coverageWarning) {
      logCoverageWarning('[DataLoader] 排名趋势信号使用了不完整快照样本:', coverageWarning)
    }

    return this.updateStockSignals(updates)
  }

  async applySignalsToMerged(merged: any[]): Promise<any[]> {
    const newRankMap = new Map(merged.map((s, i) => [s.code, i + 1]))
    const rankTrends = await rankTrendAnalyzer.getRankTrends(newRankMap, {
      updateSignalStore: false,
    })
    const coverageWarning = this.extractRankTrendCoverageWarning(rankTrends)

    for (const stock of merged) {
      stock.rank = newRankMap.get(stock.code)
      extraDataProjector.projectRuntimeFields(stock)

      const trend = rankTrends.get(stock.code)
      applyRankTrendAnalysis(stock, isRankTrendAnalysisResult(trend) ? trend : null)
      stock.rankTrendCoverageWarning = coverageWarning || undefined
    }

    if (coverageWarning) {
      logCoverageWarning('[DataLoader] 综合榜单信号基于不完整快照样本:', coverageWarning)
    }
    return merged
  }

  extractRankTrendCoverageWarning(
    results: Map<string, RankTrendAnalysisResult>,
  ): string | null {
    for (const result of results.values()) {
      const warning = result?.meta?.sampleQuality?.coverageWarning
      if (warning) return warning
    }
    return null
  }
}

export const rankTrendSignalService = new RankTrendSignalService()
