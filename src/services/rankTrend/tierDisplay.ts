/**
 * 档位展示投影（四维列方案 §3.3/§4.3）。
 *
 * 只消费后端已产字段（stock.rankTrend.*），缺字段返回 null（回退纯连续分展示，不渲染空徽章、
 * 不报错）。tierBadgeClass 供 DataTable 徽章样式映射。
 */

import type { RankTrendSignalTier } from './types'

export type TierDimension = 'resonance' | 'rankTrend' | 'volumePrice' | 'lifecycle' | 'synergy'

const TIER_BADGE_CLASS: Record<RankTrendSignalTier, string> = {
  S: 'tier-s',
  A: 'tier-a',
  B: 'tier-b',
  C: 'tier-c',
  D: 'tier-d',
  E: 'tier-e',
  unknown: 'tier-unknown',
}

const TIER_DISPLAY: Record<RankTrendSignalTier, string> = {
  S: 'S',
  A: 'A',
  B: 'B',
  C: 'C',
  D: 'D',
  E: 'E',
  unknown: '--',
}

function asTier(value: unknown): RankTrendSignalTier | null {
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(TIER_BADGE_CLASS, value)
    ? (value as RankTrendSignalTier)
    : null
}

/** 共振档位：stock.rankTrend.resonance.signalTier */
export function getResonanceTier(stock: unknown): RankTrendSignalTier | null {
  return asTier((stock as { rankTrend?: { resonance?: { signalTier?: unknown } } } | undefined)?.rankTrend?.resonance?.signalTier)
}

/** 趋势档位：stock.rankTrend.observation.rankTrend.signalTier */
export function getRankTrendTier(stock: unknown): RankTrendSignalTier | null {
  return asTier((stock as { rankTrend?: { observation?: { rankTrend?: { signalTier?: unknown } } } } | undefined)?.rankTrend?.observation?.rankTrend?.signalTier)
}

/** 量价档位：stock.rankTrend.observation.volumePrice.signalTier */
export function getVolumePriceTier(stock: unknown): RankTrendSignalTier | null {
  return asTier((stock as { rankTrend?: { observation?: { volumePrice?: { signalTier?: unknown } } } } | undefined)?.rankTrend?.observation?.volumePrice?.signalTier)
}

/** 周期档位：stock.rankTrend.observation.lifecycle.signalTier */
export function getLifecycleTier(stock: unknown): RankTrendSignalTier | null {
  return asTier((stock as { rankTrend?: { observation?: { lifecycle?: { signalTier?: unknown } } } } | undefined)?.rankTrend?.observation?.lifecycle?.signalTier)
}

/** 四维合并档位：stock.rankTrend.observation.synergy.signalTier（缺字段返回 null，回退纯连续分展示） */
export function getSynergyTier(stock: unknown): RankTrendSignalTier | null {
  return asTier((stock as { rankTrend?: { observation?: { synergy?: { signalTier?: unknown } } } } | undefined)?.rankTrend?.observation?.synergy?.signalTier)
}

/** 四维合并档位命中规则（悬停展示用）；非数组/缺字段回退空数组 */
export function getSynergyTierReasons(stock: unknown): string[] {
  const reasons = (stock as { rankTrend?: { observation?: { synergy?: { tierReasons?: unknown } } } } | undefined)?.rankTrend?.observation?.synergy?.tierReasons
  return Array.isArray(reasons) ? (reasons as string[]) : []
}

/** 四维合并档位明细（悬停展示）：如 ["共振 S","趋势 A","量价 B","周期 A"]，缺维显示 "-" */
export function getSynergyTierDetail(stock: unknown): string[] {
  const parts: string[] = []
  const dims: Array<[string, RankTrendSignalTier | null]> = [
    ['共振', getResonanceTier(stock)],
    ['趋势', getRankTrendTier(stock)],
    ['量价', getVolumePriceTier(stock)],
    ['周期', getLifecycleTier(stock)],
  ]
  for (const [label, tier] of dims) {
    parts.push(tier === null ? `${label} -` : `${label} ${tier}`)
  }
  return parts
}

/** 档位徽章 CSS 类（DataTable §4.4），unknown → 虚线占位 */
export function tierBadgeClass(tier: RankTrendSignalTier | null | undefined): string | null {
  if (tier === null || tier === undefined) return null
  return Object.prototype.hasOwnProperty.call(TIER_BADGE_CLASS, tier) ? TIER_BADGE_CLASS[tier] : null
}

/** 档位展示文本：unknown → '--'（不归零、不伪装，fail-visible） */
export function tierBadgeLabel(tier: RankTrendSignalTier | null | undefined): string | null {
  if (tier === null || tier === undefined) return null
  return Object.prototype.hasOwnProperty.call(TIER_DISPLAY, tier) ? TIER_DISPLAY[tier] : null
}
