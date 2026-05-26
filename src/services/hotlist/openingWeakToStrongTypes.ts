export type OpeningWeakToStrongVariant =
  | 'auction_gap_reversal'
  | 'low_open_red_reversal'
  | 'strong_open_board_attempt'
  | 'auction_late_lift'

export type OpeningWeakToStrongConfidence = 'watch' | 'strong' | 'critical'
export type OpeningBaselineQuality = 'good' | 'degraded' | 'missing'
export type OpeningLiquidityTier = 'unknown' | 'thin' | 'normal' | 'active' | 'hot'
export type OpeningLiquidityTierMode = 'review_only'
export type OpeningIntradayStatus =
  | 'preopen_candidate'
  | 'pending'
  | 'confirmed'
  | 'failed'
  | 'watch'
export type OpeningIntradayOutcome =
  | 'preopen_candidate'
  | 'pending'
  | 'confirmed_strong'
  | 'failed_open_dump'
  | 'watch_only'

export interface OpeningWeakToStrongRules {
  auctionTrendStart: string
  initialBaselineStart: string
  initialBaselineEnd: string
  auctionStart: string
  auctionEnd: string
  detectStart: string
  detectEnd: string
  auctionWeakMaxPct: number
  auctionGapJumpMinPctPoint: number
  auctionGapFirstWindowMinPct: number
  lowOpenRedJumpMinPctPoint: number
  lowOpenRedFirstWindowMinPct: number
  strongOpenFirstWindowMinPct: number
  nearLimitDistancePct: number
  minCurrentAmount: number
  minAmountDelta: number
  openingLiquidityMinAmount: number
  auctionLateLiftStart: string
  auctionLateLiftTotalMinPctPoint: number
  auctionLateLiftLateMinPctPoint: number
  auctionPriceLiftMinPctPoint: number
  auctionAmountLiftMinRatio: number
  auctionLatePriceLiftMinPctPoint: number
  auctionLateAmountLiftMinRatio: number
  auctionLateLiftFinalMinPct: number
  auctionLateLiftAmountDeltaMin: number
  auctionLateLiftLateAmountDeltaMin: number
  auctionLateLiftFirstWindowMinPct: number
  auctionLateLiftJumpMinPctPoint: number
  auctionLateHighRetreatPctPoint: number
  previousWeakScoreMin: number
  minAuctionCoverageRatio: number
  maxQuoteAgeMs: number
  minCurrentVolume: number
  openingSupportOpenRatio: number
}

export interface OpeningWeakToStrongQuote {
  code: string
  name?: string
  at: string
  lastPrice: number
  preClose: number
  open?: number
  amount?: number
  volume?: number
  limitUpPrice?: number
  capturedAt?: string
  bridgeTs?: string
  openingForcedSample?: boolean
  requestedCount?: number
  receivedCount?: number
  elapsedMs?: number
  slowBatches?: number
  truncatedBatches?: number
  previousWeakScore?: number
  previousWeakSignals?: string[]
  previousWeakSource?: string
  dryRun?: boolean
}

export interface OpeningWeakToStrongBaseline {
  code: string
  tradingDate: string
  name: string
  auctionFinalPrice: number
  auctionPct: number
  auctionAmount: number
  preClose: number
  capturedAt: string
  bridgeTs?: string
  sampleCount: number
  quality: OpeningBaselineQuality
  openingForcedSample?: boolean
  requestedCount?: number
  receivedCount?: number
  elapsedMs?: number
  slowBatches?: number
  truncatedBatches?: number
  auctionProfile?: OpeningAuctionPriceVolumeProfile
}

export interface OpeningAuctionPriceVolumeProfile {
  sampleCount: number
  initialAt?: string
  initialPrice?: number
  initialPct?: number
  initialAmount?: number
  lateAt?: string
  latePrice?: number
  lateAmount?: number
  finalAt?: string
  finalPrice?: number
  finalAmount?: number
  startPct?: number
  lateStartPct?: number
  finalPct?: number
  highPct?: number
  totalLiftPctPoint?: number
  lateLiftPctPoint?: number
  amountDelta?: number
  lateAmountDelta?: number
  amountLiftRatio?: number
  lateAmountLiftRatio?: number
  priceVolumeConfirmed: boolean
  lateLiftConfirmed: boolean
  riskFlags: string[]
}

export interface OpeningWeakToStrongFactor {
  key: string
  value: number | string | boolean
  threshold?: number
  score: number
}

