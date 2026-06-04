import type {
  OpeningBaselineQuality,
  OpeningAuctionPriceVolumeProfile,
  OpeningWeakToStrongBaseline,
  OpeningWeakToStrongQuote,
  OpeningWeakToStrongRules,
  OpeningWeakToStrongSignal,
} from './openingWeakToStrongTypes'

const SIGNAL_TYPE = 'opening_weak_to_strong' as const
const DISPLAY_NAME = '竞价弱转强' as const
const RULE_VERSION = 'opening-weak-to-strong.v1'
const CONFIRM_BASELINE_TIME = '09:25:00'
const GAP_ALERT_TIME = '09:30:00'
const TREND_CONFIRM_TIME = '09:35:00'
const OPTIONAL_FINAL_TIME = '10:00:00'

export class OpeningAuctionStateStore {
  private readonly baselines = new Map<string, OpeningWeakToStrongBaseline>()
  private readonly samples = new Map<string, OpeningWeakToStrongQuote[]>()

  constructor(private readonly rules: OpeningWeakToStrongRules) {}

  capture(quote: OpeningWeakToStrongQuote) {
    if (!isValidPrice(quote.lastPrice) || !isValidPrice(quote.preClose)) return

    const tradingDate = getTradingDate(quote.at)
    const key = baselineKey(quote.code, tradingDate)
    const inTrendWindow = isInWindow(quote.at, this.rules.auctionTrendStart, this.rules.auctionEnd)
    let samplesForProfile = this.samples.get(key)
    if (inTrendWindow) {
      const samples = this.samples.get(key) || []
      samples.push(quote)
      samples.sort((left, right) => secondsOfDay(left.at) - secondsOfDay(right.at))
      samplesForProfile = samples.slice(-16)
      this.samples.set(key, samplesForProfile)
    }

    const previous = this.baselines.get(key)
    const auctionProfile = buildAuctionProfile(samplesForProfile || [quote], this.rules)
    if (!isCheckpointTime(quote.at, CONFIRM_BASELINE_TIME)) {
      if (previous && inTrendWindow) {
        this.baselines.set(key, { ...previous, auctionProfile })
      }
      return
    }

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
      sampleCount: Math.max(previous?.sampleCount || 0, countAuctionBaselineSamples(samplesForProfile || [quote])),
      quality,
      openingForcedSample: quote.openingForcedSample,
      requestedCount: quote.requestedCount,
      receivedCount: quote.receivedCount,
      elapsedMs: quote.elapsedMs,
      slowBatches: quote.slowBatches,
      truncatedBatches: quote.truncatedBatches,
      auctionProfile,
    })
  }

  getBaseline(code: string, timestamp?: string): OpeningWeakToStrongBaseline | null {
    if (!timestamp) return null
    return this.baselines.get(baselineKey(code, getTradingDate(timestamp))) || null
  }
}

export class OpeningWeakToStrongDetector {
  private readonly activeSignals = new Map<string, OpeningWeakToStrongSignal>()

  constructor(
    private readonly rules: OpeningWeakToStrongRules,
    private readonly ruleVersion = RULE_VERSION,
  ) {}

  evaluate(
    quote: OpeningWeakToStrongQuote,
    baseline: OpeningWeakToStrongBaseline | null,
  ): OpeningWeakToStrongSignal | null {
    if (!isValidPrice(quote.lastPrice) || !isValidPrice(quote.preClose)) return null

    const activeKey = baselineKey(quote.code, getTradingDate(quote.at))
    const activeSignal = this.activeSignals.get(activeKey)
    let signal: OpeningWeakToStrongSignal | null = null

    if (isCheckpointTime(quote.at, CONFIRM_BASELINE_TIME)) {
      signal = this.evaluateAuctionCheckpoint(quote, baseline)
    } else if (isCheckpointTime(quote.at, GAP_ALERT_TIME)) {
      signal = this.evaluateGapCheckpoint(quote, baseline)
    } else if (isCheckpointTime(quote.at, TREND_CONFIRM_TIME)) {
      signal = this.evaluateTrendCheckpoint(quote, baseline, activeSignal)
    } else if (isCheckpointTime(quote.at, OPTIONAL_FINAL_TIME)) {
      signal = this.evaluateFinalCheckpoint(quote, baseline)
    }

    if (signal?.triggered) this.activeSignals.set(activeKey, signal)
    return signal
  }

