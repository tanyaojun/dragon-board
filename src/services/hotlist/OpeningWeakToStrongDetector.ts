import type {
  OpeningBaselineQuality,
  OpeningAuctionPriceVolumeProfile,
  OpeningWeakToStrongBaseline,
  OpeningWeakToStrongFactor,
  OpeningWeakToStrongQuote,
  OpeningWeakToStrongRiskFlag,
  OpeningWeakToStrongRules,
  OpeningWeakToStrongSignal,
  OpeningWeakToStrongVariant,
} from './openingWeakToStrongTypes'

const SIGNAL_TYPE = 'opening_weak_to_strong' as const
const DISPLAY_NAME = '竞价弱转强' as const
const RULE_VERSION = 'opening-weak-to-strong.v1'

export class OpeningAuctionStateStore {
  private readonly baselines = new Map<string, OpeningWeakToStrongBaseline>()
  private readonly samples = new Map<string, OpeningWeakToStrongQuote[]>()

  constructor(private readonly rules: OpeningWeakToStrongRules) {}

  capture(quote: OpeningWeakToStrongQuote) {
    if (!isValidPrice(quote.lastPrice) || !isValidPrice(quote.preClose)) return

    const tradingDate = getTradingDate(quote.at)
    const key = baselineKey(quote.code, tradingDate)
    if (isInWindow(quote.at, this.rules.auctionTrendStart, this.rules.auctionEnd)) {
      const samples = this.samples.get(key) || []
      samples.push(quote)
      samples.sort((left, right) => secondsOfDay(left.at) - secondsOfDay(right.at))
      this.samples.set(key, samples.slice(-64))
    }

    if (!isInWindow(quote.at, this.rules.auctionStart, this.rules.auctionEnd)) return

    const previous = this.baselines.get(key)
    const sampleCount = (previous?.sampleCount || 0) + 1
    const capturedAt = quote.capturedAt || quote.at
    const quality: OpeningBaselineQuality = quote.capturedAt || quote.bridgeTs ? 'good' : 'degraded'
    this.baselines.set(key, {
      code: quote.code,
      tradingDate,
      name: quote.name || quote.code,
      auctionFinalPrice: quote.lastPrice,
      auctionPct: pct(quote.lastPrice, quote.preClose),
      auctionAmount: normalizeNumber(quote.amount),
      preClose: quote.preClose,
      capturedAt,
      bridgeTs: quote.bridgeTs,
      sampleCount,
      quality,
      auctionProfile: buildAuctionProfile(this.samples.get(key) || [quote], this.rules),
    })
  }

  getBaseline(code: string, timestamp?: string): OpeningWeakToStrongBaseline | null {
    if (!timestamp) return null
    return this.baselines.get(baselineKey(code, getTradingDate(timestamp))) || null
  }
}

export class OpeningWeakToStrongDetector {
  constructor(
    private readonly rules: OpeningWeakToStrongRules,
    private readonly ruleVersion = RULE_VERSION,
  ) {}

