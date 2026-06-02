import type {
  OpeningBaselineQuality,
  OpeningAuctionPriceVolumeProfile,
  OpeningLiquidityTier,
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
const LIQUIDITY_TIER_VERSION = 'liquidity-review.v1'
const HOT_AMOUNT = 100_000_000
const PREOPEN_CANDIDATE_START = '09:25:00'
const INTRADAY_CONFIRM_END = '10:00:00'
const INTRADAY_CONFIRM_ADVANCE_PCT_POINT = 1
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
      samplesForProfile = samples.slice(-64)
      this.samples.set(key, samplesForProfile)
    }

    const previous = this.baselines.get(key)
    const auctionProfile = buildAuctionProfile(samplesForProfile || [quote], this.rules)
    if (!isInWindow(quote.at, this.rules.auctionStart, this.rules.auctionEnd)) {
      if (previous && inTrendWindow) {
        this.baselines.set(key, {
          ...previous,
          auctionProfile,
        })
      }
      return
    }

    const capturedAt = quote.capturedAt || quote.at
    const auctionSampleCount = countAuctionBaselineSamples(samplesForProfile || [quote], this.rules)
    if (previous && compareQuoteFreshness(quote, previous.capturedAt) <= 0) {
      this.baselines.set(key, {
        ...previous,
        sampleCount: Math.max(previous.sampleCount, auctionSampleCount),
        auctionProfile,
      })
      return
    }

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
      sampleCount: Math.max(previous?.sampleCount || 0, auctionSampleCount),
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
    const activeKey = baselineKey(quote.code, getTradingDate(quote.at))
    const activeSignal = this.activeSignals.get(activeKey)
    if (!isInWindow(quote.at, this.rules.detectStart, this.rules.detectEnd)) {
      if (isInWindow(quote.at, PREOPEN_CANDIDATE_START, beforeWindow(this.rules.detectStart))) {
        const preopenCandidate = this.evaluatePreopenCandidate(quote, baseline)
        if (preopenCandidate?.triggered) {
          this.activeSignals.set(activeKey, preopenCandidate)
          return preopenCandidate
        }
        return preopenCandidate
      }
      const update = activeSignal ? this.evaluateIntradayUpdate(quote, activeSignal) : null
      if (update) {
        this.activeSignals.set(activeKey, update)
        return update
      }
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
    const volume = normalizeNumber(quote.volume)
    const amountDelta = amount - baseline.auctionAmount
    const limitDistancePct = quote.limitUpPrice && quote.limitUpPrice > 0
      ? (quote.limitUpPrice - quote.lastPrice) / quote.limitUpPrice * 100
      : undefined
    const previousWeakScore = normalizeNumber(quote.previousWeakScore)
    const previousWeakPrecondition = previousWeakScore >= this.rules.previousWeakScoreMin
    const weakPrecondition =
      atMost(auctionPct, this.rules.auctionWeakMaxPct) ||
      (officialOpenPct !== undefined && atMost(officialOpenPct, this.rules.auctionWeakMaxPct)) ||
      previousWeakPrecondition

    const strongOpenCandidate =
      firstWindowPct >= this.rules.strongOpenFirstWindowMinPct &&
      limitDistancePct !== undefined &&
      limitDistancePct <= this.rules.nearLimitDistancePct

    const auctionProfile = baseline.auctionProfile
    const hasAuctionProfile = Boolean(auctionProfile?.initialAt && auctionProfile.finalAt)
    const priceVolumeConfirmed = auctionProfile?.priceVolumeConfirmed === true
    let variant: OpeningWeakToStrongVariant | null = null
    if (strongOpenCandidate) {
      variant = 'strong_open_board_attempt'
    }
    if (
      !variant &&
      auctionProfile?.lateLiftConfirmed &&
      firstWindowPct >= this.rules.auctionLateLiftFirstWindowMinPct &&
      jumpPctPoint >= this.rules.auctionLateLiftJumpMinPctPoint
    ) {
      variant = 'auction_late_lift'
    }
    if (
      !variant &&
      atMost(auctionPct, this.rules.auctionWeakMaxPct) &&
      jumpPctPoint >= this.rules.auctionGapJumpMinPctPoint &&
      firstWindowPct >= this.rules.auctionGapFirstWindowMinPct
    ) {
      variant = 'auction_gap_reversal'
    }
    if (
      !variant &&
      (atMost(auctionPct, this.rules.auctionWeakMaxPct) ||
        (officialOpenPct !== undefined && atMost(officialOpenPct, this.rules.auctionWeakMaxPct))) &&
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
      previousWeakScore,
      previousWeakSignals: quote.previousWeakSignals,
      previousWeakSource: quote.previousWeakSource,
      rules: this.rules,
    })
    const quality = openingQuality(quote, baseline, this.rules)
    const riskKeys = [...(auctionProfile?.riskFlags || []), ...quality.riskKeys]
    if (amount < this.rules.openingLiquidityMinAmount) riskKeys.push('opening_amount_too_small')
    if (officialOpen > 0 && quote.lastPrice < Math.max(quote.preClose, officialOpen * this.rules.openingSupportOpenRatio)) {
      riskKeys.push('opening_support_lost')
    }
    if (strongOpenCandidate && !weakPrecondition) riskKeys.push('weak_precondition_missing')
    if (!hasAuctionProfile) {
      if (!auctionProfile) riskKeys.push('auction_profile_missing')
      else if (!auctionProfile.initialAt) riskKeys.push('auction_initial_baseline_missing')
      else riskKeys.push('auction_profile_missing')
    } else if (!priceVolumeConfirmed) {
      riskKeys.push('auction_price_volume_unverified')
    }
    if (baseline.auctionAmount <= 0) riskKeys.push('auction_amount_missing')
    else if (amount < baseline.auctionAmount) riskKeys.push('amount_regressed')
    if (volume > 0 && volume < this.rules.minCurrentVolume) riskKeys.push('low_liquidity_jump')
    const riskFlags = uniqueStrings(riskKeys).map(riskFlag)
    const riskPenalty = totalRiskPenalty(riskFlags)
    const score = clampScore(factors.reduce((sum, item) => sum + item.score, 0) - riskPenalty)
    const confidence = score >= 80 ? 'critical' : score >= 60 ? 'strong' : 'watch'
    const liquidityReview = liquidityReviewFields(amount, volume, this.rules)

    const signal: OpeningWeakToStrongSignal = {
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
      initialBaselineAt: auctionProfile?.initialAt,
      initialBaselinePrice: auctionProfile?.initialPrice,
      initialBaselinePct: auctionProfile?.initialPct,
      initialBaselineAmount: auctionProfile?.initialAmount,
      lateBaselineAt: auctionProfile?.lateAt,
      lateBaselinePrice: auctionProfile?.latePrice,
      lateBaselinePct: auctionProfile?.lateStartPct,
      lateBaselineAmount: auctionProfile?.lateAmount,
      finalBaselineAt: auctionProfile?.finalAt,
      finalBaselinePrice: auctionProfile?.finalPrice,
      finalBaselinePct: auctionProfile?.finalPct,
      finalBaselineAmount: auctionProfile?.finalAmount,
      auctionPriceLiftPctPoint: auctionProfile?.totalLiftPctPoint,
      latePriceLiftPctPoint: auctionProfile?.lateLiftPctPoint,
      auctionAmountDelta: auctionProfile?.amountDelta,
      lateAmountDelta: auctionProfile?.lateAmountDelta,
      auctionAmountLiftRatio: auctionProfile?.amountLiftRatio,
      lateAmountLiftRatio: auctionProfile?.lateAmountLiftRatio,
      priceVolumeConfirmed,
      liquidityTier: liquidityReview.tier,
      liquidityTierMode: 'review_only',
      liquidityTierBasis: liquidityReview.basis,
      liquidityTierThresholds: liquidityReview.thresholds,
      liquidityTierVersion: LIQUIDITY_TIER_VERSION,
      limitDistancePct: limitDistancePct === undefined ? undefined : round2(limitDistancePct),
      triggerAt: quote.at,
      baselineQuality: baseline.quality,
      auctionCapturedAt: baseline.capturedAt,
      bridgeTs: baseline.bridgeTs,
      quoteCapturedAt: quote.capturedAt || quote.bridgeTs || quote.at,
      auctionSampleCount: baseline.sampleCount,
      quoteAgeMs: ageMs(quote.capturedAt || quote.bridgeTs || quote.at, quote.at),
      latencyMs: ageMs(baseline.capturedAt, quote.at),
      openingForcedSample: baseline.openingForcedSample,
      requestedCount: baseline.requestedCount,
      receivedCount: baseline.receivedCount,
      elapsedMs: baseline.elapsedMs,
      slowBatches: baseline.slowBatches,
      truncatedBatches: baseline.truncatedBatches,
      previousWeakScore: quote.previousWeakScore,
      previousWeakSignals: quote.previousWeakSignals,
      previousWeakSource: quote.previousWeakSource,
      auctionCoverageRatio: quality.auctionCoverageRatio,
      intradayStatus: 'pending',
      intradayOutcome: 'pending',
      intradayStatusAt: quote.at,
      intradayPrice: quote.lastPrice,
      intradayPct: round2(firstWindowPct),
      intradayAmount: amount,
      intradayNote: '09:30-09:35已触发，等待盘中确认',
      dryRun: quote.dryRun || quality.dryRun,
      factors,
      riskFlags,
      ruleVersion: this.ruleVersion,
      configHash: configHash(this.rules),
    }
    this.activeSignals.set(activeKey, signal)
    return signal
  }

  private evaluatePreopenCandidate(
    quote: OpeningWeakToStrongQuote,
    baseline: OpeningWeakToStrongBaseline | null,
  ): OpeningWeakToStrongSignal {
    if (!baseline) return this.rejected(quote, null, 'baseline_missing')
    if (!isValidPrice(quote.lastPrice) || !isValidPrice(quote.preClose)) {
      return this.rejected(quote, baseline, 'invalid_price')
    }

    const auctionProfile = baseline.auctionProfile
    const hasAuctionFinal = isValidPrice(baseline.auctionFinalPrice)
    if (!hasAuctionFinal) {
      return this.rejected(quote, baseline, 'preopen_candidate_unconfirmed')
    }

    const quality = openingQuality(quote, baseline, this.rules)
    const priceVolumeConfirmed = auctionProfile?.priceVolumeConfirmed === true
    const previousWeakScore = normalizeNumber(quote.previousWeakScore)
    const weakAuctionBaseline =
      atMost(baseline.auctionPct, this.rules.auctionWeakMaxPct) ||
      previousWeakScore >= this.rules.previousWeakScoreMin
    const hasPreopenContext =
      baseline.auctionAmount >= this.rules.openingLiquidityMinAmount ||
      previousWeakScore >= this.rules.previousWeakScoreMin
    if (!priceVolumeConfirmed && (!weakAuctionBaseline || !hasPreopenContext)) {
      return this.rejected(quote, baseline, 'preopen_candidate_unconfirmed')
    }

    const riskKeys = [...(auctionProfile?.riskFlags ?? []), ...quality.riskKeys]
    if (!priceVolumeConfirmed) riskKeys.push('auction_price_volume_unverified')
    if (baseline.auctionAmount <= 0) riskKeys.push('auction_amount_missing')
    const riskFlags = uniqueStrings(riskKeys).map(riskFlag)

    const auctionPct = baseline.auctionPct
    const amount = baseline.auctionAmount
    const volume = normalizeNumber(quote.volume)
    const auctionAmountDelta = auctionProfile?.amountDelta ?? 0
    const variant: OpeningWeakToStrongVariant = priceVolumeConfirmed ? 'auction_late_lift' : 'auction_gap_reversal'
    const jumpPctPoint = priceVolumeConfirmed ? auctionProfile?.totalLiftPctPoint ?? 0 : 0
    const factors = buildFactors({
      variant,
      jumpPctPoint,
      firstWindowPct: auctionPct,
      amount,
      amountDelta: auctionAmountDelta,
      baselineQuality: baseline.quality,
      auctionProfile,
      previousWeakScore: normalizeNumber(quote.previousWeakScore),
      previousWeakSignals: quote.previousWeakSignals,
      previousWeakSource: quote.previousWeakSource,
      rules: this.rules,
    })
    const riskPenalty = totalRiskPenalty(riskFlags)
    const score = clampScore(factors.reduce((sum, item) => sum + item.score, 0) - riskPenalty)
    const confidence = score >= 80 ? 'critical' : score >= 60 ? 'strong' : 'watch'
    const liquidityReview = liquidityReviewFields(amount, volume, this.rules)

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
      firstWindowPrice: baseline.auctionFinalPrice,
      firstWindowPct: round2(auctionPct),
      jumpPctPoint: round2(jumpPctPoint),
      amount,
      amountDelta: auctionAmountDelta,
      initialBaselineAt: auctionProfile?.initialAt,
      initialBaselinePrice: auctionProfile?.initialPrice,
      initialBaselinePct: auctionProfile?.initialPct,
      initialBaselineAmount: auctionProfile?.initialAmount,
      lateBaselineAt: auctionProfile?.lateAt,
      lateBaselinePrice: auctionProfile?.latePrice,
      lateBaselinePct: auctionProfile?.lateStartPct,
      lateBaselineAmount: auctionProfile?.lateAmount,
      finalBaselineAt: auctionProfile?.finalAt,
      finalBaselinePrice: auctionProfile?.finalPrice,
      finalBaselinePct: auctionProfile?.finalPct,
      finalBaselineAmount: auctionProfile?.finalAmount,
      auctionPriceLiftPctPoint: auctionProfile?.totalLiftPctPoint,
      latePriceLiftPctPoint: auctionProfile?.lateLiftPctPoint,
      auctionAmountDelta: auctionProfile?.amountDelta,
      lateAmountDelta: auctionProfile?.lateAmountDelta,
      auctionAmountLiftRatio: auctionProfile?.amountLiftRatio,
      lateAmountLiftRatio: auctionProfile?.lateAmountLiftRatio,
      priceVolumeConfirmed,
      liquidityTier: liquidityReview.tier,
      liquidityTierMode: 'review_only',
      liquidityTierBasis: liquidityReview.basis,
      liquidityTierThresholds: liquidityReview.thresholds,
      liquidityTierVersion: LIQUIDITY_TIER_VERSION,
      triggerAt: quote.at,
      baselineQuality: baseline.quality,
      auctionCapturedAt: baseline.capturedAt,
      bridgeTs: baseline.bridgeTs,
      quoteCapturedAt: quote.capturedAt || quote.bridgeTs || quote.at,
      auctionSampleCount: baseline.sampleCount,
      quoteAgeMs: ageMs(quote.capturedAt || quote.bridgeTs || quote.at, quote.at),
      latencyMs: ageMs(baseline.capturedAt, quote.at),
      openingForcedSample: baseline.openingForcedSample,
      requestedCount: baseline.requestedCount,
      receivedCount: baseline.receivedCount,
      elapsedMs: baseline.elapsedMs,
      slowBatches: baseline.slowBatches,
      truncatedBatches: baseline.truncatedBatches,
      previousWeakScore: quote.previousWeakScore,
      previousWeakSignals: quote.previousWeakSignals,
      previousWeakSource: quote.previousWeakSource,
      auctionCoverageRatio: quality.auctionCoverageRatio,
      intradayStatus: 'preopen_candidate',
      intradayOutcome: 'preopen_candidate',
      intradayStatusAt: quote.at,
      intradayPrice: baseline.auctionFinalPrice,
      intradayPct: round2(auctionPct),
      intradayAmount: amount,
      intradayNote: priceVolumeConfirmed
        ? '竞价量价齐升，等待开盘承接验证'
        : '09:25基准偏弱，等待09:30强跳变验证',
      dryRun: quote.dryRun || quality.dryRun,
      factors,
      riskFlags,
      ruleVersion: this.ruleVersion,
      configHash: configHash(this.rules),
    }
  }

  private evaluateIntradayUpdate(
    quote: OpeningWeakToStrongQuote,
    activeSignal: OpeningWeakToStrongSignal,
  ): OpeningWeakToStrongSignal | null {
    if (!isInWindow(quote.at, afterWindow(this.rules.detectEnd), INTRADAY_CONFIRM_END)) return null
    if (!isValidPrice(quote.lastPrice) || !isValidPrice(quote.preClose)) return null
    if (activeSignal.intradayStatus === 'failed') return null

    const intradayPct = pct(quote.lastPrice, quote.preClose)
    const officialOpen = normalizeNumber(activeSignal.officialOpen || quote.open)
    const support = Math.max(
      quote.preClose,
      officialOpen > 0 ? officialOpen * this.rules.openingSupportOpenRatio : 0,
    )
    const amount = normalizeNumber(quote.amount)
    if (quote.lastPrice < support) {
      return {
        ...activeSignal,
        confidence: 'watch',
        score: Math.min(activeSignal.score, 10),
        firstWindowPrice: activeSignal.firstWindowPrice,
        firstWindowPct: activeSignal.firstWindowPct,
        amount,
        intradayStatus: 'failed',
        intradayOutcome: 'failed_open_dump',
        intradayStatusAt: quote.at,
        intradayPrice: quote.lastPrice,
        intradayPct: round2(intradayPct),
        intradayAmount: amount,
        intradayNote: '跌破开盘/昨收支撑，疑似竞价诱多',
        riskFlags: mergeRiskFlags(activeSignal.riskFlags, [riskFlag('intraday_open_dump')]),
      }
    }

    const confirmPct = Math.max(
      normalizeNumber(activeSignal.firstWindowPct) + INTRADAY_CONFIRM_ADVANCE_PCT_POINT,
      normalizeNumber(activeSignal.officialOpenPct),
      normalizeNumber(activeSignal.auctionPct),
    )
    if (activeSignal.intradayStatus === 'pending' && intradayPct >= confirmPct && quote.lastPrice >= support) {
      return {
        ...activeSignal,
        amount,
        confidence: activeSignal.confidence === 'watch' ? 'strong' : activeSignal.confidence,
        score: Math.max(activeSignal.score, 60),
        intradayStatus: 'confirmed',
        intradayOutcome: 'confirmed_strong',
        intradayStatusAt: quote.at,
        intradayPrice: quote.lastPrice,
        intradayPct: round2(intradayPct),
        intradayAmount: amount,
        intradayNote: '09:35后继续上攻并站稳，盘中确认成功',
      }
    }

    return null
  }

  private rejected(
    quote: OpeningWeakToStrongQuote,
    baseline: OpeningWeakToStrongBaseline | null,
    invalidReason: string,
  ): OpeningWeakToStrongSignal {
    const liquidityReview = liquidityReviewFields(
      normalizeNumber(quote.amount),
      normalizeNumber(quote.volume),
      this.rules,
    )
    return {
      triggered: false,
      signalType: SIGNAL_TYPE,
      displayName: DISPLAY_NAME,
      code: quote.code,
      name: quote.name || baseline?.name || quote.code,
      score: 0,
      amount: normalizeNumber(quote.amount),
      liquidityTier: liquidityReview.tier,
      liquidityTierMode: 'review_only',
      liquidityTierBasis: liquidityReview.basis,
      liquidityTierThresholds: liquidityReview.thresholds,
      liquidityTierVersion: LIQUIDITY_TIER_VERSION,
      triggerAt: quote.at,
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
      dryRun: quote.dryRun,
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
  previousWeakScore: number
  previousWeakSignals?: string[]
  previousWeakSource?: string
  rules: OpeningWeakToStrongRules
}): OpeningWeakToStrongFactor[] {
  const factors: OpeningWeakToStrongFactor[] = []
  const r = input.rules
  if (input.variant === 'auction_late_lift') {
    factors.push({
      key: 'auctionLateLift',
      value: round2(input.auctionProfile?.totalLiftPctPoint ?? 0),
      threshold: r.auctionPriceLiftMinPctPoint,
      score: r.auctionLateLiftCoreScore,
    })
    factors.push({
      key: 'auctionAmountLiftRatio',
      value: round2(input.auctionProfile?.amountLiftRatio ?? 0),
      threshold: r.auctionAmountLiftMinRatio,
      score: r.auctionLateLiftAmountRatioScore,
    })
    factors.push({
      key: 'openStrength',
      value: round2(input.firstWindowPct),
      threshold: r.auctionLateLiftFirstWindowMinPct,
      score: r.auctionLateLiftOpenStrengthScore,
    })
  } else if (input.variant === 'strong_open_board_attempt') {
    factors.push({
      key: 'nearLimit',
      value: round2(input.limitDistancePct ?? 99),
      threshold: r.nearLimitDistancePct,
      score: r.strongOpenNearLimitScore,
    })
    factors.push({
      key: 'openStrength',
      value: round2(input.firstWindowPct),
      threshold: r.strongOpenFirstWindowMinPct,
      score: r.strongOpenOpenStrengthScore,
    })
  } else if (input.variant === 'auction_gap_reversal') {
    factors.push({
      key: 'auctionGap',
      value: round2(input.jumpPctPoint),
      threshold: r.auctionGapJumpMinPctPoint,
      score: Math.min(r.auctionGapMaxScore, 20 + input.jumpPctPoint * r.auctionGapScoreSlope),
    })
    factors.push({
      key: 'openStrength',
      value: round2(input.firstWindowPct),
      threshold: r.auctionGapFirstWindowMinPct,
      score: r.auctionGapOpenStrengthScore,
    })
  } else {
    factors.push({
      key: 'redReversal',
      value: round2(input.jumpPctPoint),
      threshold: r.lowOpenRedJumpMinPctPoint,
      score: r.lowOpenRedReversalScore,
    })
    factors.push({
      key: 'turnRed',
      value: round2(input.firstWindowPct),
      threshold: r.lowOpenRedFirstWindowMinPct,
      score: r.lowOpenTurnRedScore,
    })
  }

  factors.push({
    key: 'openingAmount',
    value: input.amount,
    threshold: r.openingLiquidityMinAmount,
    score: input.amount >= r.minCurrentAmount || input.amountDelta >= r.minAmountDelta
      ? r.auctionGapAmountStrongScore
      : r.auctionGapAmountWeakScore,
  })
  factors.push({
    key: 'baselineQuality',
    value: input.baselineQuality,
    score: input.baselineQuality === 'good' ? r.auctionGapQualityGoodScore : r.auctionGapQualityDegradedScore,
  })
  if (input.previousWeakScore >= r.previousWeakScoreMin) {
    factors.push({
      key: 'previousWeakContext',
      value: input.previousWeakScore,
      threshold: r.previousWeakScoreMin,
      score: r.previousWeakContextScore,
    })
    if (input.previousWeakSource) {
      factors.push({
        key: 'previousWeakSource',
        value: input.previousWeakSource,
        score: 0,
      })
    }
  }
  return factors
}

