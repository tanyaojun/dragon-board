import type {
  RankTrendLiveChangeGateConfig,
  RankTrendLiveStrategyConfig,
  RankTrendLiveStrategyMode,
  TradingPoolThresholds,
} from '@/types/rankTrendLiveStrategy'

export const RANK_TREND_LIVE_STRATEGY_CONFIG_STORAGE_KEY =
  'dragon-board.rankTrend.liveStrategyConfig.v1'

export const RANK_TREND_LIVE_STRATEGY_CONFIG_VERSION = 'live-v5.1.0'

const TRADING_POOL_RECALL_FIRST: TradingPoolThresholds = {
  recallJumpMin: 75,
  readyJumpMin: 80,
  observeFinalMin: 80,
  readyFinalMin: 85,
  buyVotesMin: 2,
  downgradeJumpMin: 70,
  downgradeFinalMin: 70,
  exitFinalSell: 80,
  jumpHoldMinConfidence: 50,
}

const TRADING_POOL_BALANCED: TradingPoolThresholds = {
  recallJumpMin: 80,
  readyJumpMin: 85,
  observeFinalMin: 85,
  readyFinalMin: 88,
  buyVotesMin: 3,
  downgradeJumpMin: 75,
  downgradeFinalMin: 75,
  exitFinalSell: 80,
  jumpHoldMinConfidence: 60,
}

const TRADING_POOL_STRICT: TradingPoolThresholds = {
  recallJumpMin: 85,
  readyJumpMin: 90,
  observeFinalMin: 88,
  readyFinalMin: 92,
  buyVotesMin: 3,
  downgradeJumpMin: 80,
  downgradeFinalMin: 80,
  exitFinalSell: 75,
  jumpHoldMinConfidence: 70,
}

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
    tradingPool: TRADING_POOL_RECALL_FIRST,
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
    tradingPool: TRADING_POOL_BALANCED,
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
    tradingPool: TRADING_POOL_STRICT,
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

function normalizeTradingPool(
  patch: Partial<TradingPoolThresholds> | undefined,
  base: TradingPoolThresholds,
): TradingPoolThresholds {
  return {
    recallJumpMin: normalizeNumber(patch?.recallJumpMin, base.recallJumpMin, 0, 100),
    readyJumpMin: normalizeNumber(patch?.readyJumpMin, base.readyJumpMin, 0, 100),
    observeFinalMin: normalizeNumber(patch?.observeFinalMin, base.observeFinalMin, 0, 100),
    readyFinalMin: normalizeNumber(patch?.readyFinalMin, base.readyFinalMin, 0, 100),
    buyVotesMin: normalizeNumber(patch?.buyVotesMin, base.buyVotesMin, 0, 4),
    downgradeJumpMin: normalizeNumber(patch?.downgradeJumpMin, base.downgradeJumpMin, 0, 100),
    downgradeFinalMin: normalizeNumber(patch?.downgradeFinalMin, base.downgradeFinalMin, 0, 100),
    exitFinalSell: normalizeNumber(patch?.exitFinalSell, base.exitFinalSell, 0, 100),
    jumpHoldMinConfidence: normalizeNumber(
      patch?.jumpHoldMinConfidence,
      base.jumpHoldMinConfidence,
      0,
      100,
    ),
  }
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
    tradingPool: normalizeTradingPool(patch.tradingPool, base.tradingPool),
  }
}
