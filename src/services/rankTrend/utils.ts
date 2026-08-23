export function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min
  return Math.max(min, Math.min(max, value))
}

export function average(values: number[]): number {
  if (!Array.isArray(values) || values.length === 0) return 0
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

/** 技术结构稳定观察窗口（Python golden 链的 minComputableBars ≤ stableBars） */
export function getTechnicalMinSamples(config: { macdSlow: number; momentumPeriods: number[] }): number {
  const slow = Math.floor(Number(config.macdSlow) || 0)
  const momentumPeriods = Array.isArray(config.momentumPeriods) ? config.momentumPeriods : []
  const maxMomentumPeriod =
    momentumPeriods.length > 0
      ? Math.max(...momentumPeriods.map((value) => Math.floor(Number(value) || 0)))
      : 0
  return Math.max(2, slow, maxMomentumPeriod + 1, 30)
}

/** 各特征的最小稳定观察窗口（minComputableBars ≤ stableBars） */
export const STABLE_BARS = {
  macd: 30,
  momentum: 50,
  zeroCross: 8,
} as const

export function getMaxStableBars(): number {
  return Math.max(STABLE_BARS.macd, STABLE_BARS.momentum, STABLE_BARS.zeroCross)
}
