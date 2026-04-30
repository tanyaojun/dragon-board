import {
  cloneDefaultRankTrendRuntimeConfig,
  normalizeRankTrendRuntimeConfig,
  type RTConfigPatch,
} from '@/type/rankTrendDefaults'
import { analyzeAttentionCycle } from '@/services/rankTrend/attentionCycleAnalyzer'
import { composeCandidateTier } from '@/services/rankTrend/candidateTierComposer'
import { analyzeMarketRegime } from '@/services/rankTrend/marketRegimeAnalyzer'
import { composeDecision } from '@/services/rankTrend/resultComposer'
import { analyzeRiskSignals } from '@/services/rankTrend/riskSignalAnalyzer'
import {
  analyzeFallbackTechnicalSignals,
  analyzeTechnicalSignals,
} from '@/services/rankTrend/technicalSignalAnalyzer'
import type { RankTrendAnalysisResult } from '@/services/rankTrend/types'
import { getTechnicalMinSamples } from '@/services/rankTrend/utils'
import type {
  BacktestMeta,
  ReplayEngineOptions,
  ReplayFrame,
  ReplaySignal,
  ReplayStock,
} from './types'

const DEFAULT_WINDOW_SIZE = 50

function toNumber(value: unknown, fallback = 0): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function calculatePercentileRank(rank: number, totalCount: number): number {
  if (!Number.isFinite(rank) || !Number.isFinite(totalCount) || totalCount <= 0) return 0
  return ((totalCount - rank + 1) / totalCount) * 100
}

function buildMarketBreathData(frame: ReplayFrame): Record<string, any> {
  return {
    ...(frame.marketContext.payload || {}),
    marketData: {
      ...(frame.marketContext.marketStats || {}),
      ...(frame.marketContext.limitSummary || {}),
      ...((frame.marketContext.sentiment as any)?.marketData || {}),
    },
    sentiment: frame.marketContext.sentiment || undefined,
    moneyFlow: frame.marketContext.moneyFlow || undefined,
    indices: frame.marketContext.indices || undefined,
    rotationSummary: frame.marketContext.rotationSummary || undefined,
  }
}

function findStock(frame: ReplayFrame, code: string): ReplayStock | null {
  return frame.stocks.find((stock) => stock.code === code) || null
}

export class RankTrendReplayEngine {
  private readonly config: ReturnType<typeof cloneDefaultRankTrendRuntimeConfig>

  constructor(configPatch: RTConfigPatch = {}) {
    this.config = normalizeRankTrendRuntimeConfig(cloneDefaultRankTrendRuntimeConfig(), configPatch)
  }

  replay(frames: ReplayFrame[], options: ReplayEngineOptions): ReplaySignal[] {
    const warmupCount = options.warmupCount ?? getTechnicalMinSamples(this.config)
    const windowSize = options.windowSize ?? DEFAULT_WINDOW_SIZE
    const startIndex = frames.length >= warmupCount ? warmupCount - 1 : 0
    const maxSignals =
      typeof options.maxSignals === 'number' && Number.isFinite(options.maxSignals) && options.maxSignals > 0
        ? Math.floor(options.maxSignals)
        : null
    const signals: ReplaySignal[] = []

    for (let index = startIndex; index < frames.length; index++) {
      const frameSignals = this.replayFrameAt(frames, index, { windowSize, meta: options.meta })
      if (maxSignals) {
        signals.push(...frameSignals.slice(0, Math.max(maxSignals - signals.length, 0)))
        if (signals.length >= maxSignals) break
      } else {
        signals.push(...frameSignals)
      }
    }

    return signals
  }

