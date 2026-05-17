import type { CandidateGrade, CandidateWorkbenchReview } from './types'

type CandidateReviewOutcome = 'pending' | 'success' | 'partial' | 'failed' | 'not_triggered'

export interface CandidateQualitySegment {
  key: string
  label: string
  total: number
  reviewedCount: number
  averageScore: number
  hitRate: number
  failureRate: number
  riskCount: number
}

export interface CandidateQualityStats {
  total: number
  funnel: {
    observe: number
    candidate: number
    triggered: number
    tracking: number
    reviewed: number
    success: number
    failed: number
    notTriggered: number
  }
  metrics: {
    averageScore: number
    riskCount: number
    triggerRate: number
    hitRate: number
    failureRate: number
    averageFollowDays: number
    reviewedCount: number
    pendingReview: number
  }
  breakdowns: {
    themes: CandidateQualitySegment[]
    rankTrendTiers: CandidateQualitySegment[]
    grades: CandidateQualitySegment[]
    moneyFlowStates: CandidateQualitySegment[]
  }
  reviewOutcomeSegments: CandidateQualitySegment[]
}

interface BuildCandidateQualityStatsOptions {
  now?: number
}

const DAY_MS = 24 * 60 * 60 * 1000
const RANK_TIER_ORDER = ['A_MAIN', 'B_IGNITION', 'C_CROWDED', 'D_EXIT_RISK', 'N_NEUTRAL']
const GRADE_ORDER: Array<CandidateGrade | '-'> = ['A', 'B', 'C', 'D', '-']
const MONEY_FLOW_ORDER = ['positive', 'neutral', 'negative']
const REVIEW_OUTCOME_ORDER: CandidateReviewOutcome[] = [
  'success',
  'partial',
  'failed',
  'not_triggered',
  'pending',
]

function round(value: number, digits = 0): number {
  const base = 10 ** digits
  return Math.round(value * base) / base
}

function percent(value: number, total: number): number {
  return total ? Math.round((value / total) * 100) : 0
}

function finiteTimestamp(value: string): number {
  const parsed = Date.parse(value || '')
  return Number.isFinite(parsed) ? parsed : 0
}

function followDays(review: CandidateWorkbenchReview, now: number): number {
  const startedAt = finiteTimestamp(review.entry.createdAt)
  const endedAt = finiteTimestamp(review.entry.updatedAt) || now
  if (!startedAt || endedAt < startedAt) return 0
  return Math.max(1, Math.ceil((endedAt - startedAt) / DAY_MS))
}

function reviewOutcome(review: CandidateWorkbenchReview): CandidateReviewOutcome {
  const value = String(review.entry.reviewOutcome || 'pending')
  return REVIEW_OUTCOME_ORDER.includes(value as CandidateReviewOutcome)
    ? (value as CandidateReviewOutcome)
    : 'pending'
}

function isHit(review: CandidateWorkbenchReview): boolean {
  return ['success', 'partial'].includes(reviewOutcome(review))
}

function isFailure(review: CandidateWorkbenchReview): boolean {
  return ['failed', 'not_triggered'].includes(reviewOutcome(review))
}

function isReviewed(review: CandidateWorkbenchReview): boolean {
  return review.entry.status === 'reviewed'
}

function extractTheme(review: CandidateWorkbenchReview): string {
  const theme = review.currentAnalysis.signalsSnapshot?.theme?.primaryTheme
  if (theme) return String(theme)
  const tag = review.entry.reviewTags.find((item) => !GRADE_ORDER.includes(item as CandidateGrade) && !RANK_TIER_ORDER.includes(item))
  return tag || '未分组'
}

function extractRankTrendTier(review: CandidateWorkbenchReview): string {
  const tier = review.currentAnalysis.signalsSnapshot?.rankTrend?.strategy?.candidateTier
  if (tier) return String(tier)
  return review.entry.reviewTags.find((item) => RANK_TIER_ORDER.includes(item)) || 'N_NEUTRAL'
}

function extractGrade(review: CandidateWorkbenchReview): string {
  return String(review.currentAnalysis.grade || review.savedAnalysis.grade || '-')
}

function extractMoneyFlowState(review: CandidateWorkbenchReview): string {
  const quote = review.currentAnalysis.signalsSnapshot?.quote || {}
  const mainFlow = Number(quote.zlje || 0)
  const flowScore = Number(review.currentAnalysis.scoreBreakdown.moneyFlow || 0)
  if (mainFlow < 0 || flowScore < 0) return 'negative'
  if (mainFlow > 0 || flowScore >= 8) return 'positive'
  return 'neutral'
}