function riskFlag(key: string): OpeningWeakToStrongRiskFlag {
  const high = key === 'baseline_missing'
  const profileRelated =
    key === 'auction_profile_missing' ||
    key === 'auction_initial_baseline_missing' ||
    key === 'auction_price_volume_unverified'
  const coverageRelated =
    key === 'auction_coverage_low' ||
    key === 'auction_amount_missing' ||
    key === 'amount_regressed'
  return {
    key,
    severity: high ? 'high' : profileRelated || coverageRelated ? 'low' : 'medium',
    penalty: high ? -100 : profileRelated ? -10 : coverageRelated ? -5 : -35,
  }
}

function mergeRiskFlags(
  existing: OpeningWeakToStrongRiskFlag[],
  added: OpeningWeakToStrongRiskFlag[],
): OpeningWeakToStrongRiskFlag[] {
  const byKey = new Map<string, OpeningWeakToStrongRiskFlag>()
  for (const flag of existing) byKey.set(flag.key, flag)
  for (const flag of added) byKey.set(flag.key, flag)
  return [...byKey.values()]
}

function totalRiskPenalty(riskFlags: OpeningWeakToStrongRiskFlag[]): number {
  const groups = new Map<string, number>()
  for (const flag of riskFlags) {
    const group = riskPenaltyGroup(flag.key)
    groups.set(group, Math.max(groups.get(group) || 0, Math.abs(flag.penalty)))
  }
  return [...groups.values()].reduce((sum, value) => sum + value, 0)
}