  private evaluateAuctionCheckpoint(
    quote: OpeningWeakToStrongQuote,
    baseline: OpeningWeakToStrongBaseline | null,
  ): OpeningWeakToStrongSignal {
    if (!baseline?.auctionProfile?.initialAt) {
      return this.checkpointSignal(quote, baseline, 'auctionConditionFailed', false, '缺少09:20初始基线')
    }
    if (!baseline.auctionProfile.lateBaselineAt) {
      return this.checkpointSignal(quote, baseline, 'auctionConditionFailed', false, '缺少09:24临门基线')
    }

    const profile = baseline.auctionProfile
    const priceLift = normalizeNumber(profile.totalLiftPctPoint)
    const amountLift = normalizeNumber(profile.amountLiftRatio)
    const latePriceLift = normalizeNumber(profile.latePriceLiftPctPoint)
    const lateAmountLift = normalizeNumber(profile.lateAmountLiftRatio)
    const passed =
      isValidPrice(baseline.auctionFinalPrice) &&
      priceLift >= this.rules.auctionPriceLiftMinPctPoint &&
      amountLift >= this.rules.auctionAmountLiftMinRatio &&
      latePriceLift >= this.rules.auctionLatePriceLiftMinPctPoint &&
      lateAmountLift >= this.rules.auctionLateAmountLiftMinRatio
    return this.checkpointSignal(
      quote,
      baseline,
      passed ? 'auctionConditionPassed' : 'auctionConditionFailed',
      false,
      passed
        ? '09:20总量价与09:24临门量价均通过，列入候选'
        : '09:20总量价或09:24临门量价不足，候选不成立',
    )
  }

  private evaluateGapCheckpoint(
    quote: OpeningWeakToStrongQuote,
    baseline: OpeningWeakToStrongBaseline | null,
  ): OpeningWeakToStrongSignal {
    if (!hasConfirmBaseline(baseline)) return this.rejected(quote, baseline, 'missing_09_25_confirm_baseline')

    const open = normalizeNumber(quote.open) || quote.lastPrice
    const openPct = pct(open, quote.preClose)
    const gapPctPoint = openPct - baseline.auctionPct
    const hasGap = gapPctPoint >= this.rules.auctionGapJumpMinPctPoint
    return this.checkpointSignal(
      quote,
      baseline,
      hasGap ? 'gapAlert' : 'noGap',
      hasGap,
      hasGap ? '09:30较09:25出现跳空高开缺口' : '09:30未出现有效跳空高开缺口',
      {
        officialOpen: open,
        officialOpenPct: round2(openPct),
        firstWindowPrice: quote.lastPrice,
        firstWindowPct: round2(pct(quote.lastPrice, quote.preClose)),
        jumpPctPoint: round2(gapPctPoint),
      },
    )
  }

