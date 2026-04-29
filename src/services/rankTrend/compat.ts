import type { RankTrendAnalysisResult } from './types'

export interface RankTrendDisplayStatus {
  label: string
  classKey: string
  tooltip: string
}

const CANDIDATE_TIER_STATUS: Record<string, RankTrendDisplayStatus> = {
  A_MAIN: {
    label: '主升确认',
    classKey: 'main_confirmed',
    tooltip: '注意力趋势已被快照确认，资金未明显背离，作为重点跟踪对象。',
  },
  B_IGNITION: {
    label: '点火观察',
    classKey: 'ignition_watch',
    tooltip: '注意力开始启动，仍需后续半小时快照确认扩散。',
  },
  C_CROWDED: {
    label: '高位拥挤',
    classKey: 'crowded',
    tooltip: '热度和位置偏高，追击赔率下降，重点防止情绪追高。',
  },
  D_EXIT_RISK: {
    label: '转弱预警',
    classKey: 'weakening',
    tooltip: '注意力或资金已经转弱，优先控制风险，不按机会票处理。',
  },
  N_NEUTRAL: {
    label: '新入观察',
    classKey: 'new_watch',
    tooltip: '刚进入热榜视野，资金确认一般，先看下一轮排名和资金能否延续。',
  },
}

function toNumber(value: unknown): number {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

function isSampleInsufficient(rankTrend?: RankTrendAnalysisResult | null): boolean {
  return !rankTrend || rankTrend.meta?.sampleQuality?.status === 'insufficient'
}

function isStrongMoney(stock: any): boolean {
  const zlje = toNumber(stock?.zlje)
  const zljzb = toNumber(stock?.zljzb)
  const cddje = toNumber(stock?.cddje)
  const cddjzb = toNumber(stock?.cddjzb)

  return zlje > 0 && zljzb >= 8 && (cddje > 0 || cddjzb >= 3)
}

function isMoneyWeak(stock: any): boolean {
  const zlje = toNumber(stock?.zlje)
  const zljzb = toNumber(stock?.zljzb)
  const cddje = toNumber(stock?.cddje)
  const cddjzb = toNumber(stock?.cddjzb)

  return zlje < 0 || zljzb <= -3 || (cddje < 0 && cddjzb <= 0)
}

function isHotAttention(rankTrend: RankTrendAnalysisResult | null | undefined, stock: any): boolean {
  const currentPercentile = toNumber(rankTrend?.meta?.currentPercentile)
  const compRank = toNumber(stock?.compRank ?? stock?.rank)
  const rankChange = toNumber(rankTrend?.meta?.change ?? stock?.rankChange)

  return currentPercentile >= 70 || (compRank > 0 && compRank <= 50) || rankChange > 0
}

function isHighCrowded(rankTrend: RankTrendAnalysisResult | null | undefined, stock: any): boolean {
  const change = toNumber(stock?.change)
  const volumeRatio = toNumber(stock?.volumeRatio)
  const turnoverRate = toNumber(stock?.turnoverRate)
  const currentPercentile = toNumber(rankTrend?.meta?.currentPercentile)

  return (change >= 8 || currentPercentile >= 88) && (volumeRatio >= 1.8 || turnoverRate >= 10)
}

function isMoneyNotWeak(stock: any): boolean {
  return !isMoneyWeak(stock)
}

export function applyRankTrendAnalysis(target: any, rankTrend?: RankTrendAnalysisResult | null): void {
  if (!target) return

  if (!rankTrend) {
    target.rankTrend = undefined
    return
  }

  target.rankTrend = rankTrend
}

export function getRankTrendAnalysis(target: any): RankTrendAnalysisResult | null {
  return (target?.rankTrend as RankTrendAnalysisResult | undefined) ?? null
}

export function getRankTrendDisplayStatus(
  rankTrend?: RankTrendAnalysisResult | null,
  stock?: any,
): RankTrendDisplayStatus {
  const tier = rankTrend?.strategy?.candidateTier
  const insufficient = isSampleInsufficient(rankTrend)
  const hotAttention = isHotAttention(rankTrend, stock)
  const strongMoney = isStrongMoney(stock)
  const moneyWeak = isMoneyWeak(stock)

  if (tier === 'D_EXIT_RISK') return CANDIDATE_TIER_STATUS.D_EXIT_RISK

  if (hotAttention && moneyWeak) {
    return {
      label: '资金背离',
      classKey: 'money_divergence',
      tooltip: '热度仍在，但主力资金不支持，警惕冲高回落或诱多。',
    }
  }

  if (tier === 'C_CROWDED' || isHighCrowded(rankTrend, stock)) {
    return CANDIDATE_TIER_STATUS.C_CROWDED
  }

  if (tier === 'A_MAIN' && !insufficient && isMoneyNotWeak(stock)) {
    return CANDIDATE_TIER_STATUS.A_MAIN
  }

  if (tier === 'B_IGNITION' && !insufficient && isMoneyNotWeak(stock)) {
    return CANDIDATE_TIER_STATUS.B_IGNITION
  }

  if (strongMoney) {
    return {
      label: '强资确认',
      classKey: 'strong_money',
      tooltip: '资金明显介入，但趋势样本仍需确认，重点看后续留榜和资金持续。',
    }
  }

  if (hotAttention) {
    return CANDIDATE_TIER_STATUS.N_NEUTRAL
  }

  return {
    label: '样本不足',
    classKey: 'insufficient',
    tooltip: '快照样本不足，且资金确认不明显，暂不作为重点状态。',
  }
}