  evaluate(
    quote: OpeningWeakToStrongQuote,
    baseline: OpeningWeakToStrongBaseline | null,
  ): OpeningWeakToStrongSignal | null {
    if (!isInWindow(quote.at, this.rules.detectStart, this.rules.detectEnd)) {
      return this.rejected(quote, baseline, 'outside_detection_window')
    }
    if (!baseline) return this.rejected(quote, null, 'baseline_missing')
    if (!isValidPrice(quote.lastPrice) || !isValidPrice(quote.preClose)) {
      return this.rejected(quote, baseline, 'invalid_price')
    }

    const auctionPct = baseline.auctionPct
    const firstWindowPct = pct(quote.lastPrice, quote.preClose)
    const officialOpen = normalizeNumber(quote.open)
    const officialOpenPct = officialOpen > 0 ? pct(officialOpen, quote.preClose) : undefined
    const jumpPctPoint = firstWindowPct - auctionPct
    const amount = normalizeNumber(quote.amount)
    const amountDelta = amount - baseline.auctionAmount
    const limitDistancePct = quote.limitUpPrice && quote.limitUpPrice > 0
      ? (quote.limitUpPrice - quote.lastPrice) / quote.limitUpPrice * 100
      : undefined
    const amountOk = amount >= this.rules.minCurrentAmount || amountDelta >= this.rules.minAmountDelta
    const weakPrecondition =
      auctionPct <= this.rules.auctionWeakMaxPct ||
      (officialOpenPct !== undefined && officialOpenPct <= this.rules.auctionWeakMaxPct)

    if (!amountOk) return this.rejected(quote, baseline, 'opening_amount_too_small')

    const strongOpenCandidate =
      firstWindowPct >= this.rules.strongOpenFirstWindowMinPct &&
      limitDistancePct !== undefined &&
      limitDistancePct <= this.rules.nearLimitDistancePct
    if (strongOpenCandidate && !weakPrecondition) {
      return this.rejected(quote, baseline, 'weak_precondition_missing')
    }

    const auctionProfile = baseline.auctionProfile
    let variant: OpeningWeakToStrongVariant | null = null
    if (
      auctionProfile?.lateLiftConfirmed &&
      firstWindowPct >= this.rules.auctionLateLiftFirstWindowMinPct &&
      jumpPctPoint >= this.rules.auctionLateLiftJumpMinPctPoint
    ) {
      variant = 'auction_late_lift'
    }
    if (!variant && strongOpenCandidate && weakPrecondition) {
      variant = 'strong_open_board_attempt'
    }
    if (
      !variant &&
      auctionPct <= this.rules.auctionWeakMaxPct &&
      jumpPctPoint >= this.rules.auctionGapJumpMinPctPoint &&
      firstWindowPct >= this.rules.auctionGapFirstWindowMinPct
    ) {
      variant = 'auction_gap_reversal'
    }
    if (
      !variant &&
      (auctionPct <= 0 || (officialOpenPct !== undefined && officialOpenPct <= this.rules.auctionWeakMaxPct)) &&
      firstWindowPct >= this.rules.lowOpenRedFirstWindowMinPct &&
      jumpPctPoint >= this.rules.lowOpenRedJumpMinPctPoint
    ) {
      variant = 'low_open_red_reversal'
    }
    if (!variant) return this.rejected(quote, baseline, 'variant_not_matched')

    const factors = buildFactors({
      variant,
      jumpPctPoint,
      firstWindowPct,
      amount,
      amountDelta,
      limitDistancePct,
      baselineQuality: baseline.quality,
      auctionProfile,
      rules: this.rules,
    })
    const riskFlags = (auctionProfile?.riskFlags || []).map(riskFlag)
    const riskPenalty = riskFlags.reduce((sum, item) => sum + Math.abs(item.penalty), 0)
    const score = clampScore(factors.reduce((sum, item) => sum + item.score, 0) - riskPenalty)
    const confidence =
      riskFlags.length > 0 ? 'watch' : score >= 80 ? 'critical' : score >= 60 ? 'strong' : 'watch'

    return {
      triggered: true,
      signalType: SIGNAL_TYPE,
      displayName: DISPLAY_NAME,
      code: quote.code,
      name: quote.name || baseline.name || quote.code,
      variant,
      confidence,
      score,
      auctionFinalPrice: baseline.auctionFinalPrice,
      auctionPct: round2(auctionPct),
      officialOpen: officialOpen || undefined,
      officialOpenPct: officialOpenPct === undefined ? undefined : round2(officialOpenPct),
      firstWindowPrice: quote.lastPrice,
      firstWindowPct: round2(firstWindowPct),
      jumpPctPoint: round2(jumpPctPoint),
      amount,
      amountDelta,
      limitDistancePct: limitDistancePct === undefined ? undefined : round2(limitDistancePct),
      triggerAt: quote.at,
      baselineQuality: baseline.quality,
      factors,
      riskFlags,
      ruleVersion: this.ruleVersion,
      configHash: configHash(this.rules),
    }
  }