  private evaluateTrendCheckpoint(
    quote: OpeningWeakToStrongQuote,
    baseline: OpeningWeakToStrongBaseline | null,
    activeSignal: OpeningWeakToStrongSignal | null | undefined,
  ): OpeningWeakToStrongSignal {
    if (!hasConfirmBaseline(baseline)) return this.rejected(quote, baseline, 'missing_09_25_confirm_baseline')

    const open = normalizeNumber(activeSignal?.officialOpen || quote.open)
    const openPct = open > 0 ? pct(open, quote.preClose) : undefined
    const currentPct = pct(quote.lastPrice, quote.preClose)
    const amount = normalizeNumber(quote.amount)
    const baseAmount = normalizeNumber(baseline.auctionAmount)
    const strong =
      open > 0 &&
      quote.lastPrice >= open &&
      currentPct >= Math.max(normalizeNumber(openPct), normalizeNumber(activeSignal?.firstWindowPct)) &&
      (baseAmount <= 0 || amount >= baseAmount)
    return this.checkpointSignal(
      quote,
      baseline,
      strong ? 'trendConfirm' : 'trendWeak',
      strong,
      strong ? '09:30到09:35高开高走，出现快速上板前兆' : '09:30到09:35承接不足，趋势转弱',
      {
        officialOpen: open || undefined,
        officialOpenPct: openPct === undefined ? undefined : round2(openPct),
        firstWindowPrice: quote.lastPrice,
        firstWindowPct: round2(currentPct),
        amount,
      },
    )
  }

  private evaluateFinalCheckpoint(
    quote: OpeningWeakToStrongQuote,
    baseline: OpeningWeakToStrongBaseline | null,
  ): OpeningWeakToStrongSignal {
    return this.checkpointSignal(
      quote,
      baseline,
      'optionalFinalStatus',
      false,
      '10:00仅更新最终状态备注，不影响09:30/09:35播报',
      {
        firstWindowPrice: quote.lastPrice,
        firstWindowPct: round2(pct(quote.lastPrice, quote.preClose)),
        amount: normalizeNumber(quote.amount),
      },
    )
  }

  private checkpointSignal(
    quote: OpeningWeakToStrongQuote,
    baseline: OpeningWeakToStrongBaseline | null,
    stage: OpeningWeakToStrongSignal['stage'],
    voiceEligible: boolean,
    reason: string,
    overrides: Partial<OpeningWeakToStrongSignal> = {},
  ): OpeningWeakToStrongSignal {
    return {
      triggered: true,
      signalType: SIGNAL_TYPE,
      displayName: DISPLAY_NAME,
      code: quote.code,
      name: quote.name || baseline?.name || quote.code,
      stage,
      status: stage,
      voiceEligible,
      reason,
      price: overrides.firstWindowPrice ?? quote.lastPrice,
      pct: overrides.firstWindowPct ?? round2(pct(quote.lastPrice, quote.preClose)),
      auctionFinalPrice: baseline?.auctionFinalPrice,
      auctionPct: baseline ? round2(baseline.auctionPct) : undefined,
      amount: normalizeNumber(quote.amount),
      triggerAt: quote.at,
      time: quote.at,
      baselineQuality: baseline?.quality || 'missing',
      auctionCapturedAt: baseline?.capturedAt,
      bridgeTs: baseline?.bridgeTs,
      quoteCapturedAt: quote.capturedAt || quote.bridgeTs || quote.at,
      auctionSampleCount: baseline?.sampleCount,
      quoteAgeMs: ageMs(quote.capturedAt || quote.bridgeTs || quote.at, quote.at),
      latencyMs: baseline ? ageMs(baseline.capturedAt, quote.at) : undefined,
      openingForcedSample: baseline?.openingForcedSample,
      requestedCount: baseline?.requestedCount,
      receivedCount: baseline?.receivedCount,
      elapsedMs: baseline?.elapsedMs,
      slowBatches: baseline?.slowBatches,
      truncatedBatches: baseline?.truncatedBatches,
      ruleVersion: this.ruleVersion,
      configHash: configHash(this.rules),
      ...overrides,
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
      stage: 'noGap',
      status: 'noGap',
      voiceEligible: false,
      reason: invalidReason,
      price: quote.lastPrice,
      pct: round2(pct(quote.lastPrice, quote.preClose)),
      auctionFinalPrice: baseline?.auctionFinalPrice,
      auctionPct: baseline ? round2(baseline.auctionPct) : undefined,
      amount: normalizeNumber(quote.amount),
      triggerAt: quote.at,
      time: quote.at,
      baselineQuality: baseline?.quality || 'missing',
      auctionCapturedAt: baseline?.capturedAt,
      bridgeTs: baseline?.bridgeTs,
      quoteCapturedAt: quote.capturedAt || quote.bridgeTs || quote.at,
      auctionSampleCount: baseline?.sampleCount,
      quoteAgeMs: ageMs(quote.capturedAt || quote.bridgeTs || quote.at, quote.at),
      latencyMs: baseline ? ageMs(baseline.capturedAt, quote.at) : undefined,
      openingForcedSample: baseline?.openingForcedSample,
      requestedCount: baseline?.requestedCount,
      receivedCount: baseline?.receivedCount,
      elapsedMs: baseline?.elapsedMs,
      slowBatches: baseline?.slowBatches,
      truncatedBatches: baseline?.truncatedBatches,
      invalidReason,
      ruleVersion: this.ruleVersion,
      configHash: configHash(this.rules),
    }
  }
}

