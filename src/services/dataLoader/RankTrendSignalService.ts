import { debugLog } from '@/utils/logger'
import { dataLayer } from '../DataLayer'
import { rankTrendAnalyzer, type RankTrendPreparedSnapshot } from '../RankTrendAnalyzer'
import { applyJumpSignal, applyRankTrendAnalysis } from '../rankTrend/compat'
import { evaluateJumpSignal, incrementJumpBar, registerJumpEntry, unregisterJumpPosition } from '../rankTrend/jumpSignalService'
import { jumpSignalNotifier } from '../rankTrend/JumpSignalNotifier'
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
        if (isRankTrendAnalysisResult(update.rankTrend)) {
          applyRankTrendAnalysis(stock, update.rankTrend)
        }
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

    // 跳跃检测：在 RankTrend 分析结果上运行入场/出场评估
    this.applyJumpSignals()

    return this.updateStockSignals(updates)
  }

  private applyJumpSignals(): void {
    const stocks = dataLayer.getStocks()
    if (!stocks.length) return

    incrementJumpBar()
    const stockCodeSet = new Set(stocks.map(s => s.code))

    for (const stock of stocks) {
      const rankTrend = stock.rankTrend as RankTrendAnalysisResult | undefined
      if (!rankTrend?.meta?.code) continue

      const percentiles = rankTrendAnalyzer.getCachedPercentiles(stock.code)
      if (!percentiles) continue

      const result = evaluateJumpSignal(stock, rankTrend, percentiles, stockCodeSet.has(stock.code))

      // 持仓管理
      if (result.isEntry) {
        const price = Number(stock.price || stock.lastTradePrice || 0)
        registerJumpEntry(stock.code, stock.name || '', price, rankTrend.meta?.currentRank ? String(rankTrend.meta.currentRank) : '')
        jumpSignalNotifier.notifyEntry(stock, result)
      }
      if (result.isExit) {
        unregisterJumpPosition(stock.code)
        jumpSignalNotifier.notifyExit(stock, result)
      }

      applyJumpSignal(stock, result)
    }
  }

  async preloadSnapshots(codes: string[]): Promise<RankTrendPreparedSnapshot[]> {
    return rankTrendAnalyzer.preloadSnapshots({ codes })
  }

  async applySignalsToMerged(
    merged: any[],
    options: { snapshots?: RankTrendPreparedSnapshot[] } = {},
  ): Promise<any[]> {
    const newRankMap = new Map(merged.map((s, i) => [s.code, i + 1]))
    const rankTrends = await rankTrendAnalyzer.getRankTrends(newRankMap, {
      updateSignalStore: false,
      snapshots: options.snapshots,
    })
    const coverageWarning = this.extractRankTrendCoverageWarning(rankTrends)

    for (const stock of merged) {
      stock.rank = newRankMap.get(stock.code)
      extraDataProjector.projectRuntimeFields(stock)

      const trend = rankTrends.get(stock.code)
      if (isRankTrendAnalysisResult(trend)) {
        applyRankTrendAnalysis(stock, trend)
      }
      stock.rankTrendCoverageWarning = coverageWarning || undefined
    }

    if (coverageWarning) {
      logCoverageWarning('[DataLoader] 综合榜单信号基于不完整快照样本:', coverageWarning)
    }

    // 跳跃检测
    const stockCodeSet = new Set(merged.map((s: any) => s.code))
    for (const stock of merged) {
      const rankTrend = stock.rankTrend as RankTrendAnalysisResult | undefined
      if (!rankTrend?.meta?.code) continue

      const percentiles = rankTrendAnalyzer.getCachedPercentiles(stock.code)
      if (!percentiles) continue

      const result = evaluateJumpSignal(stock, rankTrend, percentiles, stockCodeSet.has(stock.code))

      if (result.isEntry) {
        const price = Number(stock.price || stock.lastTradePrice || 0)
        registerJumpEntry(stock.code, stock.name || '', price, '')
        jumpSignalNotifier.notifyEntry(stock, result)
      }
      if (result.isExit) {
        unregisterJumpPosition(stock.code)
        jumpSignalNotifier.notifyExit(stock, result)
      }

      applyJumpSignal(stock, result)
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
