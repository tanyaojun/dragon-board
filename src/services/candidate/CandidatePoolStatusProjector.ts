import type { FusionStrategyProjection, FusionStrategyState } from '@/types/fusionStrategyProjection'

type CandidatePoolStockFields = {
  code: string
  candidatePoolStatus?: FusionStrategyState
  candidatePoolLabel?: string
  candidatePoolProjection?: FusionStrategyProjection | null
  candidatePoolEntryId?: string
  candidatePoolSource?: string
  candidatePoolUpdatedAt?: string
}

const STRATEGY_STATE_LABELS: Record<FusionStrategyState, string> = {
  idle: '未触发',
  triggered_wait_entry: '待入场',
  active_holding: '策略持有中',
  exit_signaled: '策略退出观察',
  closed: '策略已关闭',
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

    stock.candidatePoolStatus = strategyState
    stock.candidatePoolLabel = STRATEGY_STATE_LABELS[strategyState]
    stock.candidatePoolProjection = projection
    stock.candidatePoolEntryId = projection?.executionOverlay?.entryId || ''
    stock.candidatePoolSource = projection?.strategyName || ''
    stock.candidatePoolUpdatedAt = projection?.frameTime || ''
  }

  return stocks
}

export function applyCandidatePoolProjections<T extends CandidatePoolStockFields>(
  stocks: T[],
  projections: FusionStrategyProjection[],
): T[] {
  return projectCandidatePoolStatus(stocks, projections)
}
