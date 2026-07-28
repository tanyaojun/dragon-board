import { debugLog } from '@/utils/logger'
import { buildCandidateJournalProjection } from '../candidate/CandidateProjectionBuilder'
import { candidateJournalService } from '../candidate/CandidateJournalService'
import { applyCandidatePoolProjections } from '../candidate/CandidatePoolStatusProjector'
import { dataLayer } from '../DataLayer'
import { rankTrendAnalyzer, type RankTrendPreparedSnapshot } from '../RankTrendAnalyzer'
import { applyJumpSignal, applyRankTrendAnalysis } from '../rankTrend/compat'
import { evaluateJumpSignal, incrementJumpBar, registerJumpEntry, unregisterJumpPosition } from '../rankTrend/jumpSignalService'
import { analyzeRankResonance } from '../rankTrend/resonanceAnalyzer'
import { fusionCandidateNotifier } from '../rankTrend/FusionCandidateNotifier'
import { buildFusionStrategyProjections } from '../rankTrend/FusionStrategyProjector'
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

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function buildAttentionRankMap(stocks: any[]): Map<string, number> {
  const ordered = stocks
    .filter((stock) => {
      const avgRankNum = Number(stock.avgRankNum)
      return Number.isFinite(avgRankNum) && avgRankNum > 0
    })
    .sort(
      (left, right) =>
        Number(left.avgRankNum) - Number(right.avgRankNum) ||
        String(left.code).localeCompare(String(right.code)),
    )
  return new Map(ordered.map((stock, index) => [stock.code, index + 1]))
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
  private candidatePoolSyncPromise: Promise<void> | null = null
  private candidatePoolGeneration = 0
  private pendingCandidatePoolBatch: { stocks: any[]; generation: number } | null = null

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

    const rankMap = buildAttentionRankMap(stocks)
    if (!rankMap.size) return stocks

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
    this.applyResonanceFinals(mergedStocks, new Set(results.keys()))
    this.precomputeDisplayFields(mergedStocks)
    this.scheduleCandidatePoolSync(mergedStocks)

    return mergedStocks
  }

  private applyJumpSignals(stocks: any[] = dataLayer.getStocks()): void {
    if (!stocks.length) return

    incrementJumpBar()
    for (const stock of stocks) {
      const rankTrend = stock.rankTrend as RankTrendAnalysisResult | undefined
      if (!rankTrend?.meta?.code) continue

      const analysisSeries = rankTrendAnalyzer.getLatestAnalysisSeries(stock.code)
      if (!analysisSeries) continue

      const result = evaluateJumpSignal(
        stock,
        rankTrend,
        analysisSeries.percentiles,
        true,
        analysisSeries.ranks,
      )

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

  private applyResonanceFinals(stocks: any[], freshCodes: Set<string>): void {
    const seriesByCode = new Map<string, { ranks: number[]; percentiles: number[]; frameKeys: string[] }>()
    const shortChanges: number[] = []
    const marketFrameKeys = (rankTrendAnalyzer.getLatestAnalysisFrameKeys() || []).slice(-4)

    for (const stock of stocks) {
      if (!freshCodes.has(stock.code)) continue
      const rankTrend = stock.rankTrend as RankTrendAnalysisResult | undefined
      const series = rankTrend ? rankTrendAnalyzer.getLatestAnalysisSeries(stock.code) : null
      if (!series || series.percentiles.length === 0) continue
      seriesByCode.set(stock.code, series)
      if (marketFrameKeys.length < 4 || rankTrend?.meta?.sampleQuality?.status === 'insufficient') continue
      const percentileByFrame = new Map(
        series.frameKeys.map((frameKey, index) => [frameKey, series.percentiles[index]]),
      )
      if (marketFrameKeys.some((frameKey) => !percentileByFrame.has(frameKey))) continue
      const shortChange = percentileByFrame.get(marketFrameKeys.at(-1)!)! - percentileByFrame.get(marketFrameKeys[0])!
      if (!Number.isFinite(shortChange)) continue
      shortChanges.push(shortChange)
    }

    const sortedChanges = shortChanges.sort((left, right) => left - right)
    const midpoint = Math.floor(sortedChanges.length / 2)
    const marketMedianShortChange = sortedChanges.length === 0
      ? Number.NaN
      : sortedChanges.length % 2
        ? sortedChanges[midpoint]
        : (sortedChanges[midpoint - 1] + sortedChanges[midpoint]) / 2

    for (const stock of stocks) {
      if (!freshCodes.has(stock.code)) continue
      const rankTrend = stock.rankTrend as RankTrendAnalysisResult | undefined
      if (!rankTrend) continue
      const quality = rankTrend.meta?.sampleQuality
      const resonance = analyzeRankResonance({
        percentiles: seriesByCode.get(stock.code)?.percentiles || [],
        sampleQuality: {
          status: quality?.status || 'insufficient',
          timelineValid: quality?.timelineValid !== false,
        },
        marketMedianShortChange,
        marketSampleCount: shortChanges.length,
        jump: {
          direction: rankTrend.jump?.direction || 'hold',
          event: rankTrend.jump?.event || 'none',
          events: rankTrend.jump?.events || [],
        },
        entry: {
          isNew: (seriesByCode.get(stock.code)?.percentiles.length || 0) === 1,
          currentAttentionPercentile: rankTrend.meta.currentPercentile,
        },
      })
      rankTrend.resonance = resonance
      rankTrend.decision.final = { signal: resonance.direction, confidence: resonance.score }
      stock.finalSignal = resonance.direction
      stock.finalConfidence = resonance.score
    }
  }

  async preloadSnapshots(codes: string[]): Promise<RankTrendPreparedSnapshot[]> {
    return rankTrendAnalyzer.preloadSnapshots({ codes })
  }

  async applySignalsToMerged(
    merged: any[],
    options: { snapshots?: RankTrendPreparedSnapshot[] } = {},
  ): Promise<any[]> {
    const startedAt = performance.now()
    const newRankMap = buildAttentionRankMap(merged)
    const rankTrends = await rankTrendAnalyzer.getRankTrends(newRankMap, {
      updateSignalStore: false,
      snapshots: options.snapshots,
    })
    const coverageWarning = this.extractRankTrendCoverageWarning(rankTrends)

    for (const stock of merged) {
      stock.rank = newRankMap.get(stock.code)
      if (!newRankMap.has(stock.code)) {
        stock.rankTrend = undefined
        stock.rankTrendCoverageWarning = '均榜缺失'
        stock.finalSignal = 'hold'
        stock.finalConfidence = 0
        continue
      }
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

    // 核心展示字段必须在候选池/Fusion/交易日志投影前完成并返回。
    this.applyJumpSignals(merged)
    this.applyResonanceFinals(merged, new Set(rankTrends.keys()))
    this.precomputeDisplayFields(merged)
    this.scheduleCandidatePoolSync(merged)
    debugLog('[RankTrendSignalService] 核心信号阶段完成', {
      stockCount: merged.length,
      elapsedMs: Math.round(performance.now() - startedAt),
    })

    return merged
  }

  /**
   * 批量预计算三个展示字段（变化%、跃迁度、共振强度）并写入 stock 对象缓存。
   * DataTable 模板和 uiStore 排序直接读取 _ 前缀缓存字段，消除 O(n) 次重量级分析调用。
   */
  private precomputeDisplayFields(stocks: any[]): void {
    if (!stocks.length) return

    for (const stock of stocks) {
      const rankTrend = stock.rankTrend as RankTrendAnalysisResult | undefined

      // 变化% 和 跃迁度：直接从 rankTrend 读取
      stock._rankChange = Math.round(rankTrend?.meta?.change ?? 0)
      stock._jumpConfidence = Math.round(rankTrend?.jump?.confidence ?? 0)
      stock._jumpDirection = rankTrend?.jump?.direction ?? null

      stock._resonancePct = rankTrend?.resonance?.score ?? 0
      stock._resonanceLabel = rankTrend?.resonance?.label ?? '样本不足'
      stock._resonanceRawScore = rankTrend?.resonance?.score ?? 0
    }
  }

  private scheduleCandidatePoolSync(stocks: any[]): void {
    if (!stocks.length) return
    this.pendingCandidatePoolBatch = {
      stocks,
      generation: ++this.candidatePoolGeneration,
    }
    if (this.candidatePoolSyncPromise) return

    this.candidatePoolSyncPromise = this.flushCandidatePoolSync()
      .catch((error) => {
        console.warn(
          '[RankTrendSignalService] 候选池后台同步失败，保留核心信号结果:',
          error instanceof Error ? error.message : String(error),
        )
      })
      .finally(() => {
        this.candidatePoolSyncPromise = null
        const pending = this.pendingCandidatePoolBatch
        if (pending) this.scheduleCandidatePoolSync(pending.stocks)
      })
  }

  private async flushCandidatePoolSync(): Promise<void> {
    while (this.pendingCandidatePoolBatch) {
      const batch = this.pendingCandidatePoolBatch
      this.pendingCandidatePoolBatch = null
      const startedAt = performance.now()
      await this.syncCandidatePoolSignals(batch.stocks)
      if (batch.generation === this.candidatePoolGeneration) {
        this.publishCandidatePoolFields(batch.stocks)
      }
      debugLog('[RankTrendSignalService] 候选池投影阶段完成', {
        stockCount: batch.stocks.length,
        published: batch.generation === this.candidatePoolGeneration,
        elapsedMs: Math.round(performance.now() - startedAt),
      })
    }
  }

  private publishCandidatePoolFields(projectedStocks: any[]): void {
    const projectionByCode = new Map(projectedStocks.map((stock) => [stock.code, stock]))
    const currentStocks = dataLayer.getStocks()
    if (!currentStocks.length) return

    dataLayer.setMergedStocks(
      currentStocks.map((stock) => {
        const projected = projectionByCode.get(stock.code)
        if (!projected) return stock
        return {
          ...stock,
          candidatePoolStatus: projected.candidatePoolStatus,
          candidatePoolLabel: projected.candidatePoolLabel,
          candidatePoolLiveDecisionLabel: projected.candidatePoolLiveDecisionLabel,
          candidatePoolLiveDecisionSummary: projected.candidatePoolLiveDecisionSummary,
          candidatePoolProjection: projected.candidatePoolProjection,
          candidatePoolEntryId: projected.candidatePoolEntryId,
          candidatePoolSource: projected.candidatePoolSource,
          candidatePoolUpdatedAt: projected.candidatePoolUpdatedAt,
          candidateResonanceObserve: projected.candidateResonanceObserve,
        }
      }),
    )
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
