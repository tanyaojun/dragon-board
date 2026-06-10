import type {
  RankTrendLiveChangeGateConfig,
  RankTrendLiveStrategyConfig,
  RankTrendLiveStrategyMode,
} from '@/types/rankTrendLiveStrategy'

export const RANK_TREND_LIVE_STRATEGY_CONFIG_STORAGE_KEY =
  'dragon-board.rankTrend.liveStrategyConfig.v1'

export const RANK_TREND_LIVE_STRATEGY_CONFIG_VERSION = 'live-v5.1.0'

export const RANK_TREND_LIVE_STRATEGY_PRESETS: Record<
  RankTrendLiveStrategyMode,
  RankTrendLiveStrategyConfig
> = {
  recall_first: {
    version: RANK_TREND_LIVE_STRATEGY_CONFIG_VERSION,
    mode: 'recall_first',
    minJumpConfidence: 80,
    allowDegradedSample: true,
    requireCandidateTier: false,
    allowedCandidateTiers: ['A_MAIN', 'B_IGNITION'],
    requireTierBMidAndZeroCross: false,
    tierBMidMin: 20,
    accelerationMin: 10,
    accDeltaMin: 8,
    changeGate: { mode: 'warn', maxEntryChangePct: 6 },
    limitUpPolicy: 'quote_first',
  },
  balanced: {
    version: RANK_TREND_LIVE_STRATEGY_CONFIG_VERSION,
    mode: 'balanced',
    minJumpConfidence: 85,
    allowDegradedSample: true,
    requireCandidateTier: false,
    allowedCandidateTiers: ['A_MAIN', 'B_IGNITION'],
    requireTierBMidAndZeroCross: false,
    tierBMidMin: 20,
    accelerationMin: 10,
    accDeltaMin: 8,
    changeGate: { mode: 'warn', maxEntryChangePct: 6 },
    limitUpPolicy: 'quote_first',
  },
  strict_execution: {
    version: RANK_TREND_LIVE_STRATEGY_CONFIG_VERSION,
    mode: 'strict_execution',
    minJumpConfidence: 90,
    allowDegradedSample: false,
    requireCandidateTier: true,
    allowedCandidateTiers: ['A_MAIN', 'B_IGNITION'],
    requireTierBMidAndZeroCross: true,
    tierBMidMin: 20,
    accelerationMin: 10,
    accDeltaMin: 8,
    changeGate: { mode: 'block', maxEntryChangePct: 6 },
    limitUpPolicy: 'quote_first',
  },
}

export const DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG =
  RANK_TREND_LIVE_STRATEGY_PRESETS.balanced

function normalizeNumber(value: unknown, fallback: number, min: number, max: number): number {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return fallback
  return Math.min(max, Math.max(min, numeric))
}

function normalizeMode(value: unknown): RankTrendLiveStrategyMode {
  return value === 'recall_first' || value === 'strict_execution' ? value : 'balanced'
}

function normalizeBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function normalizeCandidateTiers(
  value: unknown,
  fallback: RankTrendLiveStrategyConfig['allowedCandidateTiers'],
): RankTrendLiveStrategyConfig['allowedCandidateTiers'] {
  if (!Array.isArray(value)) return [...fallback]
  const allowed = new Set(['A_MAIN', 'B_IGNITION', 'N_NEUTRAL'])
  const tiers = value.filter(
    (tier): tier is RankTrendLiveStrategyConfig['allowedCandidateTiers'][number] =>
      typeof tier === 'string' && allowed.has(tier),
  )
  return tiers.length ? tiers : [...fallback]
}

export function normalizeRankTrendLiveStrategyConfig(
  patch: Partial<RankTrendLiveStrategyConfig> = {},
): RankTrendLiveStrategyConfig {
  const mode = normalizeMode(patch.mode)
  const base = RANK_TREND_LIVE_STRATEGY_PRESETS[mode]
  const changeGate: Partial<RankTrendLiveChangeGateConfig> = patch.changeGate || {}

  return {
    ...base,
    ...patch,
    version: RANK_TREND_LIVE_STRATEGY_CONFIG_VERSION,
    mode,
    minJumpConfidence: normalizeNumber(patch.minJumpConfidence, base.minJumpConfidence, 0, 100),
    tierBMidMin: normalizeNumber(patch.tierBMidMin, base.tierBMidMin, 0, 100),
    accelerationMin: normalizeNumber(patch.accelerationMin, base.accelerationMin, 0, 100),
    accDeltaMin: normalizeNumber(patch.accDeltaMin, base.accDeltaMin, 0, 100),
    allowDegradedSample: normalizeBoolean(patch.allowDegradedSample, base.allowDegradedSample),
    requireCandidateTier: normalizeBoolean(patch.requireCandidateTier, base.requireCandidateTier),
    requireTierBMidAndZeroCross: normalizeBoolean(
      patch.requireTierBMidAndZeroCross,
      base.requireTierBMidAndZeroCross,
    ),
    allowedCandidateTiers: normalizeCandidateTiers(
      patch.allowedCandidateTiers,
      base.allowedCandidateTiers,
    ),
    changeGate: {
      mode:
        changeGate.mode === 'off' || changeGate.mode === 'block' || changeGate.mode === 'warn'
          ? changeGate.mode
          : base.changeGate.mode,
      maxEntryChangePct:
        changeGate.maxEntryChangePct === null
          ? null
          : normalizeNumber(
              changeGate.maxEntryChangePct,
              base.changeGate.maxEntryChangePct ?? 6,
              0,
              30,
            ),
    },
    limitUpPolicy: 'quote_first',
  }
}