function labelFor(group: 'tier' | 'grade' | 'money' | 'outcome' | 'theme', key: string): string {
  if (group === 'money') {
    return {
      positive: '资金正向',
      neutral: '资金中性',
      negative: '资金转弱',
    }[key] || key
  }
  if (group === 'outcome') {
    return {
      success: '成功',
      partial: '部分兑现',
      failed: '失败',
      not_triggered: '未触发',
      pending: '待复盘',
    }[key] || key
  }
  return key
}

function orderIndex(order: string[], key: string): number {
  const index = order.indexOf(key)
  return index >= 0 ? index : order.length
}

function buildSegments(
  reviews: CandidateWorkbenchReview[],
  keyOf: (review: CandidateWorkbenchReview) => string,
  labelGroup: 'tier' | 'grade' | 'money' | 'outcome' | 'theme',
  preferredOrder: string[] = [],
): CandidateQualitySegment[] {
  const groups = new Map<string, CandidateWorkbenchReview[]>()
  for (const review of reviews) {
    const key = keyOf(review) || '未分组'
    groups.set(key, [...(groups.get(key) || []), review])
  }

  return [...groups.entries()]
    .map(([key, items]) => {
      const reviewed = items.filter(isReviewed)
      const scoreTotal = items.reduce((sum, item) => sum + item.currentAnalysis.score, 0)
      return {
        key,
        label: labelFor(labelGroup, key),
        total: items.length,
        reviewedCount: reviewed.length,
        averageScore: items.length ? Math.round(scoreTotal / items.length) : 0,
        hitRate: percent(items.filter(isHit).length, items.length),
        failureRate: percent(items.filter(isFailure).length, items.length),
        riskCount: items.filter((item) => item.currentAnalysis.riskWarnings.length > 0).length,
      }
    })
    .sort((left, right) => {
      if (labelGroup === 'outcome') {
        return orderIndex(preferredOrder, left.key) - orderIndex(preferredOrder, right.key)
      }
      if (right.total !== left.total) return right.total - left.total
      const leftOrder = orderIndex(preferredOrder, left.key)
      const rightOrder = orderIndex(preferredOrder, right.key)
      if (leftOrder !== rightOrder) return leftOrder - rightOrder
      if (right.averageScore !== left.averageScore) return right.averageScore - left.averageScore
      return left.label.localeCompare(right.label, 'zh-Hans-CN')
    })
}

export function buildCandidateQualityStats(
  reviews: CandidateWorkbenchReview[],
  options: BuildCandidateQualityStatsOptions = {},
): CandidateQualityStats {
  const now = options.now || Date.now()
  const total = reviews.length
  const reviewed = reviews.filter(isReviewed)
  const triggeredTotal = reviews.filter((review) =>
    ['triggered', 'tracking', 'reviewed'].includes(review.entry.status),
  ).length
  const followDayValues = reviews.map((review) => followDays(review, now)).filter((days) => days > 0)
  const scoreTotal = reviews.reduce((sum, review) => sum + review.currentAnalysis.score, 0)

  return {
    total,
    funnel: {
      observe: reviews.filter((review) => review.entry.status === 'observe').length,
      candidate: reviews.filter((review) => review.entry.status === 'candidate').length,
      triggered: reviews.filter((review) => review.entry.status === 'triggered').length,
      tracking: reviews.filter((review) => review.entry.status === 'tracking').length,
      reviewed: reviewed.length,
      success: reviews.filter((review) => reviewOutcome(review) === 'success').length,
      failed: reviews.filter((review) => reviewOutcome(review) === 'failed').length,
      notTriggered: reviews.filter((review) => reviewOutcome(review) === 'not_triggered').length,
    },
    metrics: {
      averageScore: total ? Math.round(scoreTotal / total) : 0,
      riskCount: reviews.filter((review) => review.currentAnalysis.riskWarnings.length > 0).length,
      triggerRate: percent(triggeredTotal, total),
      hitRate: percent(reviews.filter(isHit).length, reviewed.length),
      failureRate: percent(reviews.filter(isFailure).length, reviewed.length),
      averageFollowDays: followDayValues.length
        ? round(followDayValues.reduce((sum, days) => sum + days, 0) / followDayValues.length, 1)
        : 0,
      reviewedCount: reviewed.length,
      pendingReview: reviews.filter((review) => review.entry.status !== 'reviewed').length,
    },
    breakdowns: {
      themes: buildSegments(reviews, extractTheme, 'theme'),
      rankTrendTiers: buildSegments(reviews, extractRankTrendTier, 'tier', RANK_TIER_ORDER),
      grades: buildSegments(reviews, extractGrade, 'grade', GRADE_ORDER),
      moneyFlowStates: buildSegments(reviews, extractMoneyFlowState, 'money', MONEY_FLOW_ORDER),
    },
    reviewOutcomeSegments: buildSegments(
      reviews,
      (review) => reviewOutcome(review),
      'outcome',
      REVIEW_OUTCOME_ORDER,
    ),
  }
}
