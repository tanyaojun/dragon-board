export function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min
  return Math.max(min, Math.min(max, value))
}

export function average(values: number[]): number {
  if (!Array.isArray(values) || values.length === 0) return 0
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

export function normalizeSigned(
  value: number,
  positiveScale: number,
  negativeScale: number,
): number {
  if (!Number.isFinite(value)) return 0
  const scale =
    value >= 0
      ? Math.max(1e-6, Math.abs(positiveScale))
      : Math.max(1e-6, Math.abs(negativeScale))
  return clamp(Math.tanh(value / scale), -1, 1)
}

export function calculateSignalConfidence(rawScore: number, agreementBonus = 0): number {
  return clamp(50 + Math.abs(rawScore) * 40 + agreementBonus, 50, 90)
}

export function calculateWeightedShare(
  scores: number[],
  weights: number[],
  predicate: (score: number, index: number) => boolean,
): number {
  let numerator = 0
  let denominator = 0
  for (let i = 0; i < scores.length; i++) {
    const weight = Number(weights[i] ?? 0)
    if (!Number.isFinite(weight) || weight <= 0) continue
    denominator += weight
    if (predicate(scores[i], i)) numerator += weight
  }
  return denominator > 0 ? numerator / denominator : 0
}

export function getMacdMinSamples(config: { macdSlow: number }): number {
  const slow = Math.floor(Number(config.macdSlow) || 0)
  return Math.max(2, slow)
}

/** 动量特征的最小可计算窗口：需覆盖最长动量周期再加当前对比点 */
export function getMomentumMinSamples(config: { momentumPeriods: number[] }): number {
  const momentumPeriods = Array.isArray(config.momentumPeriods) ? config.momentumPeriods : []
  const maxMomentumPeriod =
    momentumPeriods.length > 0
      ? Math.max(...momentumPeriods.map((value) => Math.floor(Number(value) || 0)))
      : 0
  return Math.max(2, maxMomentumPeriod + 1)
}

/**
 * 技术信号的最小可计算窗口（minComputableBars）：
 * bars 达到该值时必须产出 MACD/动量/零线交叉结果。
 * 与稳定观察窗口 getTechnicalMinSamples 分开，稳定窗口只影响质量标记，不阻断计算。
 */
export function getTechnicalMinComputableSamples(config: {
  macdSlow: number
  momentumPeriods: number[]
}): number {
  return Math.max(getMacdMinSamples(config), getMomentumMinSamples(config))
}

/** 技术结构稳定观察窗口（minComputableBars ≤ stableBars）：未达到时结果降级，但必须仍可计算 */
export function getTechnicalMinSamples(config: {
  macdSlow: number
  momentumPeriods: number[]
}): number {
  return Math.max(getTechnicalMinComputableSamples(config), 30)
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
