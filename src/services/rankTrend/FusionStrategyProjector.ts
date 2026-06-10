import type { CandidateExecutionOverlayByCode } from '@/services/candidate/types'
import type {
  FusionSnapshotType,
  FusionStrategyProjection,
  FusionStrategyState,
} from '@/types/fusionStrategyProjection'
import type { CandidateTier, LifecycleDecisionAction } from './types'
import { evaluateV5FusionEntry, type V5FusionEntryResult } from './v5FusionExecutionContract'

type StrategyLifecycleInput = {
  triggered?: boolean
  hasOpenPosition?: boolean
  exitWatch?: boolean
  closed?: boolean
  triggerAt?: string
  entryAt?: string
  exitAt?: string
  holdingBars?: number
  slotIndex?: number
  maxPositions?: number
  tPlusOneUnlocked?: boolean
  entryReason?: string
  exitReason?: string
  strategyEntryPrice?: number
  strategyExitPrice?: number
  strategyReturnPct?: number
}

type BuildProjectionInput = {
  stock: Record<string, any>
  snapshotType: FusionSnapshotType
  tradingDate: string
  snapshotId: string
  frameTime: string
  projectionSource?: 'live' | 'backtest'
  strategyLifecycle?: StrategyLifecycleInput | null
  executionOverlay?: FusionStrategyProjection['executionOverlay']
}

type BuildProjectionsOptions = {
  executionOverlayByCode?: CandidateExecutionOverlayByCode
  snapshotType?: FusionSnapshotType
}

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function normalizeCandidateTier(entry: V5FusionEntryResult): CandidateTier {
  const tier = entry.candidateTier
  if (
    tier === 'A_MAIN' ||
    tier === 'B_IGNITION' ||
    tier === 'C_CROWDED' ||
    tier === 'D_EXIT_RISK'
  ) {
    return tier
  }
  return 'N_NEUTRAL'
}

function normalizeLifecycleAction(stock: Record<string, any>): LifecycleDecisionAction {
  const action = String(stock?.rankTrend?.cycle?.decision?.action || '')
  if (action === 'allow' || action === 'caution' || action === 'veto' || action === 'exit_watch') {
    return action
  }
  return 'caution'
}

function normalizeSnapshotType(
  stock: Record<string, any>,
  fallback: FusionSnapshotType,
): FusionSnapshotType {
  return stock?.rankTrend?.meta?.sampleQuality?.snapshotType === 'quarter_hour'
    ? 'quarter_hour'
    : fallback
}

function buildFrameTime(tradingDate: string, slotTime: string): string {
  if (!tradingDate) return ''
  if (!slotTime) return `${tradingDate}T00:00:00+08:00`
  return `${tradingDate}T${slotTime}:00+08:00`
}

function buildSnapshotId(
  snapshotType: FusionSnapshotType,
  tradingDate: string,
  slotTime: string,
  stockCode: string,
): string {
  if (tradingDate && slotTime) {
    return `${snapshotType}:${tradingDate}:${slotTime}`
  }
  return `${snapshotType}:${tradingDate || 'unknown'}:${stockCode || 'stock'}`
}

function resolveStrategyState(
  entry: V5FusionEntryResult,
  lifecycle: StrategyLifecycleInput | null | undefined,
): FusionStrategyState {
  const triggered = lifecycle?.triggered ?? entry.accepted

  let strategyState: FusionStrategyState = 'idle'
  if (triggered) strategyState = 'triggered_wait_entry'
  if (lifecycle?.hasOpenPosition) strategyState = 'active_holding'
  if (lifecycle?.exitWatch && lifecycle?.hasOpenPosition) strategyState = 'exit_signaled'
  if (lifecycle?.closed) strategyState = 'closed'
  return strategyState
}

export function buildFusionStrategyProjection(input: BuildProjectionInput): FusionStrategyProjection {
  const lifecycle = input.strategyLifecycle
  const stockCode = normalizeCode(input.stock.code)
  const entry = evaluateV5FusionEntry(input.stock)
  const strategyState = resolveStrategyState(entry, lifecycle)

  return {
    stockCode,
    stockName: String(input.stock.name || stockCode || ''),
    strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion',
    snapshotType: input.snapshotType,
    tradingDate: input.tradingDate,
    snapshotId: input.snapshotId,
    frameTime: input.frameTime,
    projectionSource: input.projectionSource || 'live',
    strategyState,
    candidateTier: normalizeCandidateTier(entry),
    lifecycleAction: normalizeLifecycleAction(input.stock),
    triggerAt: strategyState !== 'idle' ? lifecycle?.triggerAt || input.frameTime : undefined,
    strategyEntryAt: lifecycle?.entryAt,
    strategyExitAt: lifecycle?.exitAt,
    holdingBars: lifecycle?.holdingBars,
    slotIndex: lifecycle?.slotIndex,
    maxPositions: lifecycle?.maxPositions,
    tPlusOneUnlocked: lifecycle?.tPlusOneUnlocked,
    entryReason: lifecycle?.entryReason,
    exitReason: lifecycle?.exitReason,
    strategyEntryPrice: lifecycle?.strategyEntryPrice,
    strategyExitPrice: lifecycle?.strategyExitPrice,
    strategyReturnPct: lifecycle?.strategyReturnPct,
    executionOverlay: input.executionOverlay || null,
  }
}

export function buildFusionStrategyProjections(
  stocks: Array<Record<string, any>>,
  options: BuildProjectionsOptions = {},
): FusionStrategyProjection[] {
  const fallbackSnapshotType = options.snapshotType || 'half_hour'

  const liveNow = new Date()
  const liveDateFallback = liveNow.toISOString().slice(0, 10)
  const liveTimeFallback = liveNow.toTimeString().slice(0, 5)

  return stocks.map((stock) => {
    const stockCode = normalizeCode(stock.code)
    const tradingDate =
      String(stock?.rankTrend?.meta?.sampleQuality?.latestTradingDate || '') || liveDateFallback
    const slotTime =
      String(stock?.rankTrend?.meta?.sampleQuality?.latestSlotTime || '') || liveTimeFallback
    const snapshotType = normalizeSnapshotType(stock, fallbackSnapshotType)

    return buildFusionStrategyProjection({
      stock,
      snapshotType,
      tradingDate,
      snapshotId: buildSnapshotId(snapshotType, tradingDate, slotTime, stockCode),
      frameTime: buildFrameTime(tradingDate, slotTime),
      strategyLifecycle: stock?.rankTrend?.strategyLifecycle || stock?.rankTrend?.lifecycle || null,
      executionOverlay: options.executionOverlayByCode?.[stockCode] || null,
    })
  })
}
