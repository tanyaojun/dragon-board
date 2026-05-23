import type { OpeningWeakToStrongRules } from './openingWeakToStrongTypes'

export const OPENING_WEAK_TO_STRONG_RULE_VERSION = 'opening-weak-to-strong.v1'

export const DEFAULT_OPENING_WEAK_TO_STRONG_RULES: OpeningWeakToStrongRules = {
  auctionTrendStart: '09:20:00',
  auctionStart: '09:24:50',
  auctionEnd: '09:25:10',
  detectStart: '09:30:00',
  detectEnd: '09:35:00',
  auctionWeakMaxPct: 0.5,
  auctionGapJumpMinPctPoint: 3,
  auctionGapFirstWindowMinPct: 1.5,
  lowOpenRedJumpMinPctPoint: 1.5,
  lowOpenRedFirstWindowMinPct: 1,
  strongOpenFirstWindowMinPct: 3,
  nearLimitDistancePct: 2,
  minCurrentAmount: 30_000_000,
  minAmountDelta: 20_000_000,
  auctionLateLiftStart: '09:24:00',
  auctionLateLiftTotalMinPctPoint: 1,
  auctionLateLiftLateMinPctPoint: 0.5,
  auctionLateLiftFinalMinPct: 0,
  auctionLateLiftAmountDeltaMin: 8_000_000,
  auctionLateLiftLateAmountDeltaMin: 5_000_000,
  auctionLateLiftFirstWindowMinPct: 2.5,
  auctionLateLiftJumpMinPctPoint: 2,
  auctionLateHighRetreatPctPoint: 0.2,
}
