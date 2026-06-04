import type { OpeningWeakToStrongRules } from './openingWeakToStrongTypes'

export const OPENING_WEAK_TO_STRONG_RULE_VERSION = 'opening-weak-to-strong.v1'

export const DEFAULT_OPENING_WEAK_TO_STRONG_RULES: OpeningWeakToStrongRules = {
  auctionTrendStart: '09:20:00',
  initialBaselineStart: '09:20:00',
  initialBaselineEnd: '09:20:30',
  auctionStart: '09:25:00',
  auctionEnd: '09:25:00',
  detectStart: '09:30:00',
  detectEnd: '09:35:00',
  auctionGapJumpMinPctPoint: 3,
  auctionPriceLiftMinPctPoint: 0.8,
  auctionAmountLiftMinRatio: 0.35,
}