  private rejected(
    quote: OpeningWeakToStrongQuote,
    baseline: OpeningWeakToStrongBaseline | null,
    invalidReason: string,
  ): OpeningWeakToStrongSignal {
    return {
      triggered: false,
      signalType: SIGNAL_TYPE,
      displayName: DISPLAY_NAME,
      code: quote.code,
      name: quote.name || baseline?.name || quote.code,
      score: 0,
      amount: normalizeNumber(quote.amount),
      triggerAt: quote.at,
      baselineQuality: baseline?.quality || 'missing',
      factors: [],
      riskFlags: [riskFlag(invalidReason)],
      invalidReason,
      ruleVersion: this.ruleVersion,
      configHash: configHash(this.rules),
    }
  }
}

export type OpeningWeakToStrongResult = OpeningWeakToStrongSignal

function buildFactors(input: {
  variant: OpeningWeakToStrongVariant
  jumpPctPoint: number
  firstWindowPct: number
  amount: number
  amountDelta: number
  limitDistancePct?: number
  baselineQuality: OpeningBaselineQuality
  auctionProfile?: OpeningAuctionPriceVolumeProfile
  rules: OpeningWeakToStrongRules
}): OpeningWeakToStrongFactor[] {
  const factors: OpeningWeakToStrongFactor[] = []
  if (input.variant === 'auction_late_lift') {
    factors.push({
      key: 'auctionLateLift',
      value: round2(input.auctionProfile?.totalLiftPctPoint ?? 0),
      threshold: input.rules.auctionLateLiftTotalMinPctPoint,
      score: 24,
    })
    factors.push({
      key: 'auctionLateAmount',
      value: input.auctionProfile?.lateAmountDelta ?? 0,
      threshold: input.rules.auctionLateLiftLateAmountDeltaMin,
      score: 18,
    })
    factors.push({
      key: 'openStrength',
      value: round2(input.firstWindowPct),
      threshold: input.rules.auctionLateLiftFirstWindowMinPct,
      score: 18,
    })
  } else if (input.variant === 'strong_open_board_attempt') {
    factors.push({
      key: 'nearLimit',
      value: round2(input.limitDistancePct ?? 99),
      threshold: input.rules.nearLimitDistancePct,
      score: 30,
    })
    factors.push({
      key: 'openStrength',
      value: round2(input.firstWindowPct),
      threshold: input.rules.strongOpenFirstWindowMinPct,
      score: 25,
    })
  } else if (input.variant === 'auction_gap_reversal') {
    factors.push({
      key: 'auctionGap',
      value: round2(input.jumpPctPoint),
      threshold: input.rules.auctionGapJumpMinPctPoint,
      score: Math.min(35, 20 + input.jumpPctPoint * 3),
    })
    factors.push({
      key: 'openStrength',
      value: round2(input.firstWindowPct),
      threshold: input.rules.auctionGapFirstWindowMinPct,
      score: 10,
    })
  } else {
    factors.push({
      key: 'redReversal',
      value: round2(input.jumpPctPoint),
      threshold: input.rules.lowOpenRedJumpMinPctPoint,
      score: 28,
    })
    factors.push({
      key: 'turnRed',
      value: round2(input.firstWindowPct),
      threshold: input.rules.lowOpenRedFirstWindowMinPct,
      score: 12,
    })
  }

  factors.push({
    key: 'openingAmount',
    value: input.amount,
    threshold: input.rules.minCurrentAmount,
    score: input.amountDelta >= input.rules.minAmountDelta ? 18 : 12,
  })
  factors.push({
    key: 'baselineQuality',
    value: input.baselineQuality,
    score: input.baselineQuality === 'good' ? 10 : 4,
  })
  return factors
}

function riskFlag(key: string): OpeningWeakToStrongRiskFlag {
  const severity = key === 'baseline_missing'
    ? 'high'
    : key === 'price_lift_without_volume' ||
        key === 'volume_without_price_lift' ||
        key === 'auction_late_high_retreated'
      ? 'medium'
      : 'medium'
  const penalty = key === 'baseline_missing' ? -100 : -35
  return { key, severity, penalty }
}

