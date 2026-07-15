import { debugLog } from '@/utils/logger'
import { buildCandidateJournalProjection } from '../candidate/CandidateProjectionBuilder'
import { candidateJournalService } from '../candidate/CandidateJournalService'
import { applyCandidatePoolProjections } from '../candidate/CandidatePoolStatusProjector'
import { dataLayer } from '../DataLayer'
import { rankTrendAnalyzer, type RankTrendPreparedSnapshot } from '../RankTrendAnalyzer'
import { applyJumpSignal, applyRankTrendAnalysis } from '../rankTrend/compat'
import { evaluateJumpSignal, incrementJumpBar, registerJumpEntry, unregisterJumpPosition } from '../rankTrend/jumpSignalService'
import { fusionCandidateNotifier } from '../rankTrend/FusionCandidateNotifier'
import { buildFusionStrategyProjections } from '../rankTrend/FusionStrategyProjector'
import type { RankTrendAnalysisResult } from '../rankTrend/types'
import {
  analyzeTradingPoolCandidate,
  normalizeResonanceIntensity,
} from '../candidate/TradingPoolAnalysisService'
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

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function mergeCandidatePoolProjections(
  liveProjections: ReturnType<typeof buildFusionStrategyProjections>,
  journalProjections: ReturnType<typeof buildFusionStrategyProjections>,
) {
  const projectionByCode = new Map(liveProjections.map((projection) => [normalizeCode(projection.stockCode), projection]))
  for (const projection of journalProjections) {
    const code = normalizeCode(projection.stockCode)
    if (!code) continue
    projectionByCode.set(code, projection)
  }
  return Array.from(projectionByCode.values())
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

    const mergedStocks = this.updateStockSignals(updates)
    // 跳跃检测与 V3 实盘信号都应基于本轮最新 rankTrend 结果计算。
    this.applyJumpSignals(mergedStocks)
    await this.syncCandidatePoolSignals(mergedStocks)

    return mergedStocks
  }

  private applyJumpSignals(stocks: any[] = dataLayer.getStocks()): void {
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
      }
      if (result.isExit) {
        unregisterJumpPosition(stock.code)
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
    this.applyJumpSignals(merged)
    await this.syncCandidatePoolSignals(merged)

    // 预计算展示字段：避免 DataTable 模板渲染和 uiStore 排序时逐行调用 analyzeTradingPoolCandidate
    this.precomputeDisplayFields(merged)

    return merged
  }

  /**
   * 批量预计算三个展示字段（变化%、跃迁度、共振强度）并写入 stock 对象缓存。
   * DataTable 模板和 uiStore 排序直接读取 _ 前缀缓存字段，消除 O(n) 次重量级分析调用。
   */
  private precomputeDisplayFields(stocks: any[]): void {
    if (!stocks.length) return

    // 分离 thesis 候选和实时投影，供 analyzeTradingPoolCandidate 批量分析
    const thesisCandidates: any[] = []
    const liveStocks: any[] = []

    for (const stock of stocks) {
      const rankTrend = stock.rankTrend as RankTrendAnalysisResult | undefined

      // 变化% 和 跃迁度：直接从 rankTrend 读取
      stock._rankChange = Math.round(rankTrend?.meta?.change ?? 0)
      stock._jumpConfidence = Math.round(rankTrend?.jump?.confidence ?? 0)
      stock._jumpDirection = rankTrend?.jump?.direction ?? null

      // 共振强度需要 analyzeTradingPoolCandidate 批量计算
      if (stock.candidatePoolEntryId || stock.candidatePoolProjection?.entryDecision) {
        thesisCandidates.push({
          ...stock,
          candidateEntryDecision: stock.candidatePoolProjection?.entryDecision,
          rankTrend,
        })
      } else if (rankTrend) {
        liveStocks.push({ ...stock, rankTrend })
      }
    }

    // 批量计算共振强度（一次调用处理所有股票）
    if (thesisCandidates.length > 0 || liveStocks.length > 0) {
      const analysis = analyzeTradingPoolCandidate({
        candidates: thesisCandidates,
        liveStocks,
      })
      const rowByCode = new Map(analysis.rows.map((row) => [row.code, row]))

      for (const stock of stocks) {
        const row = rowByCode.get(stock.code)
        const totalScore = row?.scoringBreakdown?.totalScore ?? null
        if (totalScore != null) {
          const { pct, label } = normalizeResonanceIntensity(totalScore)
          stock._resonancePct = pct
          stock._resonanceLabel = label
          stock._resonanceRawScore = totalScore
        }
      }
    }
  }

  private async syncCandidatePoolSignals(stocks: any[]): Promise<void> {
    if (!stocks.length) return

    try {
      await fusionCandidateNotifier.process(stocks)
    } catch (error) {
      console.warn(
        '[RankTrendSignalService] fusion 自动入池失败，保留本地 RankTrend 刷新结果:',
        error instanceof Error ? error.message : String(error),
      )
    }

    try {
      const codes = stocks.map((stock) => stock.code)
      const openCandidateByCode = await candidateJournalService.getOpenCandidateMap(codes)
      const executionOverlayByCode = Object.fromEntries(
        Object.entries(openCandidateByCode).map(([code, entry]) => [
          code,
          candidateJournalService.toExecutionOverlay(entry),
        ]),
      )
      const projections = buildFusionStrategyProjections(stocks, { executionOverlayByCode })
      const journalProjections = stocks
        .map((stock) => {
          const entry = openCandidateByCode[normalizeCode(stock.code)]
          return entry ? buildCandidateJournalProjection(entry, stock) : null
        })
        .filter(Boolean) as typeof projections
      applyCandidatePoolProjections(stocks, mergeCandidatePoolProjections(projections, journalProjections))
    } catch (error) {
      console.warn(
        '[RankTrendSignalService] 候选池 execution overlay 读取失败，使用无 overlay 投影:',
        error instanceof Error ? error.message : String(error),
      )
      const projections = buildFusionStrategyProjections(stocks, { executionOverlayByCode: {} })
      applyCandidatePoolProjections(stocks, projections)
    }
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