function riskPenaltyGroup(key: string): string {
  if (
    key === 'auction_price_volume_desynced' ||
    key === 'auction_price_volume_unverified' ||
    key === 'price_lift_without_volume' ||
    key === 'volume_without_price_lift' ||
    key === 'auction_late_high_retreated'
  ) {
    return 'auction_price_volume'
  }
  return key
}

function openingQuality(
  quote: OpeningWeakToStrongQuote,
  baseline: OpeningWeakToStrongBaseline,
  rules: OpeningWeakToStrongRules,
): { riskKeys: string[]; auctionCoverageRatio?: number; dryRun: boolean } {
  const riskKeys: string[] = []
  const requested = normalizeNumber(baseline.requestedCount)
  const received = normalizeNumber(baseline.receivedCount)
  const auctionCoverageRatio = requested > 0 ? received / requested : undefined
  if (auctionCoverageRatio !== undefined && auctionCoverageRatio < rules.minAuctionCoverageRatio) {
    riskKeys.push('auction_coverage_low')
  }
  const quoteAge = ageMs(quote.capturedAt || quote.bridgeTs || quote.at, quote.at)
  if (quoteAge !== undefined && quoteAge > rules.maxQuoteAgeMs) riskKeys.push('quote_time_untrusted')
  if (!isInWindow(baseline.capturedAt, rules.auctionStart, rules.auctionEnd)) {
    riskKeys.push('auction_time_untrusted')
  }
  return {
    riskKeys,
    auctionCoverageRatio: auctionCoverageRatio === undefined ? undefined : round2(auctionCoverageRatio),
    dryRun: riskKeys.includes('quote_time_untrusted') ||
      riskKeys.includes('auction_time_untrusted'),
  }
}

