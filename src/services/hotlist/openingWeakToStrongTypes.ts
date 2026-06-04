export type OpeningBaselineQuality = 'good' | 'degraded' | 'missing'
export type OpeningWatchStage =
  | 'auctionConditionPassed'
  | 'auctionConditionFailed'
  | 'gapAlert'
  | 'noGap'
  | 'trendConfirm'
  | 'trendWeak'
  | 'optionalFinalStatus'

export interface OpeningWeakToStrongRules {
  auctionTrendStart: string
  initialBaselineStart: string
  initialBaselineEnd: string
  auctionLateLiftStart: string
  auctionStart: string
  auctionEnd: string
  detectStart: string
  detectEnd: string
  openingSupportImproveMinPctPoint?: number
  openingSupportAmountMinRatio?: number
  auctionPriceLiftMinPctPoint: number
  auctionAmountLiftMinRatio: number
  auctionLatePriceLiftMinPctPoint: number
  auctionLateAmountLiftMinRatio: number
  checkpointWindowThresholdSeconds?: number
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
  lateBaselineAt?: string
  lateBaselinePrice?: number
  lateBaselinePct?: number
  lateBaselineAmount?: number
  finalAt?: string
  finalPrice?: number
  finalAmount?: number
  startPct?: number
  finalPct?: number
  totalLiftPctPoint?: number
  latePriceLiftPctPoint?: number
  amountDelta?: number
  lateAmountDelta?: number
  amountLiftRatio?: number
  lateAmountLiftRatio?: number
  priceVolumeConfirmed: boolean
}

export interface OpeningWatchSignal {
  stage: OpeningWatchStage
  status: OpeningWatchStage
  code: string
  name: string
  time: string
  price: number
  pct: number
  amount: number
  voiceEligible: boolean
  reason: string
}

export interface OpeningWeakToStrongSignal extends OpeningWatchSignal {
  triggered: boolean
  signalType: 'opening_weak_to_strong'
  displayName: '竞价弱转强'
  auctionFinalPrice?: number
  auctionPct?: number
  officialOpen?: number
  officialOpenPct?: number
  firstWindowPrice?: number
  firstWindowPct?: number
  jumpPctPoint?: number
  amountDelta?: number
  initialBaselineAt?: string
  initialBaselinePrice?: number
  initialBaselinePct?: number
  initialBaselineAmount?: number
  finalBaselineAt?: string
  finalBaselinePrice?: number
  finalBaselinePct?: number
  finalBaselineAmount?: number
  auctionPriceLiftPctPoint?: number
  auctionAmountDelta?: number
  auctionAmountLiftRatio?: number
  priceVolumeConfirmed?: boolean
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
  invalidReason?: string
  ruleVersion: string
  configHash: string
}

export interface OpeningWeakToStrongFixtureCase {
  caseId: string
  description: string
  quotes: OpeningWeakToStrongQuote[]
  expected: {
    checkpoints: Array<{
      at: '09:20' | '09:25' | '09:30' | '09:35' | '10:00'
      result: 'PASS' | 'FAIL'
      stage: OpeningWatchStage
      voiceEligible: boolean
    }>
  }
}

export interface OpeningWeakToStrongFixture {
  schemaVersion: number
  ruleVersion: string
  rules: OpeningWeakToStrongRules
  cases: OpeningWeakToStrongFixtureCase[]
}
