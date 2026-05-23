export type OpeningWeakToStrongVariant =
  | 'auction_gap_reversal'
  | 'low_open_red_reversal'
  | 'strong_open_board_attempt'
  | 'auction_late_lift'

export type OpeningWeakToStrongConfidence = 'watch' | 'strong' | 'critical'
export type OpeningBaselineQuality = 'good' | 'degraded' | 'missing'

export interface OpeningWeakToStrongRules {
  auctionTrendStart: string
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
  auctionLateLiftStart: string
  auctionLateLiftTotalMinPctPoint: number
  auctionLateLiftLateMinPctPoint: number
  auctionLateLiftFinalMinPct: number
  auctionLateLiftAmountDeltaMin: number
  auctionLateLiftLateAmountDeltaMin: number
  auctionLateLiftFirstWindowMinPct: number
  auctionLateLiftJumpMinPctPoint: number
  auctionLateHighRetreatPctPoint: number
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
  auctionProfile?: OpeningAuctionPriceVolumeProfile
}

export interface OpeningAuctionPriceVolumeProfile {
  sampleCount: number
  startPct?: number
  lateStartPct?: number
  finalPct?: number
  highPct?: number
  totalLiftPctPoint?: number
  lateLiftPctPoint?: number
  amountDelta?: number
  lateAmountDelta?: number
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
  limitDistancePct?: number
  triggerAt: string
  baselineQuality: OpeningBaselineQuality
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
    invalidReason?: string
  }
}

export interface OpeningWeakToStrongFixture {
  schemaVersion: number
  ruleVersion: string
  rules: OpeningWeakToStrongRules
  cases: OpeningWeakToStrongFixtureCase[]
}
