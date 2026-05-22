import type { OpeningWeakToStrongRules } from './openingWeakToStrongTypes'

export const OPENING_WEAK_TO_STRONG_RULE_VERSION = 'opening-weak-to-strong.v1'

export const DEFAULT_OPENING_WEAK_TO_STRONG_RULES: OpeningWeakToStrongRules = {
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
}