function liquidityReviewFields(
  amount: number,
  volume: number,
  rules: OpeningWeakToStrongRules,
): { tier: OpeningLiquidityTier; basis: string; thresholds: string } {
  return {
    tier: liquidityTier(amount, volume, rules),
    basis: `amount=${amount};volume=${volume}`,
    thresholds:
      `openingLiquidityMinAmount=${rules.openingLiquidityMinAmount};` +
      `minCurrentAmount=${rules.minCurrentAmount};hotAmount=${HOT_AMOUNT};` +
      `minCurrentVolume=${rules.minCurrentVolume}`,
  }
}

function liquidityTier(amount: number, volume: number, rules: OpeningWeakToStrongRules): OpeningLiquidityTier {
  if (!Number.isFinite(amount) || amount <= 0) return 'unknown'
  if (amount < rules.openingLiquidityMinAmount || (volume > 0 && volume < rules.minCurrentVolume)) {
    return 'thin'
  }
  if (amount >= HOT_AMOUNT) return 'hot'
  if (amount >= rules.minCurrentAmount) return 'active'
  return 'normal'
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

  const initial = trusted.find(item => isInWindow(item.at, rules.initialBaselineStart, rules.initialBaselineEnd))
  const finalSamples = trusted.filter(item => isInWindow(item.at, rules.auctionStart, rules.auctionEnd))
  const final = finalSamples[finalSamples.length - 1] || trusted[trusted.length - 1]
  const lateSamples = trusted.filter(item => secondsOfDay(item.at) >= secondsOfDay(rules.auctionLateLiftStart))
  const lateStart = lateSamples[0] || final
  const startPct = initial ? pct(initial.lastPrice, initial.preClose) : undefined
  const lateStartPct = pct(lateStart.lastPrice, lateStart.preClose)
  const finalPct = pct(final.lastPrice, final.preClose)
  const highPct = Math.max(...trusted.map(item => pct(item.lastPrice, item.preClose)))
  const totalLiftPctPoint = startPct === undefined ? undefined : finalPct - startPct
  const lateLiftPctPoint = finalPct - lateStartPct
  const initialAmount = initial ? normalizeNumber(initial.amount) : undefined
  const finalAmount = normalizeNumber(final.amount)
  const lateStartAmount = normalizeNumber(lateStart.amount)
  const amountDelta = initialAmount === undefined ? undefined : finalAmount - initialAmount
  const lateAmountDelta = normalizeNumber(final.amount) - normalizeNumber(lateStart.amount)
  const amountLiftRatio = ratioFromBase(amountDelta, initialAmount)
  const lateAmountLiftRatio = ratioFromBase(lateAmountDelta, lateStartAmount)
  const totalPriceLifted =
    totalLiftPctPoint !== undefined && meets(totalLiftPctPoint, rules.auctionPriceLiftMinPctPoint)
  const latePriceLifted = meets(lateLiftPctPoint, rules.auctionLatePriceLiftMinPctPoint)
  const totalAmountExpanded =
    amountLiftRatio !== undefined && meets(amountLiftRatio, rules.auctionAmountLiftMinRatio)
  const lateAmountExpanded =
    lateAmountLiftRatio !== undefined && meets(lateAmountLiftRatio, rules.auctionLateAmountLiftMinRatio)
  const priceLifted = totalPriceLifted || latePriceLifted
  const amountExpanded = totalAmountExpanded || lateAmountExpanded
  const highRetreated = meets(highPct - finalPct, rules.auctionLateHighRetreatPctPoint)
  const riskFlags: string[] = []
  if (initial && priceLifted && !amountExpanded) riskFlags.push('auction_price_volume_desynced')
  if (initial && amountExpanded && !priceLifted) riskFlags.push('auction_price_volume_desynced')
  if (priceLifted && !amountExpanded) riskFlags.push('price_lift_without_volume')
  if (amountExpanded && !priceLifted) riskFlags.push('volume_without_price_lift')
  if (highRetreated) riskFlags.push('auction_late_high_retreated')

  return {
    sampleCount: trusted.length,
    initialAt: initial?.at,
    initialPrice: initial?.lastPrice,
    initialPct: startPct === undefined ? undefined : round2(startPct),
    initialAmount,
    lateAt: lateStart.at,
    latePrice: lateStart.lastPrice,
    lateAmount: lateStartAmount,
    finalAt: final.at,
    finalPrice: final.lastPrice,
    finalAmount,
    startPct: startPct === undefined ? undefined : round2(startPct),
    lateStartPct: round2(lateStartPct),
    finalPct: round2(finalPct),
    highPct: round2(highPct),
    totalLiftPctPoint: totalLiftPctPoint === undefined ? undefined : round2(totalLiftPctPoint),
    lateLiftPctPoint: round2(lateLiftPctPoint),
    amountDelta,
    lateAmountDelta,
    amountLiftRatio: amountLiftRatio === undefined ? undefined : round2(amountLiftRatio),
    lateAmountLiftRatio: lateAmountLiftRatio === undefined ? undefined : round2(lateAmountLiftRatio),
    priceVolumeConfirmed:
      Boolean(initial) &&
      totalPriceLifted &&
      totalAmountExpanded &&
      latePriceLifted &&
      lateAmountExpanded &&
      !highRetreated,
    lateLiftConfirmed:
      Boolean(initial) &&
      totalPriceLifted &&
      totalAmountExpanded &&
      latePriceLifted &&
      lateAmountExpanded &&
      !highRetreated,
    riskFlags,
  }
}

