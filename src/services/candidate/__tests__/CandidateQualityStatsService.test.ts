import { describe, expect, it } from 'vitest'
import { buildCandidateQualityStats } from '../CandidateQualityStatsService'
import type { CandidateJournalEntry, CandidateWorkbenchReview } from '../types'

function makeReview(
  partial: {
    id: string
    status: CandidateJournalEntry['status']
    reviewOutcome?: string
    theme?: string
    tier?: string
    grade?: 'A' | 'B' | 'C' | 'D'
    moneyFlow?: number
    score?: number
    createdAt: string
    updatedAt: string
    riskWarnings?: string[]
  },
): CandidateWorkbenchReview {
  const grade = partial.grade || 'B'
  const score = partial.score ?? 70
  return {
    entry: {
      id: partial.id,
      stockCode: partial.id.padStart(6, '0'),
      stockName: partial.id,
      status: partial.status,
      tradeType: 'thesis',
      entryReason: '',
      tradeHypothesis: '',
      entryPrerequisites: '',
      invalidationRules: '',
      humanDecision: 'watch',
      skipReason: '',
      reviewOutcome: partial.reviewOutcome || 'pending',
      modelResult: 'unknown',
      executionResult: 'unknown',
      reviewNotes: '',
      reviewTags: [grade, partial.tier || 'N_NEUTRAL', partial.theme || '未分组'],
      signalsSnapshot: {},
      createdAt: partial.createdAt,
      updatedAt: partial.updatedAt,
    },
    savedAnalysis: {
      score,
      grade,
      suggestedStatus: partial.status,
      riskWarnings: [],
      strengths: [],
      weaknesses: [],
      scoreBreakdown: {
        rankTrend: 0,
        theme: 0,
        dragon: 0,
        sentiment: 0,
        moneyFlow: partial.moneyFlow ?? 5,
      },
    },
    currentAnalysis: {
      score,
      grade,
      suggestedStatus: partial.status === 'tracking' ? 'triggered' : partial.status === 'reviewed' ? 'candidate' : partial.status,
      entryReason: '',
      tradeHypothesis: '',
      entryPrerequisites: '',
      invalidationRules: '',
      riskWarnings: partial.riskWarnings || [],
      strengths: [],
      weaknesses: [],
      tags: [],
      scoreBreakdown: {
        rankTrend: 0,
        theme: 0,
        dragon: 0,
        sentiment: 0,
        moneyFlow: partial.moneyFlow ?? 5,
      },
      signalsSnapshot: {
        theme: { primaryTheme: partial.theme || '未分组' },
        rankTrend: { strategy: { candidateTier: partial.tier || 'N_NEUTRAL' } },
        quote: { zlje: (partial.moneyFlow ?? 5) >= 8 ? 1200 : partial.moneyFlow && partial.moneyFlow < 0 ? -800 : 0 },
      },
    },
    scoreDelta: 0,
    stateLabel: '条件持平',
    stateReasons: [],
  }
}

describe('CandidateQualityStatsService', () => {
  it('builds funnel, review metrics and quality breakdowns from candidate reviews', () => {
    const stats = buildCandidateQualityStats(
      [
        makeReview({
          id: '1',
          status: 'observe',
          theme: '先进封装',
          tier: 'N_NEUTRAL',
          grade: 'C',
          moneyFlow: 4,
          score: 58,
          createdAt: '2026-05-10T09:30:00+08:00',
          updatedAt: '2026-05-10T10:30:00+08:00',
        }),
        makeReview({
          id: '2',
          status: 'candidate',
          theme: '先进封装',
          tier: 'A_MAIN',
          grade: 'A',
          moneyFlow: 12,
          score: 86,
          createdAt: '2026-05-11T09:30:00+08:00',
          updatedAt: '2026-05-13T09:30:00+08:00',
        }),
        makeReview({
          id: '3',
          status: 'triggered',
          theme: '机器人',
          tier: 'B_IGNITION',
          grade: 'B',
          moneyFlow: 10,
          score: 72,
          createdAt: '2026-05-12T09:30:00+08:00',
          updatedAt: '2026-05-14T09:30:00+08:00',
        }),
        makeReview({
          id: '4',
          status: 'tracking',
          theme: '机器人',
          tier: 'C_CROWDED',
          grade: 'C',
          moneyFlow: -2,
          score: 51,
          createdAt: '2026-05-13T09:30:00+08:00',
          updatedAt: '2026-05-16T09:30:00+08:00',
          riskWarnings: ['主力净额转负，资金确认不足'],
        }),
        makeReview({
          id: '5',
          status: 'reviewed',
          reviewOutcome: 'success',
          theme: '先进封装',
          tier: 'A_MAIN',
          grade: 'A',
          moneyFlow: 14,
          score: 90,
          createdAt: '2026-05-10T09:30:00+08:00',
          updatedAt: '2026-05-15T09:30:00+08:00',
        }),
        makeReview({
          id: '6',
          status: 'reviewed',
          reviewOutcome: 'failed',
          theme: '机器人',
          tier: 'D_EXIT_RISK',
          grade: 'D',
          moneyFlow: -4,
          score: 38,
          createdAt: '2026-05-11T09:30:00+08:00',
          updatedAt: '2026-05-12T09:30:00+08:00',
          riskWarnings: ['RankTrend 为 D_EXIT_RISK，候选失效风险高'],
        }),
        makeReview({
          id: '7',
          status: 'reviewed',
          reviewOutcome: 'not_triggered',
          theme: '低空经济',
          tier: 'N_NEUTRAL',
          grade: 'C',
          moneyFlow: 3,
          score: 55,
          createdAt: '2026-05-13T09:30:00+08:00',
          updatedAt: '2026-05-14T09:30:00+08:00',
        }),
      ],
      { now: Date.parse('2026-05-17T09:30:00+08:00') },
    )

    expect(stats.total).toBe(7)
    expect(stats.funnel).toEqual({
      observe: 1,
      candidate: 1,
      triggered: 1,
      tracking: 1,
      reviewed: 3,
      success: 1,
      failed: 1,
      notTriggered: 1,
    })
    expect(stats.metrics.hitRate).toBe(33)
    expect(stats.metrics.failureRate).toBe(67)
    expect(stats.metrics.averageFollowDays).toBe(2.1)
    expect(stats.metrics.reviewedCount).toBe(3)
    expect(stats.metrics.pendingReview).toBe(4)

    expect(stats.breakdowns.themes[0]).toMatchObject({
      key: '先进封装',
      label: '先进封装',
      total: 3,
      averageScore: 78,
      hitRate: 33,
    })
    expect(stats.breakdowns.rankTrendTiers.map((item) => item.key)).toEqual([
      'A_MAIN',
      'N_NEUTRAL',
      'B_IGNITION',
      'C_CROWDED',
      'D_EXIT_RISK',
    ])
    expect(stats.breakdowns.grades.find((item) => item.key === 'A')).toMatchObject({
      total: 2,
      hitRate: 50,
    })
    expect(stats.breakdowns.moneyFlowStates.map((item) => item.key)).toEqual([
      'positive',
      'neutral',
      'negative',
    ])
    expect(stats.reviewOutcomeSegments.map((item) => item.key)).toEqual([
      'success',
      'failed',
      'not_triggered',
      'pending',
    ])
  })
})
