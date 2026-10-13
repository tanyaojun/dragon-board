/**
 * L1 事件规则默认值：与 tools/YiDongJingLing/Events/L1EventRules.cs 完全对齐。
 * 批量阈值可直接改本文件（与 C# 侧同步调整），运行时可被两层开关设置覆盖。
 */

export interface L1EventRules {
  nearLimitDistancePct: number
  riseTiers: number[]
  dropTiers: number[]
  amountTiers: number[]
  fastRise30SecPct: number
  fastRise60SecPct: number
  fastRise300SecPct: number
  fastDrop30SecPct: number
  fastDrop60SecPct: number
  fastDrop300SecPct: number
  pressureRatio: number
  spreadPct: number
  largeOrderAmount: number
  openGapPct: number
  longBodyPct: number
  sealWeakRatio: number
  sealIncreaseRatio: number
  upcomingOpenSealWeakRatio: number
  upcomingOpenMinSealAmount: number
  upcomingOpenMinSealVolume: number
  upcomingOpenWindowMs: number
  volumeAccelerationRatio: number
  newStockMinSurgePct: number
  newStockOpenDropPct: number
  newStockResealDrawdownPct: number
  speedBaselineToleranceMs: number
}

export const DEFAULT_L1_EVENT_RULES: L1EventRules = {
  nearLimitDistancePct: 1.0,
  riseTiers: [3, 5, 7, 9],
  dropTiers: [3, 5, 7, 9],
  amountTiers: [100_000_000, 300_000_000, 500_000_000, 1_000_000_000],
  fastRise30SecPct: 2,
  fastRise60SecPct: 3,
  fastRise300SecPct: 5,
  fastDrop30SecPct: -2,
  fastDrop60SecPct: -3,
  fastDrop300SecPct: -5,
  pressureRatio: 2.5,
  spreadPct: 1.0,
  largeOrderAmount: 10_000_000,
  openGapPct: 1,
  longBodyPct: 4,
  sealWeakRatio: 0.5,
  sealIncreaseRatio: 1.5,
  upcomingOpenSealWeakRatio: 0.35,
  upcomingOpenMinSealAmount: 5_000_000,
  upcomingOpenMinSealVolume: 10_000,
  upcomingOpenWindowMs: 10_000,
  volumeAccelerationRatio: 2.0,
  newStockMinSurgePct: 10,
  newStockOpenDropPct: 5,
  newStockResealDrawdownPct: 1,
  speedBaselineToleranceMs: 10_000,
}

/** 板块异动阈值，语义对齐 SectorEventRules.cs。 */
export interface SectorEventRules {
  minRiseCount: number
  riseRatio: number
  rushMinAvgPct: number
  minFallCount: number
  fallRatio: number
  diveMaxAvgPct: number
  waveThreshold: number
  waveWindowMs: number
  cooldownMs: number
}

export const DEFAULT_SECTOR_EVENT_RULES: SectorEventRules = {
  minRiseCount: 3,
  riseRatio: 0.6,
  rushMinAvgPct: 1.0,
  minFallCount: 3,
  fallRatio: 0.6,
  diveMaxAvgPct: -1.0,
  waveThreshold: 2,
  waveWindowMs: 600_000,
  cooldownMs: 600_000,
}

/** 去重冷却（毫秒），对齐 EventDeduper：状态变化 30s / 噪声 180s。 */
export const STATE_CHANGE_COOLDOWN_MS = 30_000
export const NOISE_COOLDOWN_MS = 180_000
