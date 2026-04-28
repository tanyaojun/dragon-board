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

export function getTechnicalMinSamples(config: {
  macdSlow: number
  momentumPeriods: number[]
}): number {
  const momentumPeriods = Array.isArray(config.momentumPeriods) ? config.momentumPeriods : []
  const maxMomentumPeriod =
    momentumPeriods.length > 0
      ? Math.max(...momentumPeriods.map((value) => Math.floor(Number(value) || 0)))
      : 0
  return Math.max(getMacdMinSamples(config), maxMomentumPeriod + 1, 30)
}