  replayFrameAt(
    frames: ReplayFrame[],
    frameIndex: number,
    options: { windowSize?: number; meta: BacktestMeta },
  ): ReplaySignal[] {
    const frame = frames[frameIndex]
    if (!frame) return []

    const windowSize = options.windowSize ?? DEFAULT_WINDOW_SIZE
    const historyFrames = frames.slice(Math.max(0, frameIndex - windowSize + 1), frameIndex + 1)
    const regime = analyzeMarketRegime({
      breathData: buildMarketBreathData(frame),
      stocks: frame.stocks,
    })

    return frame.stocks
      .map((stock) => this.replayStock(stock, frame, historyFrames, regime, options.meta))
      .filter((signal: ReplaySignal | null): signal is ReplaySignal => signal !== null)
  }

  private replayStock(
    stock: ReplayStock,
    frame: ReplayFrame,
    historyFrames: ReplayFrame[],
    regime: ReturnType<typeof analyzeMarketRegime>,
    meta: BacktestMeta,
  ): ReplaySignal | null {
    const ranks: number[] = []
    const percentiles: number[] = []

    for (const historicalFrame of historyFrames) {
      const row = findStock(historicalFrame, stock.code)
      if (!row) continue
      const rank = toNumber(row.rank, 0)
      if (rank <= 0 || historicalFrame.stocks.length === 0) continue
      ranks.push(rank)
      percentiles.push(calculatePercentileRank(rank, historicalFrame.stocks.length))
    }

    if (!ranks.length || !percentiles.length) return null

    const currentRank = ranks[ranks.length - 1]
    const currentPercentile = percentiles[percentiles.length - 1]
    const previousPercentile =
      percentiles.length >= 2 ? percentiles[percentiles.length - 2] : currentPercentile
    const displayChange = currentPercentile - previousPercentile
    const rawChange = ranks[0] - currentRank
    const stockChange = toNumber(stock.change)
    const volumeRatio = toNumber(stock.volumeRatio)
    const zlje = toNumber(stock.zlje)
    const zljzb = toNumber(stock.zljzb)

    const technical =
      percentiles.length >= getTechnicalMinSamples(this.config)
        ? analyzeTechnicalSignals(percentiles, this.config)
        : analyzeFallbackTechnicalSignals({
            percentiles,
            displayChange,
            stockChange,
            volumeRatio,
            zlje,
            zljzb,
            config: this.config,
          })
    const cycle = analyzeAttentionCycle({
      ranks,
      percentiles,
    })
    const risk = analyzeRiskSignals({
      currentPercentile,
      technical,
      cycle,
      zlje,
      zljzb,
      volumeRatio,
    })
    const decision = composeDecision({
      technical,
      cycle,
      risk,
      config: this.config,
    })
    const strategy = composeCandidateTier({
      technical,
      cycle,
      risk,
      regime,
    })

    const rankTrend: RankTrendAnalysisResult = {
      meta: {
        code: stock.code,
        currentRank,
        currentPercentile,
        change: displayChange,
        rawChange,
        updateTime: frame.timestamp,
        sampleQuality: {
          snapshotType: frame.type,
          sampleCount: percentiles.length,
          requiredSampleCount: getTechnicalMinSamples(this.config),
          status:
            percentiles.length >= getTechnicalMinSamples(this.config)
              ? 'ok'
              : percentiles.length >= 5
                ? 'degraded'
                : 'insufficient',
          coverageWarning:
            meta.sampleQuality === 'ok'
              ? undefined
              : meta.warnings[0] || '样本质量降级',
          latestTradingDate: frame.tradingDate,
          latestSlotTime: frame.slotTime,
          delayedCount: meta.delayedCount,
          restoredCount: meta.restoredCount,
        },
      },
      technical,
      cycle,
      risk,
      decision,
      strategy,
    }

    return {
      snapshotId: frame.snapshotId,
      timestamp: frame.timestamp,
      tradingDate: frame.tradingDate,
      slotTime: frame.slotTime,
      code: stock.code,
      name: stock.name,
      rank: currentRank,
      price: Number.isFinite(Number(stock.price)) ? Number(stock.price) : null,
      rankTrend,
      candidateTier: strategy.candidateTier,
      action: strategy.action,
      stage: cycle.stage,
      regime: regime.state,
      confidence: decision.final.confidence,
    }
  }
}
