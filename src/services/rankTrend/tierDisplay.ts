/**
 * 档位展示投影（原四维列方案 §3.3/§4.3；现口径 5 投票维 + 1 环境门，见 docs 命名注记）。
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

/** 热度档位（技术字段 crossSection）：stock.rankTrend.observation.crossSection.signalTier（2026-08-18 第 5 维，tooltip 展示；UI 展示名「热度」） */
export function getCrossSectionTier(stock: unknown): RankTrendSignalTier | null {
  return asTier((stock as { rankTrend?: { observation?: { crossSection?: { signalTier?: unknown } } } } | undefined)?.rankTrend?.observation?.crossSection?.signalTier)
}

/** 热度明细（技术字段 crossSection）：percentile/delta/relativeToMarket（tooltip 展示；缺字段返回 null） */
export function getCrossSectionDetail(stock: unknown): string | null {
  const cs = (stock as { rankTrend?: { observation?: { crossSection?: { percentile?: unknown; percentileDelta?: unknown; relativeToMarket?: unknown } } } } | undefined)?.rankTrend?.observation?.crossSection
  if (!cs || typeof cs !== 'object') return null
  const pct = typeof cs.percentile === 'number' ? Math.round(cs.percentile) : null
  const delta = typeof cs.percentileDelta === 'number' ? Math.round(cs.percentileDelta) : null
  const rel = typeof cs.relativeToMarket === 'number' ? Math.round(cs.relativeToMarket) : null
  if (pct === null && delta === null && rel === null) return null
  return `热度 ${pct ?? '-'}/${delta ?? '-'}/${rel ?? '-'}`
}

/** synergy 合并档位：stock.rankTrend.observation.synergy.signalTier（缺字段返回 null，回退纯连续分展示） */
export function getSynergyTier(stock: unknown): RankTrendSignalTier | null {
  return asTier((stock as { rankTrend?: { observation?: { synergy?: { signalTier?: unknown } } } } | undefined)?.rankTrend?.observation?.synergy?.signalTier)
}

/** synergy 合并档位命中规则（悬停展示用）；非数组/缺字段回退空数组 */
export function getSynergyTierReasons(stock: unknown): string[] {
  const reasons = (stock as { rankTrend?: { observation?: { synergy?: { tierReasons?: unknown } } } } | undefined)?.rankTrend?.observation?.synergy?.tierReasons
  return Array.isArray(reasons) ? (reasons as string[]) : []
}

/** 五维合并档位明细（悬停展示）：如 ["共振 S","趋势 A","量价 B","周期 A","热度 B"]，缺维显示 "-" */
export function getSynergyTierDetail(stock: unknown): string[] {
  const parts: string[] = []
  const dims: Array<[string, RankTrendSignalTier | null]> = [
    ['共振', getResonanceTier(stock)],
    ['趋势', getRankTrendTier(stock)],
    ['量价', getVolumePriceTier(stock)],
    ['周期', getLifecycleTier(stock)],
    ['热度', getCrossSectionTier(stock)],
  ]
  for (const [label, tier] of dims) {
    parts.push(tier === null ? `${label} -` : `${label} ${tier}`)
  }
  return parts
}

const STAGE_CN: Record<string, string> = {
  ignition: '点火',
  expansion: '扩散',
  crowded: '拥挤',
  reversal: '反转',
  cooling: '冷却',
}

const TIER_CN: Record<RankTrendSignalTier, string> = {
  S: '强买',
  A: '买入',
  B: '弱买',
  C: '中性',
  D: '回避',
  E: '否决',
  unknown: '--',
}

function dimDirection(stock: unknown, path: string): string | null {
  let cur: unknown = stock
  for (const key of path.split('.')) {
    if (cur && typeof cur === 'object' && key in (cur as Record<string, unknown>)) {
      cur = (cur as Record<string, unknown>)[key]
    } else {
      return null
    }
  }
  return typeof cur === 'string' && cur ? cur : null
}

/** 五维信号"三票一票制"用户友好解释（悬停展示，2026-08-16；2026-08-26 补齐第 5 维热度票与降档前档位）：
 *  方向投票（共振/趋势/量价三维 + 第 5 维热度（crossSection），有明确方向/档位才投）+ 周期环境门（否决/谨慎/回避/放行）+ 最终结果。
 *  分值映射与后端一致（_VOTE_STRENGTH v4 / _CS_STRENGTH × 维度票权：阶段 23.9 采纳
 *  res/rank/cs ×0.75、vp ×1.0，2026-09-14 用户决策），仅作解释投影，不产出档位。
 *  示例：
 *    共振 强买·涨(+0.9)  趋势 买入·涨(+0.75)  量价 弱买·涨(+0.7)  热度 偏强（第5维票 +0.38）
 *    周期 拥挤（回避）→ 若为 S/A 则降一档
 *    票数汇总 → 总档 买入（周期环境门降档后，降档前 S）       */