function ratioFromBase(delta: number | undefined, base: number | undefined): number | undefined {
  if (delta === undefined || base === undefined || base <= 0) return undefined
  return delta / base
}

function countAuctionBaselineSamples(samples: OpeningWeakToStrongQuote[], rules: OpeningWeakToStrongRules): number {
  return samples.filter(item => isInWindow(item.at, rules.auctionStart, rules.auctionEnd)).length
}

function meets(value: number, threshold: number): boolean {
  return value + 1e-6 >= threshold
}

function atMost(value: number, threshold: number): boolean {
  return value <= threshold + 1e-6
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
  if (!match) {
    console.warn(`[OpeningWeakToStrong] unparseable timestamp, defaulting to 00:00:00: "${value}"`)
    return 0
  }
  let hours = Number(match[1])
  if (/[zZ]$/.test(value)) hours = (hours + 8) % 24
  return hours * 3600 + Number(match[2]) * 60 + Number(match[3])
}

function afterWindow(value: string): string {
  const seconds = Math.min(24 * 3600 - 1, secondsOfDay(value) + 1)
  const hour = Math.floor(seconds / 3600)
  const minute = Math.floor((seconds % 3600) / 60)
  const second = seconds % 60
  return [hour, minute, second].map(item => String(item).padStart(2, '0')).join(':')
}