export type OpeningWeakToStrongResult = OpeningWeakToStrongSignal

function buildAuctionProfile(
  samples: OpeningWeakToStrongQuote[],
  rules: OpeningWeakToStrongRules,
): OpeningAuctionPriceVolumeProfile | undefined {
  const trusted = samples
    .filter(item => isInWindow(item.at, rules.auctionTrendStart, rules.auctionEnd))
    .filter(item => isValidPrice(item.lastPrice) && isValidPrice(item.preClose))
    .sort((left, right) => secondsOfDay(left.at) - secondsOfDay(right.at))
  if (trusted.length < 2) return undefined

  const initial = trusted.find(item => isInWindow(item.at, rules.initialBaselineStart, rules.initialBaselineEnd))
  const final = trusted.find(item => isCheckpointTime(item.at, CONFIRM_BASELINE_TIME)) || trusted[trusted.length - 1]
  const lateBaseline =
    trusted.find(item => secondsOfDay(item.at) >= secondsOfDay(rules.auctionLateLiftStart)) || final
  const startPct = initial ? pct(initial.lastPrice, initial.preClose) : undefined
  const lateBaselinePct = pct(lateBaseline.lastPrice, lateBaseline.preClose)
  const finalPct = pct(final.lastPrice, final.preClose)
  const initialAmount = initial ? normalizeNumber(initial.amount) : undefined
  const lateBaselineAmount = normalizeNumber(lateBaseline.amount)
  const finalAmount = normalizeNumber(final.amount)
  const amountDelta = initialAmount === undefined ? undefined : finalAmount - initialAmount
  const lateAmountDelta = finalAmount - lateBaselineAmount
  const amountLiftRatio = ratioFromBase(amountDelta, initialAmount)
  const lateAmountLiftRatio = ratioFromBase(lateAmountDelta, lateBaselineAmount)
  const totalLiftPctPoint = startPct === undefined ? undefined : finalPct - startPct
  const latePriceLiftPctPoint = finalPct - lateBaselinePct
  const latePriceLifted = latePriceLiftPctPoint >= rules.auctionLatePriceLiftMinPctPoint
  const lateAmountExpanded =
    lateAmountLiftRatio !== undefined && lateAmountLiftRatio >= rules.auctionLateAmountLiftMinRatio
  const priceVolumeConfirmed =
    initial !== undefined &&
    totalLiftPctPoint !== undefined &&
    amountLiftRatio !== undefined &&
    totalLiftPctPoint >= rules.auctionPriceLiftMinPctPoint &&
    amountLiftRatio >= rules.auctionAmountLiftMinRatio &&
    latePriceLifted &&
    lateAmountExpanded

  return {
    sampleCount: trusted.length,
    initialAt: initial?.at,
    initialPrice: initial?.lastPrice,
    initialPct: startPct === undefined ? undefined : round2(startPct),
    initialAmount,
    lateBaselineAt: lateBaseline.at,
    lateBaselinePrice: lateBaseline.lastPrice,
    lateBaselinePct: round2(lateBaselinePct),
    lateBaselineAmount,
    finalAt: final.at,
    finalPrice: final.lastPrice,
    finalAmount,
    finalPct: round2(finalPct),
    totalLiftPctPoint: totalLiftPctPoint === undefined ? undefined : round2(totalLiftPctPoint),
    latePriceLiftPctPoint: round2(latePriceLiftPctPoint),
    amountDelta,
    lateAmountDelta,
    amountLiftRatio: amountLiftRatio === undefined ? undefined : round2(amountLiftRatio),
    lateAmountLiftRatio: lateAmountLiftRatio === undefined ? undefined : round2(lateAmountLiftRatio),
    priceVolumeConfirmed,
  }
}

