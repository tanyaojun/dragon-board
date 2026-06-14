import type {
  TradingPoolAnalysisResult,
  TradingPoolAnalysisRow,
  TradingPoolDecision,
  TradingPoolSignalSnapshot,
  TradingPoolStatus,
} from './types'

type TradingPoolCandidateLike = Record<string, any>

interface TradingPoolInput {
  candidates: TradingPoolCandidateLike[]
  previousRows?: Array<Partial<TradingPoolAnalysisRow> & { code: string }>
}

interface TradingPoolDecisionResult {
  status: TradingPoolStatus
  decision: TradingPoolDecision
  reasons: string[]
}

const HARD_EXIT_REASONS = ['macd_death_cross', 'direction_weak', 'zero_cross_sell']

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function toOptionalNumber(value: unknown): number | null {
  if (value == null || value === '') return null
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

function hasOwnValue(source: Record<string, any> | null | undefined, key: string): boolean {
  return !!source && Object.prototype.hasOwnProperty.call(source, key)
}

function readTradingSignals(stock: TradingPoolCandidateLike): TradingPoolSignalSnapshot {
  const hasRankTrend = hasOwnValue(stock, 'rankTrend')
  const rankTrend = hasRankTrend ? stock.rankTrend : null
  return {
    directionSignal: rankTrend?.technical?.signals?.direction?.signal ?? stock.directionSignal ?? null,
    jumpConfidence: toOptionalNumber(rankTrend?.jump?.confidence ?? stock.jumpConfidence),
    macdCross: rankTrend?.technical?.macd?.cross ?? stock.macdCross ?? null,
    accelerationSignal:
      rankTrend?.technical?.signals?.acceleration?.signal ?? stock.accelerationSignal ?? null,
    zeroCrossSignal: rankTrend?.technical?.signals?.zeroCross?.signal ?? stock.crossSignal ?? null,
    momentumSyncBroken: Boolean(rankTrend?.technical?.momentumProfile?.syncBroken),
    lifecycleAction: rankTrend?.cycle?.decision?.action ?? stock.lifecycleAction ?? null,
    dataQuality: hasRankTrend ? (rankTrend != null ? 'fresh' : 'stale') : 'missing',
  }
}

function hasFreshSignals(signals: TradingPoolSignalSnapshot): boolean {
  return signals.dataQuality === 'fresh'
}

function decideTradingPoolStatus(
  signals: TradingPoolSignalSnapshot,
  previous?: Partial<TradingPoolAnalysisRow> | null,
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

  const reasons: string[] = []
  if (signals.macdCross === 'death') reasons.push('macd_death_cross')
  if (signals.directionSignal !== 'buy') reasons.push('direction_weak')
  if (signals.zeroCrossSignal === 'sell') reasons.push('zero_cross_sell')

  const hardExitCount = reasons.filter((reason) => HARD_EXIT_REASONS.includes(reason)).length
  if (signals.macdCross === 'death' && hardExitCount >= 2) {
    return { status: '已退出', decision: 'exit', reasons }
  }

  if ((signals.jumpConfidence ?? 0) < 0.8) {
    return { status: '观察中', decision: 'downgrade', reasons: ['jump_confidence_low'] }
  }

  if (signals.momentumSyncBroken) {
    return { status: '观察中', decision: 'downgrade', reasons: ['momentum_sync_broken'] }
  }

  if (
    signals.directionSignal === 'buy' &&
    signals.macdCross === 'golden' &&
    signals.accelerationSignal === 'buy' &&
    signals.zeroCrossSignal === 'buy'
  ) {
    return { status: '观察买点', decision: 'enter', reasons: ['signal_resonance'] }
  }

  return { status: '观察中', decision: 'watch', reasons: ['resonance_incomplete'] }
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
  const previousRows = buildPreviousRowMap(input.previousRows)
  const rows: TradingPoolAnalysisRow[] = []
  let staleCount = 0
  let exitedCount = 0

  for (const candidate of input.candidates || []) {
    const code = normalizeCode(candidate.code)
    if (!code) continue

    const signals = readTradingSignals(candidate)
    const previous = previousRows.get(code) || null
    const decisionResult = decideTradingPoolStatus(signals, previous)
    const resolvedSignals = {
      ...signals,
      dataQuality:
        decisionResult.decision === 'stale' ? 'stale' : signals.dataQuality,
    } as TradingPoolSignalSnapshot
    const row: TradingPoolAnalysisRow = {
      code,
      name: candidate.name ? String(candidate.name) : undefined,
      status: decisionResult.status,
      decision: decisionResult.decision,
      reasons: decisionResult.reasons,
      signalSnapshot: resolvedSignals,
    }

    rows.push(row)
    if (row.decision === 'stale') staleCount += 1
    if (row.decision === 'exit') exitedCount += 1
  }

  return { rows, staleCount, exitedCount }
}