export function getSynergyVoteBreakdown(stock: unknown): string[] {
  const lines: string[] = []
  const votes: string[] = []
  const resTier = getResonanceTier(stock)
  const rankTier = getRankTrendTier(stock)
  const vpTier = getVolumePriceTier(stock)
  const lcTier = getLifecycleTier(stock)
  const resDir = dimDirection(stock, 'rankTrend.resonance.direction')
  const rankDir = dimDirection(stock, 'rankTrend.observation.rankTrend.direction')
  const vpDir = dimDirection(stock, 'rankTrend.observation.volumePrice.direction')
  const stage = dimDirection(stock, 'rankTrend.observation.lifecycle.stage')

  // 档位强度 × 维度票权（展示投影，与后端 volume_price.py _VOTE_STRENGTH v4 +
  // config.tierSynergy{Resonance,Rank,VolumePrice,CrossSection}Vote 一致；阶段 23.9；
  // B 档 0.8→0.7 随后端 2026-09-30 vsB_070 落默认同步，长测阶段 27.3）
  const VOTE_STRENGTH: Record<string, number> = { S: 1.2, A: 1.0, B: 0.7, C: 0.5, D: 1.0, E: 1.0 }
  const CS_TIER_CN: Record<string, string> = { A: '强', B: '偏强', C: '偏弱', D: '弱' }
  const CS_VOTE: Record<string, number> = { A: 1.0, B: 0.5, C: -0.5, D: -1.0 }
  const RES_VOTE_WEIGHT = 0.75
  const RANK_VOTE_WEIGHT = 0.75
  const VP_VOTE_WEIGHT = 1.0
  const CS_VOTE_WEIGHT = 0.75
  const round2 = (v: number): number => Number(v.toFixed(2))

  const voteText = (tier: RankTrendSignalTier | null, dir: string | null, defaultTxt: string, weight: number) => {
    if (!tier || tier === 'unknown') return null
    const score = round2((VOTE_STRENGTH[tier] ?? 0) * weight)
    const scoreTxt = score > 0 ? `(+${score})` : `(${score})`
    if (dir === 'buy' || dir === 'up') return `${TIER_CN[tier]}·涨${scoreTxt}`
    if (dir === 'sell' || dir === 'down') return `${TIER_CN[tier]}·跌${scoreTxt}`
    return `${TIER_CN[tier]}（${defaultTxt}）`
  }
  const vRes = voteText(resTier, resDir, '共振观望', RES_VOTE_WEIGHT)
  const vRank = voteText(rankTier, rankDir, '趋势观望', RANK_VOTE_WEIGHT)
  const vVp = voteText(vpTier, vpDir, '量价常态', VP_VOTE_WEIGHT)
  if (vRes) votes.push(`共振 ${vRes}`)
  if (vRank) votes.push(`趋势 ${vRank}`)
  if (vVp) votes.push(`量价 ${vVp}`)
  // 第 5 维热度（技术字段 crossSection）：参与投票（后端 tierSynergyCrossSectionVote=0.75，阶段 23.9）
  const csTier = getCrossSectionTier(stock)
  if (csTier && csTier !== 'unknown' && CS_VOTE[csTier] != null) {
    const csVote = round2(CS_VOTE[csTier] * CS_VOTE_WEIGHT)
    votes.push(`热度 ${CS_TIER_CN[csTier] ?? csTier}（第5维票 ${csVote > 0 ? '+' : ''}${csVote}）`)
  }
  if (votes.length) {
    lines.push(votes.join('  '))
  } else {
    lines.push('共振/趋势/量价：方向票不足，未形成买入方向')
  }

  // 周期环境门
  const stageCn = stage ? (STAGE_CN[stage] || stage) : '未知'
  if (lcTier === 'E') {
    lines.push(`周期 否决（${stageCn}）→ 总档强制否决`)
  } else if (lcTier === 'B') {
    lines.push(`周期 谨慎（${stageCn}）→ 若为 S/A 则降一档`)
  } else if (lcTier === 'D') {
    lines.push(`周期 回避（${stageCn}）→ 若为 S/A 则降一档`)
  } else if (lcTier === 'A') {
    lines.push(`周期 放行（${stageCn}）→ 不干预方向票`)
  } else {
    lines.push(`周期 ${stageCn}（环境门）`)
  }

  // 最终结果：后端已产 synergy.signalTier；若 tierReasons 含"环境降档"，标注降档前档位（S→A、A→B）
  const syn = getSynergyTier(stock)
  const synReasons = getSynergyTierReasons(stock)
  const downgraded = synReasons.some((r) => r.includes('环境降档'))
  const downgradeBefore = (tier: RankTrendSignalTier): string =>
    tier === 'A' ? 'S' : tier === 'B' ? 'A' : tier
  if (syn && syn !== 'unknown') {
    const reason = TIER_CN[syn]
    const before = downgraded ? `，降档前 ${downgradeBefore(syn)}` : ''
    lines.push(`票数汇总 → 总档 ${syn}（${reason}${downgraded ? '，周期环境门降档后' : ''}${before}）`)
  } else {
    lines.push('总档：数据不足，未合并')
  }
  return lines
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
