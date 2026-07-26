import { DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG } from '@/config/rankTrendLiveStrategyConfig'
import type { TradingPoolThresholds } from '@/types/rankTrendLiveStrategy'
import type {
  TradingPoolAnalysisResult,
  TradingPoolAnalysisRow,
  TradingPoolDecision,
  TradingPoolRiskFlag,
  TradingPoolScoringBreakdown,
  TradingPoolSignalSnapshot,
  TradingPoolSource,
  TradingPoolStatus,
} from './types'

type TradingPoolCandidateLike = Record<string, any>
const INDEPENDENT_CONTINUOUS_SCALE = 6 / 4.5

interface TradingPoolInput {
  candidates: TradingPoolCandidateLike[]
  previousRows?: Array<Partial<TradingPoolAnalysisRow> & { code: string }>
  liveStocks?: TradingPoolCandidateLike[]
}

interface TradingPoolDecisionResult {
  status: TradingPoolStatus
  decision: TradingPoolDecision
  reasons: string[]
  scoringBreakdown: TradingPoolScoringBreakdown
}

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function toOptionalNumber(value: unknown): number | null {
  if (value == null || value === '') return null
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

function normalizeConfidence(value: unknown): number | null {
  const numeric = toOptionalNumber(value)
  if (numeric == null) return null
  return numeric <= 1 ? Math.round(numeric * 1000) / 10 : numeric
}

function hasOwnValue(source: Record<string, any> | null | undefined, key: string): boolean {
  return !!source && Object.prototype.hasOwnProperty.call(source, key)
}

function countBuyVotes(signals: Pick<
  TradingPoolSignalSnapshot,
  'directionSignal' | 'accelerationSignal' | 'zeroCrossSignal' | 'macdCross'
>): number {
  return [
    signals.directionSignal === 'buy',
    signals.accelerationSignal === 'buy',
    signals.zeroCrossSignal === 'buy',
    signals.macdCross === 'golden',
  ].filter(Boolean).length
}

function getEntryDecision(stock: TradingPoolCandidateLike): Record<string, any> | null {
  if (stock.tradingPoolSource === 'live_projection') return null
  return stock.candidateEntryDecision || stock.entryDecision || null
}

function readGateCheckNumber(stock: TradingPoolCandidateLike, key: string): number | null {
  const check = (getEntryDecision(stock)?.checks || []).find((item: any) => item?.key === key)
  return normalizeConfidence(check?.actual)
}

function hasNonJumpHardBlock(stock: TradingPoolCandidateLike): boolean {
  const checks = getEntryDecision(stock)?.checks || []
  return checks.some((check: any) =>
    check?.hardBlock && check?.status === 'fail' && check.key !== 'jump_confidence',
  )
}

function resolveTradingPoolSource(stock: TradingPoolCandidateLike): TradingPoolSource {
  if (stock.tradingPoolSource === 'manual') return 'manual'
  if (stock.tradingPoolSource === 'persisted') return 'persisted'
  if (stock.tradingPoolSource === 'live_projection') return 'live_projection'
  if (stock.tradingPoolSource === 'thesis') return 'thesis'
  if (stock.tradingPoolSource === 'jump_blocked_resonance') return 'thesis'
  if (stock.tradingPoolSource === 'candidate_auto_add') return 'thesis'
  if (getEntryDecision(stock)) return 'thesis'
  return 'unknown'
}

function readRiskFlags(
  rankTrend: any,
  stock: TradingPoolCandidateLike,
  signals: TradingPoolSignalSnapshot,
): TradingPoolRiskFlag[] {
  const flags: TradingPoolRiskFlag[] = []

  if (signals.lifecycleAction === 'veto') flags.push('lifecycle_veto')
  if (signals.macdCross === 'death') flags.push('macd_death_cross')
  if (
    rankTrend?.risk?.overheatReversal?.signal === 'sell' ||
    rankTrend?.risk?.overheat?.signal === 'sell' ||
    stock.overheatSignal === 'sell'
  ) {
    flags.push('overheat_sell')
  }
  if (
    rankTrend?.risk?.capitalDivergence?.signal === 'sell' ||
    rankTrend?.risk?.divergence?.signal === 'sell' ||
    stock.capitalDivergenceSignal === 'sell'
  ) {
    flags.push('capital_divergence_sell')
  }
  if (hasNonJumpHardBlock(stock)) flags.push('candidate_hard_blocked')
  if (signals.limitUp) flags.push('limit_up')
  if (signals.dataQuality !== 'fresh') flags.push('data_stale')

  return flags
}

function directionSign(signal: string | null | undefined): number {
  if (signal === 'buy') return 1
  if (signal === 'sell') return -1
  return 0
}

export function computeResonanceScore(
  signals: Pick<
    TradingPoolSignalSnapshot,
    | 'macdCross'
    | 'jumpDirection'
    | 'jumpConfidence'
    | 'directionSignal'
    | 'directionConfidence'
    | 'accelerationSignal'
    | 'accelerationConfidence'
    | 'zeroCrossSignal'
    | 'zeroCrossConfidence'
  >,
  weights = DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.tradingPool.weights,
): TradingPoolScoringBreakdown {
  const macdCrossScore = signals.macdCross === 'golden' ? 3 : signals.macdCross === 'death' ? -3 : 0
  const jumpDirectionScore = signals.jumpDirection === 'buy' ? 2 : signals.jumpDirection === 'sell' ? -2 : 0
  const discreteScore = macdCrossScore + jumpDirectionScore

  const jumpConfidenceScore =
    ((signals.jumpConfidence ?? 0) / 100) * weights.jumpConfidence * 5 * directionSign(signals.jumpDirection)
  const directionConfidenceScore =
    ((signals.directionConfidence ?? 0) / 100) * weights.directionConfidence * 5 * directionSign(signals.directionSignal)
  const accelerationConfidenceScore =
    ((signals.accelerationConfidence ?? 0) / 100) * weights.accelerationConfidence * 5 * directionSign(signals.accelerationSignal)
  const zeroCrossConfidenceScore =
    ((signals.zeroCrossConfidence ?? 0) / 100) * weights.zeroCrossConfidence * 5 * directionSign(signals.zeroCrossSignal)
  const independentContinuousScore =
    jumpConfidenceScore +
    directionConfidenceScore +
    accelerationConfidenceScore +
    zeroCrossConfidenceScore
  const continuousScore = independentContinuousScore * INDEPENDENT_CONTINUOUS_SCALE

  return {
    totalScore: Math.round((discreteScore + continuousScore) * 100) / 100,
    discreteScore: Math.round(discreteScore * 100) / 100,
    continuousScore: Math.round(continuousScore * 100) / 100,
    discreteDetail: {
      macdCross: macdCrossScore,
      jumpDirection: jumpDirectionScore,
    },
    continuousDetail: {
      jumpConfidence: Math.round(jumpConfidenceScore * INDEPENDENT_CONTINUOUS_SCALE * 100) / 100,
      finalConfidence: 0,
      directionConfidence: Math.round(directionConfidenceScore * INDEPENDENT_CONTINUOUS_SCALE * 100) / 100,
      accelerationConfidence: Math.round(accelerationConfidenceScore * INDEPENDENT_CONTINUOUS_SCALE * 100) / 100,
      zeroCrossConfidence: Math.round(zeroCrossConfidenceScore * INDEPENDENT_CONTINUOUS_SCALE * 100) / 100,
    },
  }
}

function readTradingSignals(stock: TradingPoolCandidateLike): TradingPoolSignalSnapshot {
  const hasRankTrend = hasOwnValue(stock, 'rankTrend')
  const rankTrend = hasRankTrend ? stock.rankTrend : null
  const limitUp = Boolean(rankTrend?.jump?.limitUp ?? rankTrend?._jumpLimitUp ?? false)
  const snapshot: TradingPoolSignalSnapshot = {
    finalSignal: rankTrend?.decision?.final?.signal ?? stock.finalSignal ?? null,
    finalConfidence: normalizeConfidence(rankTrend?.decision?.final?.confidence ?? stock.finalConfidence),
    jumpDirection: rankTrend?.jump?.direction ?? stock.jumpDirection ?? null,
    directionSignal: rankTrend?.technical?.signals?.direction?.signal ?? stock.directionSignal ?? null,
    directionConfidence: normalizeConfidence(
      rankTrend?.technical?.signals?.direction?.confidence ?? stock.directionConfidence,
    ),
    jumpConfidence:
      normalizeConfidence(rankTrend?.jump?.confidence ?? stock.jumpConfidence) ??
      readGateCheckNumber(stock, 'jump_confidence'),
    macdCross: rankTrend?.technical?.macd?.cross ?? stock.macdCross ?? null,
    accelerationSignal:
      rankTrend?.technical?.signals?.acceleration?.signal ?? stock.accelerationSignal ?? null,
    accelerationConfidence: normalizeConfidence(
      rankTrend?.technical?.signals?.acceleration?.confidence ?? stock.accelerationConfidence,
    ),
    zeroCrossSignal: rankTrend?.technical?.signals?.zeroCross?.signal ?? stock.crossSignal ?? null,
    zeroCrossConfidence: normalizeConfidence(
      rankTrend?.technical?.signals?.zeroCross?.confidence ?? stock.crossConfidence,
    ),
    buyVotes: 0,
    riskFlags: [],
    source: resolveTradingPoolSource(stock),
    limitUp,
    momentumSyncBroken: Boolean(rankTrend?.technical?.momentumProfile?.syncBroken),
    lifecycleAction: rankTrend?.cycle?.decision?.action ?? stock.lifecycleAction ?? null,
    dataQuality: hasRankTrend ? (rankTrend != null ? 'fresh' : 'stale') : 'missing',
  }
  snapshot.buyVotes = countBuyVotes(snapshot)
  snapshot.riskFlags = readRiskFlags(rankTrend, stock, snapshot)
  return snapshot
}

function hasFreshSignals(signals: TradingPoolSignalSnapshot): boolean {
  return signals.dataQuality === 'fresh'
}

function hasBearishExecutionEvidence(signals: TradingPoolSignalSnapshot): boolean {
  return (
    signals.jumpDirection === 'sell' ||
    signals.macdCross === 'death' ||
    signals.directionSignal === 'sell' ||
    signals.accelerationSignal === 'sell' ||
    signals.zeroCrossSignal === 'sell'
  )
}

function decideTradingPoolStatus(
  signals: TradingPoolSignalSnapshot,
  previous: Partial<TradingPoolAnalysisRow> | null | undefined,
  scoring: TradingPoolThresholds['scoring'],
  weights: TradingPoolThresholds['weights'],
): TradingPoolDecisionResult {
  const scoringBreakdown = computeResonanceScore(signals, weights)

  if (signals.lifecycleAction === 'veto') {
    return { status: '已退出', decision: 'exit', reasons: ['lifecycle_veto'], scoringBreakdown }
  }

  if (signals.limitUp) {
    return { status: '涨停观察', decision: 'watch', reasons: ['limit_up'], scoringBreakdown }
  }

  if (!hasFreshSignals(signals)) {
    return {
      status: (previous?.status as TradingPoolStatus) || '观察中',
      decision: 'stale',
      reasons: ['signal_stale'],
      scoringBreakdown,
    }
  }

  if (previous?.status === '已介入') {
    if (scoringBreakdown.totalScore < scoring.exitMax && hasBearishExecutionEvidence(signals)) {
      return { status: '已退出', decision: 'exit', reasons: ['score_below_exit'], scoringBreakdown }
    }
    return {
      status: '已介入',
      decision: 'stale',
      reasons: signals.riskFlags.length ? ['intervened_keep_with_risk'] : ['intervened_keep'],
      scoringBreakdown,
    }
  }

  if (scoringBreakdown.totalScore < scoring.exitMax && hasBearishExecutionEvidence(signals)) {
    return { status: '已退出', decision: 'exit', reasons: ['score_below_exit'], scoringBreakdown }
  }

  if (
    scoringBreakdown.totalScore >= scoring.readyMin &&
    signals.macdCross === 'golden' &&
    (signals.jumpConfidence ?? 0) >= scoring.readyJumpMin
  ) {
    return {
      status: '准备介入',
      decision: 'enter',
      reasons: ['strong_consensus', 'macd_golden_cross'],
      scoringBreakdown,
    }
  }

  if (scoringBreakdown.totalScore >= scoring.buyPointMin) {
    const resonance =
      signals.directionSignal === 'buy' &&
      signals.macdCross === 'golden' &&
      signals.accelerationSignal === 'buy' &&
      signals.zeroCrossSignal === 'buy'
        ? ['strong_consensus', 'signal_resonance']
        : ['strong_consensus']
    return { status: '观察买点', decision: 'enter', reasons: resonance, scoringBreakdown }
  }

  if (scoringBreakdown.totalScore >= scoring.observeMin) {
    return { status: '观察中', decision: 'watch', reasons: ['consensus_moderate'], scoringBreakdown }
  }

  return { status: '观察中', decision: 'watch', reasons: ['consensus_moderate'], scoringBreakdown }
}

function buildPreviousRowMap(previousRows: TradingPoolInput['previousRows']) {
  const rowMap = new Map<string, Partial<TradingPoolAnalysisRow>>()
  for (const row of previousRows || []) {
    const code = normalizeCode(row.code)
    if (!code) continue
    rowMap.set(code, row)
  }
  return rowMap
}

export function analyzeTradingPoolCandidate(input: TradingPoolInput): TradingPoolAnalysisResult {
  const tradingPoolConfig = DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.tradingPool
  const scoring = tradingPoolConfig.scoring
  const weights = tradingPoolConfig.weights
  const previousRows = buildPreviousRowMap(input.previousRows)

  const thesisCodes = new Set<string>()
  const mergedCandidates: TradingPoolCandidateLike[] = []

  for (const candidate of input.candidates || []) {
    const code = normalizeCode(candidate.code)
    if (!code) continue
    thesisCodes.add(code)
    mergedCandidates.push(candidate)
  }

  for (const stock of input.liveStocks || []) {
    const code = normalizeCode(stock.code)
    if (!code || thesisCodes.has(code)) continue
    mergedCandidates.push({
      ...stock,
      tradingPoolSource: stock.tradingPoolSource || 'live_projection',
    })
  }

  const rows: TradingPoolAnalysisRow[] = []
  let staleCount = 0
  let exitedCount = 0

  for (const candidate of mergedCandidates) {
    const code = normalizeCode(candidate.code)
    if (!code) continue

    const signals = readTradingSignals(candidate)
    const previous = previousRows.get(code) || null
    const decisionResult = decideTradingPoolStatus(signals, previous, scoring, weights)

    const resolvedSignals = {
      ...signals,
      dataQuality: decisionResult.decision === 'stale' ? 'stale' : signals.dataQuality,
    } as TradingPoolSignalSnapshot

    const row: TradingPoolAnalysisRow = {
      code,
      name: candidate.name ? String(candidate.name) : undefined,
      status: decisionResult.status,
      decision: decisionResult.decision,
      reasons: decisionResult.reasons.slice(),
      signalSnapshot: resolvedSignals,
      scoringBreakdown: decisionResult.scoringBreakdown,
    }

    rows.push(row)
    if (row.decision === 'stale') staleCount += 1
    if (row.decision === 'exit') exitedCount += 1
  }

  return { rows, staleCount, exitedCount }
}

/** 归一化天花板：五维连续全买100%置信理论约55分，30覆盖全部决策阈值(exitMax=8→readyMin=20)并保留强信号余量 */
const RESONANCE_NORMALIZATION_CEILING = 30

export function normalizeResonanceIntensity(totalScore: number): { pct: number; label: string } {
  const pct = Math.max(0, Math.min(100, Math.round((totalScore / RESONANCE_NORMALIZATION_CEILING) * 100)))
  let label: string
  if (pct >= 90) label = '非常强'
  else if (pct >= 67) label = '强'
  else if (pct >= 50) label = '中等'
  else if (pct >= 27) label = '较弱'
  else label = '非常弱'
  return { pct, label }
}
