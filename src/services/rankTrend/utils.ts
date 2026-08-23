export function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min
  return Math.max(min, Math.min(max, value))
}

/**
 * 量价输入指纹（2026-08-23 修复①：当前帧标识稳定化）。
 *
 * 仅取影响量价/四维分档的输入字段（change/volumeRatio/zlje/zljzb），做确定性稳定哈希：
 * - 相同输入 → 相同指纹 → 后端 analyze 缓存命中 → 量价分不随刷新漂移；
 * - 盘中实时输入变化 → 指纹变化 → 缓存错过 → 量价分随实时刷新；
 * - 排序后哈希保证字段顺序无关（同股不同遍历序也稳定）。
 */
export function buildVpInputFingerprint(
  stocks: Array<{
    code?: unknown
    change?: unknown
    volumeRatio?: unknown
    zlje?: unknown
    zljzb?: unknown
  }>,
): string {
  if (!Array.isArray(stocks) || stocks.length === 0) return 'empty'
  const inputs = stocks
    .map((s) => [
      String(s?.code ?? ''),
      Number(s?.change ?? 0),
      Number(s?.volumeRatio ?? 0),
      Number(s?.zlje ?? 0),
      Number(s?.zljzb ?? 0),
    ])
    .sort((a, b) => String(a[0]).localeCompare(String(b[0])))
  // 确定性 djb2 哈希（无需 crypto 依赖，浏览器/Node 一致）
  const payload = JSON.stringify(inputs)
  let hash = 5381
  for (let index = 0; index < payload.length; index += 1) {
    hash = ((hash << 5) + hash + payload.charCodeAt(index)) >>> 0
  }
  return hash.toString(36)
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
