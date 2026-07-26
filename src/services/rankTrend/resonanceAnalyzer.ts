import type { RankSignalDirection, RankTrendResonance } from './types'

type ResonanceJump = {
  direction: RankSignalDirection
  event: 'jump' | 'none'
  events: Array<{ index: number; direction: 'surge' | 'collapse'; magnitude: number }>
}

type ResonanceInput = {
  percentiles: number[]
  sampleQuality: { status: 'ok' | 'degraded' | 'insufficient' }
  marketMedianShortChange: number
  marketSampleCount: number
  jump: ResonanceJump
  entry?: { isNew: boolean; currentAttentionPercentile: number }
}

const MIN_SERIES_BARS = 4
const MIN_MARKET_SAMPLE_COUNT = 20

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function positive(value: number): number {
  return Math.max(0, value)
}

function labelFor(score: number): RankTrendResonance['label'] {
  if (score >= 85) return '非常强'
  if (score >= 67) return '强'
  if (score >= 50) return '中等'
  if (score >= 27) return '较弱'
  return '非常弱'
}

function insufficient(reason: string, marketMedianShortChange: number): RankTrendResonance {
  return {
    status: 'insufficient',
    direction: 'hold',
    score: 0,
    label: '样本不足',
    relativeMomentum: 0,
    acceleration: 0,
    persistence: 0,
    jumpFreshness: 0,
    reversalPenalty: 0,
    historyState: 'established',
    marketMedianShortChange,
    reasons: [reason],
  }
}

export function analyzeRankResonance(input: ResonanceInput): RankTrendResonance {
  const percentiles = input.percentiles.map(Number)
  const isNewEntry = input.entry?.isNew === true
  const currentAttentionPercentile = Number(input.entry?.currentAttentionPercentile)
  if (isNewEntry) {
    if (!Number.isFinite(currentAttentionPercentile)) {
      return insufficient('新入榜关注度无效', input.marketMedianShortChange)
    }
    if (!Number.isFinite(input.marketMedianShortChange) || input.marketSampleCount < MIN_MARKET_SAMPLE_COUNT) {
      return insufficient('横截面有效样本不足', input.marketMedianShortChange)
    }
    const jumpFreshness = input.jump.events.at(-1) ? 1 : 0
    const entryStrength = clamp((currentAttentionPercentile - 50) / 25, 0, 1)
    const score = Math.round(100 * clamp(0.7 * entryStrength + 0.3 * jumpFreshness, 0, 1))
    return {
      status: 'ok',
      direction: entryStrength > 0 ? 'buy' : 'hold',
      score,
      label: labelFor(score),
      relativeMomentum: entryStrength,
      acceleration: 0,
      persistence: 0,
      jumpFreshness,
      reversalPenalty: 0,
      historyState: 'new_entry',
      marketMedianShortChange: input.marketMedianShortChange,
      reasons: [`新入榜关注度 ${Math.round(currentAttentionPercentile)}`],
    }
  }
  if (percentiles.length < MIN_SERIES_BARS || percentiles.some((value) => !Number.isFinite(value))) {
    return insufficient('排名序列不足或无效', input.marketMedianShortChange)
  }
  if (input.sampleQuality.status === 'insufficient') {
    return insufficient('快照样本不足', input.marketMedianShortChange)
  }
  if (!Number.isFinite(input.marketMedianShortChange) || input.marketSampleCount < MIN_MARKET_SAMPLE_COUNT) {
    return insufficient('横截面有效样本不足', input.marketMedianShortChange)
  }

  const lastIndex = percentiles.length - 1
  const shortStartIndex = Math.max(0, lastIndex - 3)
  const midStartIndex = Math.max(0, lastIndex - 8)
  const shortBars = lastIndex - shortStartIndex
  const midBars = lastIndex - midStartIndex
  const shortChange = percentiles[lastIndex] - percentiles[shortStartIndex]
  const midChange = percentiles[lastIndex] - percentiles[midStartIndex]
  const relativeMomentum = clamp((shortChange - input.marketMedianShortChange) / 15, -1, 1)
  const acceleration = clamp((shortChange - (midChange * shortBars) / midBars) / 15, -1, 1)

  const pathPercentiles = percentiles.slice(-8)
  const changes = pathPercentiles.slice(1).map((value, index) => value - pathPercentiles[index])
  const pathDirection = Math.sign(shortChange || midChange)
  const directionalChanges = changes.filter((value) => Math.sign(value) === pathDirection && pathDirection !== 0)
  const persistence = changes.length ? directionalChanges.length / changes.length : 0
  const directionSwitchRate = changes.length > 1
    ? changes.slice(1).filter((value, index) => Math.sign(value) !== 0 && Math.sign(changes[index]) !== 0 && Math.sign(value) !== Math.sign(changes[index])).length / (changes.length - 1)
    : 0
  const recentPeak = Math.max(...pathPercentiles)
  const percentileDrawdown = Math.max(0, recentPeak - percentiles[lastIndex])
  const reversalPenalty = clamp(0.6 * directionSwitchRate + 0.4 * percentileDrawdown / 20, 0, 1)

  const latestEvent = input.jump.events.at(-1)
  const jumpFreshness = latestEvent
    ? Math.exp(-(lastIndex - latestEvent.index) / 3)
    : 0
  const directionScore = relativeMomentum + acceleration + 0.2 * pathDirection * persistence
  const baseDirection: RankSignalDirection =
    directionScore > 0.1 ? 'buy' : directionScore < -0.1 ? 'sell' : 'hold'
  const direction = input.jump.event === 'jump' && input.jump.direction !== 'hold' && input.jump.direction !== baseDirection
    ? input.jump.direction
    : baseDirection

  const directionalMomentum = direction === 'sell' ? -relativeMomentum : relativeMomentum
  const directionalAcceleration = direction === 'sell' ? -acceleration : acceleration
  const rawScore =
    0.35 * positive(directionalMomentum) +
    0.25 * positive(directionalAcceleration) +
    0.2 * persistence +
    0.2 * jumpFreshness -
    0.2 * reversalPenalty
  const score = Math.round(100 * clamp(rawScore, 0, 1))

  return {
    status: 'ok',
    direction,
    score,
    label: labelFor(score),
    relativeMomentum,
    acceleration,
    persistence,
    jumpFreshness,
    reversalPenalty,
    historyState: 'established',
    marketMedianShortChange: input.marketMedianShortChange,
    reasons: [
      `相对动量 ${Math.round(relativeMomentum * 100)}`,
      `加速度 ${Math.round(acceleration * 100)}`,
      `路径持续性 ${Math.round(persistence * 100)}%`,
    ],
  }
}