function buildAuctionProfile(
  samples: OpeningWeakToStrongQuote[],
  rules: OpeningWeakToStrongRules,
): OpeningAuctionPriceVolumeProfile | undefined {
  const trusted = samples
    .filter(item => isInWindow(item.at, rules.auctionTrendStart, rules.auctionEnd))
    .filter(item => isValidPrice(item.lastPrice) && isValidPrice(item.preClose))
    .sort((left, right) => secondsOfDay(left.at) - secondsOfDay(right.at))
  if (trusted.length < 2) return undefined

  const first = trusted[0]
  const final = trusted[trusted.length - 1]
  const lateSamples = trusted.filter(item => secondsOfDay(item.at) >= secondsOfDay(rules.auctionLateLiftStart))
  const lateStart = lateSamples[0] || final
  const startPct = pct(first.lastPrice, first.preClose)
  const lateStartPct = pct(lateStart.lastPrice, lateStart.preClose)
  const finalPct = pct(final.lastPrice, final.preClose)
  const highPct = Math.max(...trusted.map(item => pct(item.lastPrice, item.preClose)))
  const totalLiftPctPoint = finalPct - startPct
  const lateLiftPctPoint = finalPct - lateStartPct
  const amountDelta = normalizeNumber(final.amount) - normalizeNumber(first.amount)
  const lateAmountDelta = normalizeNumber(final.amount) - normalizeNumber(lateStart.amount)
  const priceLifted = meets(totalLiftPctPoint, rules.auctionLateLiftTotalMinPctPoint) ||
    meets(lateLiftPctPoint, rules.auctionLateLiftLateMinPctPoint)
  const amountExpanded = meets(amountDelta, rules.auctionLateLiftAmountDeltaMin) ||
    meets(lateAmountDelta, rules.auctionLateLiftLateAmountDeltaMin)
  const highRetreated = meets(highPct - finalPct, rules.auctionLateHighRetreatPctPoint)
  const riskFlags: string[] = []
  if (priceLifted && !amountExpanded) riskFlags.push('price_lift_without_volume')
  if (amountExpanded && !priceLifted) riskFlags.push('volume_without_price_lift')
  if (highRetreated) riskFlags.push('auction_late_high_retreated')

  return {
    sampleCount: trusted.length,
    startPct: round2(startPct),
    lateStartPct: round2(lateStartPct),
    finalPct: round2(finalPct),
    highPct: round2(highPct),
    totalLiftPctPoint: round2(totalLiftPctPoint),
    lateLiftPctPoint: round2(lateLiftPctPoint),
    amountDelta,
    lateAmountDelta,
    lateLiftConfirmed:
      priceLifted &&
      amountExpanded &&
      !highRetreated &&
      finalPct >= rules.auctionLateLiftFinalMinPct,
    riskFlags,
  }
}

function meets(value: number, threshold: number): boolean {
  return value + 1e-6 >= threshold
}

function isValidPrice(value: number): boolean {
  return Number.isFinite(value) && value > 0
}

function normalizeNumber(value: unknown): number {
  const numberValue = Number(value)
  return Number.isFinite(numberValue) ? numberValue : 0
}

function pct(price: number, preClose: number): number {
  return (price - preClose) / preClose * 100
}

function isInWindow(timestamp: string, start: string, end: string): boolean {
  const value = secondsOfDay(timestamp)
  return value >= secondsOfDay(start) && value <= secondsOfDay(end)
}

function getTradingDate(timestamp: string): string {
  return timestamp.slice(0, 10)
}

function baselineKey(code: string, tradingDate: string): string {
  return `${tradingDate}:${code}`
}

function secondsOfDay(value: string): number {
  const match = value.match(/(?:T)?(\d{2}):(\d{2}):(\d{2})/)
  if (match) return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3])
  const date = new Date(value)
  return date.getHours() * 3600 + date.getMinutes() * 60 + date.getSeconds()
}

function round2(value: number): number {
  return Math.round(value * 100) / 100
}

function clampScore(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value)))
}

function configHash(rules: OpeningWeakToStrongRules): string {
  const json = JSON.stringify(rules, Object.keys(rules).sort())
  let hash = 2166136261
  for (let index = 0; index < json.length; index++) {
    hash ^= json.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return `owts-${(hash >>> 0).toString(16).padStart(8, '0')}`
}