function beforeWindow(value: string): string {
  const seconds = Math.max(0, secondsOfDay(value) - 1)
  const hour = Math.floor(seconds / 3600)
  const minute = Math.floor((seconds % 3600) / 60)
  const second = seconds % 60
  return [hour, minute, second].map(item => String(item).padStart(2, '0')).join(':')
}

function compareQuoteFreshness(quote: OpeningWeakToStrongQuote, baselineCapturedAt: string): number {
  return Date.parse(quote.capturedAt || quote.at) - Date.parse(baselineCapturedAt)
}

function ageMs(from: string | undefined, to: string): number | undefined {
  if (!from) return undefined
  const elapsed = Date.parse(to) - Date.parse(from)
  return Number.isFinite(elapsed) ? Math.max(0, elapsed) : undefined
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values)]
}

function round2(value: number): number {
  return Math.round(value * 100) / 100
}

function clampScore(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value)))
}

function configHash(rules: OpeningWeakToStrongRules): string {
  const hashKeys: (keyof OpeningWeakToStrongRules)[] = [
    'auctionEnd',
    'auctionGapFirstWindowMinPct',
    'auctionGapJumpMinPctPoint',
    'auctionAmountLiftMinRatio',
    'auctionLateHighRetreatPctPoint',
    'auctionLateLiftFinalMinPct',
    'auctionLateLiftFirstWindowMinPct',
    'auctionLateLiftJumpMinPctPoint',
    'auctionLateLiftStart',
    'auctionLateLiftTotalMinPctPoint',
    'auctionLateAmountLiftMinRatio',
    'auctionLatePriceLiftMinPctPoint',
    'auctionPriceLiftMinPctPoint',
    'auctionStart',
    'auctionTrendStart',
    'auctionWeakMaxPct',
    'detectEnd',
    'detectStart',
    'initialBaselineEnd',
    'initialBaselineStart',
    'lowOpenRedFirstWindowMinPct',
    'lowOpenRedJumpMinPctPoint',
    'minAmountDelta',
    'maxQuoteAgeMs',
    'minAuctionCoverageRatio',
    'minCurrentAmount',
    'minCurrentVolume',
    'nearLimitDistancePct',
    'openingLiquidityMinAmount',
    'openingSupportOpenRatio',
    'previousWeakScoreMin',
    'strongOpenFirstWindowMinPct',
    'auctionGapMaxScore',
    'auctionGapScoreSlope',
    'auctionGapOpenStrengthScore',
    'auctionGapAmountStrongScore',
    'auctionGapAmountWeakScore',
    'auctionGapQualityGoodScore',
    'auctionGapQualityDegradedScore',
    'auctionLateLiftCoreScore',
    'auctionLateLiftAmountRatioScore',
    'auctionLateLiftOpenStrengthScore',
    'strongOpenNearLimitScore',
    'strongOpenOpenStrengthScore',
    'lowOpenRedReversalScore',
    'lowOpenTurnRedScore',
    'previousWeakContextScore',
  ].sort()
  const hashRules = Object.fromEntries(hashKeys.map((key) => [key, rules[key]]))
  const json = JSON.stringify(hashRules)
  let hash = 2166136261
  for (let index = 0; index < json.length; index++) {
    hash ^= json.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return `owts-${(hash >>> 0).toString(16).padStart(8, '0')}`
}