function ratioFromBase(delta: number | undefined, base: number | undefined): number | undefined {
  if (delta === undefined || base === undefined || base <= 0) return undefined
  return delta / base
}

function countAuctionBaselineSamples(samples: OpeningWeakToStrongQuote[]): number {
  return samples.filter(item => isCheckpointTime(item.at, CONFIRM_BASELINE_TIME)).length
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

function isCheckpointTime(timestamp: string, checkpoint: string): boolean {
  return secondsOfDay(timestamp) === secondsOfDay(checkpoint)
}

function isOpeningBaseline(
  value: OpeningWeakToStrongBaseline | OpeningWeakToStrongSignal | null | undefined,
): value is OpeningWeakToStrongBaseline {
  return Boolean(value && 'tradingDate' in value && 'auctionAmount' in value)
}

function hasConfirmBaseline(
  value: OpeningWeakToStrongBaseline | null | undefined,
): value is OpeningWeakToStrongBaseline {
  return isOpeningBaseline(value) && isCheckpointTime(value.capturedAt, CONFIRM_BASELINE_TIME)
}

function getTradingDate(timestamp: string): string {
  return timestamp.slice(0, 10)
}

function baselineKey(code: string, tradingDate: string): string {
  return `${tradingDate}:${code}`
}

function secondsOfDay(value: string): number {
  const match = value.match(/(?:T)?(\d{2}):(\d{2}):(\d{2})/)
  if (!match) {
    console.warn(`[OpeningWeakToStrong] unparseable timestamp, defaulting to 00:00:00: "${value}"`)
    return 0
  }
  let hours = Number(match[1])
  if (/[zZ]$/.test(value)) hours = (hours + 8) % 24
  return hours * 3600 + Number(match[2]) * 60 + Number(match[3])
}

function ageMs(from: string | undefined, to: string): number | undefined {
  if (!from) return undefined
  const elapsed = Date.parse(to) - Date.parse(from)
  return Number.isFinite(elapsed) ? Math.max(0, elapsed) : undefined
}

function round2(value: number): number {
  return Math.round(value * 100) / 100
}

function configHash(rules: OpeningWeakToStrongRules): string {
  const hashKeys = ([
    'auctionAmountLiftMinRatio',
    'auctionEnd',
    'auctionGapJumpMinPctPoint',
    'auctionLateAmountLiftMinRatio',
    'auctionLateLiftStart',
    'auctionLatePriceLiftMinPctPoint',
    'auctionPriceLiftMinPctPoint',
    'auctionStart',
    'auctionTrendStart',
    'initialBaselineEnd',
    'initialBaselineStart',
  ] as (keyof OpeningWeakToStrongRules)[]).sort()
  const hashRules = Object.fromEntries(hashKeys.map((key) => [key, rules[key]]))
  const json = JSON.stringify(hashRules)
  let hash = 2166136261
  for (let index = 0; index < json.length; index++) {
    hash ^= json.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return `owts-${(hash >>> 0).toString(16).padStart(8, '0')}`
}
