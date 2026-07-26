import type { FusionStrategyProjection, FusionStrategyState } from '@/types/fusionStrategyProjection'

export interface ResonanceObserveInput {
  resonance?: {
    status?: string | null
    direction?: string | null
    score?: number | null
  } | null
}

export function isResonanceObserve(input: ResonanceObserveInput): boolean {
  return (
    input.resonance?.status === 'ok' &&
    input.resonance.direction === 'buy' &&
    (input.resonance.score ?? 0) >= 85
  )
}

type CandidatePoolStockFields = {
  code: string
  candidatePoolStatus?: FusionStrategyState
  candidatePoolLabel?: string
  candidatePoolLiveDecisionLabel?: string
  candidatePoolLiveDecisionSummary?: string
  candidatePoolProjection?: FusionStrategyProjection | null
  candidatePoolEntryId?: string
  candidatePoolSource?: string
  candidatePoolUpdatedAt?: string
  candidateResonanceObserve?: boolean
}

const STRATEGY_STATE_LABELS: Record<FusionStrategyState, string> = {
  idle: '未触发',
  triggered_wait_entry: '待入场',
  active_holding: '已入场',
  exit_signaled: '策略退出观察',
  closed: '策略已关闭',
}

function formatStrategyStateLabel(state: FusionStrategyState, hasCandidateEntry: boolean): string {
  if (state === 'idle' && hasCandidateEntry) return '观察中'
  return STRATEGY_STATE_LABELS[state]
}

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function buildProjectionMap(projections: FusionStrategyProjection[]): Map<string, FusionStrategyProjection> {
  const map = new Map<string, FusionStrategyProjection>()
  for (const projection of projections) {
    const code = normalizeCode(projection.stockCode)
    if (!code) continue
    map.set(code, projection)
  }
  return map
}

export function projectCandidatePoolStatus<T extends CandidatePoolStockFields>(
  stocks: T[],
  projections: FusionStrategyProjection[],
): T[] {
  const projectionByCode = buildProjectionMap(projections)

  for (const stock of stocks) {
    const projection = projectionByCode.get(normalizeCode(stock.code)) || null
    const strategyState = projection?.strategyState || 'idle'
    const hasCandidateEntry = !!projection?.executionOverlay?.entryId

    stock.candidatePoolStatus = strategyState
    stock.candidatePoolLabel = formatStrategyStateLabel(strategyState, hasCandidateEntry)
    stock.candidatePoolLiveDecisionLabel = projection?.entryDecision?.label || ''
    stock.candidatePoolLiveDecisionSummary = projection?.entryDecision?.summary || ''
    stock.candidatePoolProjection = projection
    stock.candidatePoolEntryId = projection?.executionOverlay?.entryId || ''
    stock.candidatePoolSource = projection?.strategyName || ''
    stock.candidatePoolUpdatedAt = projection?.frameTime || ''

    const rankTrend = (stock as Record<string, any>).rankTrend
    const resonanceEligible = isResonanceObserve({
      resonance: rankTrend?.resonance,
    })
    ;(stock as Record<string, any>).candidateResonanceObserve =
      resonanceEligible && !projection?.entryDecision?.accepted
  }

  return stocks
}

export function applyCandidatePoolProjections<T extends CandidatePoolStockFields>(
  stocks: T[],
  projections: FusionStrategyProjection[],
): T[] {
  return projectCandidatePoolStatus(stocks, projections)
}
