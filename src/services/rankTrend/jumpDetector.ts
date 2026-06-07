export interface JumpEvent {
  index: number
  direction: 'surge' | 'collapse'
  magnitude: number
}

export interface JumpResult {
  event: 'jump' | 'none'
  direction: 'buy' | 'sell' | 'hold'
  signal: 'buy' | 'sell' | 'hold'
  magnitude: number
  overshoot: number
  delta: number
  sustained: boolean
  confidence: number
  eventCount: number
  surgeCount: number
  collapseCount: number
  rankMagnitude: number
  cumulativeChange?: number
  events: JumpEvent[]
}

export function detectRankJumps(
  percentiles: number[],
  ranks?: number[] | null,
  deltaPct?: number,
): JumpResult {
  const delta = deltaPct ?? 15

  if (!Array.isArray(percentiles) || percentiles.length < 3) {
    return {
      event: 'none', direction: 'hold', signal: 'hold',
      magnitude: 0, overshoot: 0, delta,
      sustained: false, confidence: 50, eventCount: 0,
      surgeCount: 0, collapseCount: 0, rankMagnitude: 0, events: [],
    }
  }

  let ref = percentiles[0]
  const events: JumpEvent[] = []

  for (let i = 0; i < percentiles.length; i++) {
    const p = percentiles[i]
    const cumChange = p - ref
    if (Math.abs(cumChange) > delta) {
      events.push({
        index: i,
        direction: cumChange > 0 ? 'surge' : 'collapse',
        magnitude: Math.round(Math.abs(cumChange) * 100) / 100,
      })
      const lookback = Math.min(3, i + 1)
      let sum = 0
      for (let j = i - lookback + 1; j <= i; j++) {
        sum += percentiles[j]
      }
      ref = sum / lookback
    }
  }

  if (events.length === 0) {
    const cum = percentiles[percentiles.length - 1] - percentiles[0]
    return {
      event: 'none', direction: 'hold', signal: 'hold',
      magnitude: Math.round(Math.abs(cum) * 100) / 100, overshoot: 0, delta,
      sustained: false, confidence: 50, eventCount: 0,
      surgeCount: 0, collapseCount: 0, rankMagnitude: 0, events: [],
      cumulativeChange: Math.round(cum * 100) / 100,
    }
  }

  const latest = events[events.length - 1]
  const surgeCount = events.filter(e => e.direction === 'surge').length
  const collapseCount = events.filter(e => e.direction === 'collapse').length
  const sustained = surgeCount >= 2 || collapseCount >= 2
  const direction = latest.direction === 'surge' ? 'buy' : 'sell'

  const mag = latest.magnitude
  const overshoot = Math.round((mag - delta) * 100) / 100
  const magFactor = Math.min(1.0, mag / Math.max(delta * 2, 1))
  const overshootFactor = Math.min(1.0, Math.max(0, overshoot) / Math.max(delta, 1))
  const sustainBonus = sustained ? 0.2 : 0
  const rawConf = 55 + 25 * magFactor + 15 * overshootFactor + 20 * sustainBonus
  const confidence = Math.round(Math.min(95, Math.max(50, rawConf)) * 10) / 10

  let rankMagnitude = 0
  if (ranks && ranks.length >= 2) {
    rankMagnitude = Math.abs(ranks[ranks.length - 1] - ranks[0])
  }

  return {
    event: 'jump',
    direction,
    signal: direction,
    magnitude: mag,
    overshoot,
    delta,
    sustained,
    confidence,
    eventCount: events.length,
    surgeCount,
    collapseCount,
    rankMagnitude,
    events: events.map(e => ({
      index: e.index,
      direction: e.direction,
      magnitude: e.magnitude,
    })),
  }
}