export interface OpeningWeakToStrongRiskFlag {
  key: string
  severity: 'low' | 'medium' | 'high'
  penalty: number
}

export interface OpeningWeakToStrongSignal {
  triggered: boolean
  signalType: 'opening_weak_to_strong'
  displayName: '竞价弱转强'
  code: string
  name: string
  variant?: OpeningWeakToStrongVariant
  confidence?: OpeningWeakToStrongConfidence
  score: number
  auctionFinalPrice?: number
  auctionPct?: number
  officialOpen?: number
  officialOpenPct?: number
  firstWindowPrice?: number
  firstWindowPct?: number
  jumpPctPoint?: number
  amount: number
  amountDelta?: number
  initialBaselineAt?: string
  initialBaselinePrice?: number
  initialBaselinePct?: number
  initialBaselineAmount?: number
  lateBaselineAt?: string
  lateBaselinePrice?: number
  lateBaselinePct?: number
  lateBaselineAmount?: number
  finalBaselineAt?: string
  finalBaselinePrice?: number
  finalBaselinePct?: number
  finalBaselineAmount?: number
  auctionPriceLiftPctPoint?: number
  latePriceLiftPctPoint?: number
  auctionAmountDelta?: number
  lateAmountDelta?: number
  auctionAmountLiftRatio?: number
  lateAmountLiftRatio?: number
  priceVolumeConfirmed?: boolean
  liquidityTier: OpeningLiquidityTier
  liquidityTierMode: OpeningLiquidityTierMode
  liquidityTierBasis: string
  liquidityTierThresholds: string
  liquidityTierVersion: string
  limitDistancePct?: number
  triggerAt: string
  baselineQuality: OpeningBaselineQuality
  auctionCapturedAt?: string
  bridgeTs?: string
  quoteCapturedAt?: string
  auctionSampleCount?: number
  quoteAgeMs?: number
  latencyMs?: number
  openingForcedSample?: boolean
  requestedCount?: number
  receivedCount?: number
  elapsedMs?: number
  slowBatches?: number
  truncatedBatches?: number
  previousWeakScore?: number
  previousWeakSignals?: string[]
  previousWeakSource?: string
  auctionCoverageRatio?: number
  intradayStatus?: OpeningIntradayStatus
  intradayOutcome?: OpeningIntradayOutcome
  intradayStatusAt?: string
  intradayPrice?: number
  intradayPct?: number
  intradayAmount?: number
  intradayNote?: string
  dryRun?: boolean
  factors: OpeningWeakToStrongFactor[]
  riskFlags: OpeningWeakToStrongRiskFlag[]
  invalidReason?: string
  ruleVersion: string
  configHash: string
}

export interface OpeningWeakToStrongFixtureCase {
  caseId: string
  description: string
  quotes: OpeningWeakToStrongQuote[]
  expected: {
    triggered: boolean
    variant?: OpeningWeakToStrongVariant
    confidence?: OpeningWeakToStrongConfidence
    scoreRange?: [number, number]
    jumpPctPointRange?: [number, number]
    riskFlags?: string[]
    dryRun?: boolean
    auctionCoverageRatio?: number
    liquidityTier?: string
    liquidityTierMode?: string
    liquidityTierBasis?: string
    liquidityTierThresholds?: string
    liquidityTierVersion?: string
    initialBaselineAt?: string
    initialBaselinePrice?: number
    initialBaselinePct?: number
    initialBaselineAmount?: number
    lateBaselineAt?: string
    lateBaselinePrice?: number
    lateBaselinePct?: number
    lateBaselineAmount?: number
    finalBaselineAt?: string
    finalBaselinePrice?: number
    finalBaselinePct?: number
    finalBaselineAmount?: number
    auctionPriceLiftPctPoint?: number
    latePriceLiftPctPoint?: number
    auctionAmountDelta?: number
    lateAmountDelta?: number
    auctionAmountLiftRatio?: number
    lateAmountLiftRatio?: number
    priceVolumeConfirmed?: boolean
    intradayStatus?: OpeningIntradayStatus
    intradayOutcome?: OpeningIntradayOutcome
    intradayStatusAt?: string
    intradayPrice?: number
    intradayPct?: number
    intradayAmount?: number
    intradayNote?: string
    invalidReason?: string
  }
}

export interface OpeningWeakToStrongFixture {
  schemaVersion: number
  ruleVersion: string
  rules: OpeningWeakToStrongRules
  cases: OpeningWeakToStrongFixtureCase[]
}
