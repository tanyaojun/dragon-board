import type {
  TradingPoolAnalysisResult,
  TradingPoolAnalysisRow,
  TradingPoolDecision,
  TradingPoolRiskFlag,
  TradingPoolSignalSnapshot,
  TradingPoolSource,
  TradingPoolStatus,
} from './types'
import type { TradingPoolThresholds } from '@/types/rankTrendLiveStrategy'
import { DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG } from '@/config/rankTrendLiveStrategyConfig'

type TradingPoolCandidateLike = Record<string, any>

interface TradingPoolInput {
  candidates: TradingPoolCandidateLike[]
  previousRows?: Array<Partial<TradingPoolAnalysisRow> & { code: string }>
  liveStocks?: TradingPoolCandidateLike[]
  thresholds?: TradingPoolThresholds
}

interface TradingPoolDecisionResult {
  status: TradingPoolStatus
  decision: TradingPoolDecision
  reasons: string[]
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

function hasDoubleRisk(signals: TradingPoolSignalSnapshot): boolean {
  return (
    signals.riskFlags.includes('overheat_sell') &&
    signals.riskFlags.includes('capital_divergence_sell')
  )
}

function getEntryDecision(stock: TradingPoolCandidateLike): Record<string, any> | null {
  if (stock.tradingPoolSource === 'live_projection') return null
  return stock.candidateEntryDecision || stock.entryDecision || null
}

function readGateCheckNumber(stock: TradingPoolCandidateLike, key: string): number | null {
  const check = (getEntryDecision(stock)?.checks || []).find((item: any) => item?.key === key)
  return normalizeConfidence(check?.actual)
}

function isJumpBlockedOnly(stock: TradingPoolCandidateLike): boolean {
  const checks = getEntryDecision(stock)?.checks || []
  const hardBlocks = checks.filter((check: any) => check?.hardBlock && check?.status === 'fail')
  return hardBlocks.length > 0 && hardBlocks.every((check: any) => check.key === 'jump_confidence')
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
  const decision = getEntryDecision(stock)
  if (decision?.accepted) return 'candidate_auto_add'
  if (isJumpBlockedOnly(stock)) return 'jump_blocked_resonance'
  if (decision) return 'candidate_watch'
  return 'unknown'
}

function readRiskFlags(
  rankTrend: any,
  stock: TradingPoolCandidateLike,
  signals: TradingPoolSignalSnapshot,
  t: TradingPoolThresholds,
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
  if (signals.momentumSyncBroken) flags.push('momentum_sync_broken')
  if ((signals.jumpConfidence ?? 100) < t.downgradeJumpMin) flags.push('jump_confidence_low')
  if ((signals.finalConfidence ?? 100) < t.downgradeFinalMin) flags.push('final_confidence_low')
  if (hasNonJumpHardBlock(stock)) flags.push('candidate_hard_blocked')
  if (signals.dataQuality !== 'fresh') flags.push('data_stale')

  return flags
}

function readTradingSignals(stock: TradingPoolCandidateLike, t: TradingPoolThresholds): TradingPoolSignalSnapshot {
  const hasRankTrend = hasOwnValue(stock, 'rankTrend')
  const rankTrend = hasRankTrend ? stock.rankTrend : null
  const snapshot: TradingPoolSignalSnapshot = {
    finalSignal: rankTrend?.decision?.final?.signal ?? stock.finalSignal ?? null,
    finalConfidence: normalizeConfidence(rankTrend?.decision?.final?.confidence ?? stock.finalConfidence),
    jumpDirection: rankTrend?.jump?.direction ?? stock.jumpDirection ?? null,
    directionSignal: rankTrend?.technical?.signals?.direction?.signal ?? stock.directionSignal ?? null,
    directionConfidence: normalizeConfidence(
      rankTrend?.technical?.signals?.direction?.confidence ?? stock.directionConfidence,
    ),
    jumpConfidence: normalizeConfidence(rankTrend?.jump?.confidence ?? stock.jumpConfidence) ??
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
    momentumSyncBroken: Boolean(rankTrend?.technical?.momentumProfile?.syncBroken),
    lifecycleAction: rankTrend?.cycle?.decision?.action ?? stock.lifecycleAction ?? null,
    dataQuality: hasRankTrend ? (rankTrend != null ? 'fresh' : 'stale') : 'missing',
  }
  snapshot.buyVotes = countBuyVotes(snapshot)
  snapshot.riskFlags = readRiskFlags(rankTrend, stock, snapshot, t)
  return snapshot
}

function hasFreshSignals(signals: TradingPoolSignalSnapshot): boolean {
  return signals.dataQuality === 'fresh'
}

function decideTradingPoolStatus(
  signals: TradingPoolSignalSnapshot,
  previous: Partial<TradingPoolAnalysisRow> | null | undefined,
  t: TradingPoolThresholds,
): TradingPoolDecisionResult {
  if (!hasFreshSignals(signals)) {
    return {
      status: (previous?.status as TradingPoolStatus) || '观察中',
      decision: 'stale',
      reasons: ['signal_stale'],
    }
  }

  if (signals.lifecycleAction === 'veto') {
    return { status: '已退出', decision: 'exit', reasons: ['lifecycle_veto'] }
  }

  if (signals.macdCross === 'death' && (signals.directionSignal !== 'buy' || signals.zeroCrossSignal === 'sell')) {
    const reasons = ['macd_death_cross']
    if (signals.directionSignal !== 'buy') reasons.push('direction_weak')
    if (signals.zeroCrossSignal === 'sell') reasons.push('zero_cross_sell')
    return { status: '已退出', decision: 'exit', reasons }
  }

  if (signals.finalSignal === 'sell' && (signals.finalConfidence ?? 0) >= t.exitFinalSell) {
    return { status: '已退出', decision: 'exit', reasons: ['final_sell_signal'] }
  }

  const wasIntervened = previous?.status === '已介入'
  if (wasIntervened) {
    if (signals.finalSignal === 'hold' && (signals.finalConfidence ?? 0) < t.observeFinalMin) {
      return { status: '观察中', decision: 'downgrade', reasons: ['intervened_consensus_weakened'] }
    }
    if (
      signals.buyVotes <= 1 &&
      signals.jumpConfidence != null &&
      signals.jumpConfidence < t.downgradeJumpMin
    ) {
      return { status: '观察中', decision: 'downgrade', reasons: ['intervened_votes_and_jump_low'] }
    }
    return {
      status: '已介入',
      decision: 'stale',
      reasons: signals.riskFlags.length ? ['intervened_keep_with_risk'] : ['intervened_keep'],
    }
  }

  if (
    signals.buyVotes <= 1 &&
    signals.jumpConfidence != null &&
    signals.jumpConfidence < t.downgradeJumpMin
  ) {
    return { status: '已退出', decision: 'exit', reasons: ['low_votes_and_jump'] }
  }

  if ((signals.finalConfidence ?? 100) < t.downgradeFinalMin) {
    return { status: '观察中', decision: 'downgrade', reasons: ['consensus_not_enough'] }
  }

  if ((signals.jumpConfidence ?? 100) < t.recallJumpMin) {
    return { status: '观察中', decision: 'downgrade', reasons: ['jump_confidence_low'] }
  }

  if (signals.momentumSyncBroken) {
    return { status: '观察中', decision: 'downgrade', reasons: ['momentum_sync_broken'] }
  }

  const trendBuyCount = [
    signals.directionSignal,
    signals.accelerationSignal,
    signals.zeroCrossSignal,
  ].filter((item) => item === 'buy').length
  const hasFinalInput = signals.finalSignal != null
  const finalSignalPass = hasFinalInput ? signals.finalSignal === 'buy' : true
  const finalConfidencePass = hasFinalInput
    ? (signals.finalConfidence ?? 0) >= t.observeFinalMin
    : true
  const jumpDirectionPass =
    signals.jumpDirection == null ||
    signals.jumpDirection === 'buy' ||
    (signals.jumpDirection === 'hold' && (signals.jumpConfidence ?? 0) >= t.jumpHoldMinConfidence)
  const strongConsensus =
    finalSignalPass &&
    finalConfidencePass &&
    signals.buyVotes >= t.buyVotesMin &&
    jumpDirectionPass &&
    (signals.jumpConfidence ?? 0) >= t.recallJumpMin &&
    trendBuyCount >= 2 &&
    !signals.riskFlags.includes('candidate_hard_blocked') &&
    signals.macdCross !== 'death'

  if (!strongConsensus) {
    return { status: '观察中', decision: 'watch', reasons: ['consensus_not_enough'] }
  }

  if (hasDoubleRisk(signals)) {
    return { status: '观察中', decision: 'downgrade', reasons: ['double_risk'] }
  }

  const ready =
    (signals.finalConfidence ?? 0) >= t.readyFinalMin &&
    (signals.jumpConfidence ?? 0) >= t.readyJumpMin &&
    (signals.macdCross === 'golden' || (signals.zeroCrossSignal === 'buy' && signals.directionSignal === 'buy'))

  if (ready) {
    return {
      status: '准备介入',
      decision: 'enter',
      reasons: signals.macdCross === 'golden'
        ? ['strong_consensus', 'macd_golden_cross']
        : ['strong_consensus'],
    }
  }

  if (
    signals.directionSignal === 'buy' &&
    signals.macdCross === 'golden' &&
    signals.accelerationSignal === 'buy' &&
    signals.zeroCrossSignal === 'buy'
  ) {
    return { status: '观察买点', decision: 'enter', reasons: ['strong_consensus', 'signal_resonance'] }
  }

  return { status: '观察买点', decision: 'enter', reasons: ['strong_consensus'] }
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
  const t = input.thresholds ?? DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.tradingPool
  const previousRows = buildPreviousRowMap(input.previousRows)

  const thesisCodes = new Set<string>()
  const mergedCandidates: TradingPoolCandidateLike[] = []

  for (const candidate of input.candidates || []) {
    const code = normalizeCode(candidate.code)
    if (!code) continue
    thesisCodes.add(code)
    mergedCandidates.push(candidate)
  }

  if (input.liveStocks) {
    for (const stock of input.liveStocks) {
      const code = normalizeCode(stock.code)
      if (!code || thesisCodes.has(code)) continue
      mergedCandidates.push({
        ...stock,
        tradingPoolSource: 'live_projection' as TradingPoolSource,
      })
    }
  }

  const rows: TradingPoolAnalysisRow[] = []
  let staleCount = 0
  let exitedCount = 0

  for (const candidate of mergedCandidates) {
    const code = normalizeCode(candidate.code)
    if (!code) continue

    const signals = readTradingSignals(candidate, t)
    const previous = previousRows.get(code) || null
    const decisionResult = decideTradingPoolStatus(signals, previous, t)
    const sourceReason = signals.source === 'jump_blocked_resonance' ? ['jump_blocked_resonance'] : []
    const resolvedSignals = {
      ...signals,
      dataQuality:
        decisionResult.decision === 'stale' ? 'stale' : signals.dataQuality,
    } as TradingPoolSignalSnapshot
    const trendBuyCount = [
      signals.directionSignal,
      signals.accelerationSignal,
      signals.zeroCrossSignal,
    ].filter((item) => item === 'buy').length
    const hasFinalInput = signals.finalSignal != null
    const consensusBreakdown = {
      finalSignalPass: hasFinalInput ? signals.finalSignal === 'buy' : true,
      finalConfidencePass: hasFinalInput
        ? (signals.finalConfidence ?? 0) >= t.observeFinalMin
        : true,
      buyVotesPass: signals.buyVotes >= t.buyVotesMin,
      jumpDirectionPass:
        signals.jumpDirection == null ||
        signals.jumpDirection === 'buy' ||
        (signals.jumpDirection === 'hold' && (signals.jumpConfidence ?? 0) >= t.jumpHoldMinConfidence),
      jumpConfidencePass: (signals.jumpConfidence ?? 0) >= t.recallJumpMin,
      trendBuyCountPass: trendBuyCount >= 2,
      noHardBlock: !signals.riskFlags.includes('candidate_hard_blocked'),
      noMacdDeath: signals.macdCross !== 'death',
      passedCount: 0,
    }
    consensusBreakdown.passedCount = [
      consensusBreakdown.finalSignalPass,
      consensusBreakdown.finalConfidencePass,
      consensusBreakdown.buyVotesPass,
      consensusBreakdown.jumpDirectionPass,
      consensusBreakdown.jumpConfidencePass,
      consensusBreakdown.trendBuyCountPass,
      consensusBreakdown.noHardBlock,
      consensusBreakdown.noMacdDeath,
    ].filter(Boolean).length

    const row: TradingPoolAnalysisRow = {
      code,
      name: candidate.name ? String(candidate.name) : undefined,
      status: decisionResult.status,
      decision: decisionResult.decision,
      reasons: [...decisionResult.reasons, ...sourceReason],
      signalSnapshot: resolvedSignals,
      consensusBreakdown,
    }

    rows.push(row)
    if (row.decision === 'stale') staleCount += 1
    if (row.decision === 'exit') exitedCount += 1
  }

  return { rows, staleCount, exitedCount }
}
