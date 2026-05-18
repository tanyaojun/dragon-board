import { describe, expect, it } from 'vitest'
import { analyzeCandidateStock } from '../CandidateAnalysisService'
import type { CandidateAnalysisContext } from '../types'

function baseContext(overrides: Partial<CandidateAnalysisContext> = {}): CandidateAnalysisContext {
  return {
    stock: {
      code: '600584',
      name: '长电科技',
      zlje: 10.98,
      zljzb: 7.65,
      cddje: 11.98,
      volumeRatio: 1.28,
      turnoverRate: 14.03,
      themes: [
        {
          id: 'chip',
          name: '先进封装',
          role: 'leader',
          themeContribution: 16,
          exposureWeight: 86,
        },
      ],
    },
    allStocks: [],
    rankTrend: {
      strategy: {
        candidateTier: 'A_MAIN',
        action: 'focus',
        reasons: ['排名趋势进入核心候选'],
        regime: { state: 'strong', score: 82, reasons: [] },
        momentum: { short: 8, mid: 12, long: 18, acceleration: 4, shock: 2, composite: 76 },
      },
      technical: {
        momentumProfile: { composite: 76 },
      },
      cycle: {
        stage: 'expansion',
      },
      decision: {
        final: { signal: 'buy', confidence: 84 },
      },
    },
    themeExposures: [
      {
        themeId: 'chip',
        themeName: '先进封装',
        role: 'leader',
        roleScore: 88,
        exposureWeight: 86,
        themeContribution: 16,
        riskPenalty: 0,
        reasons: ['主线题材暴露较强'],
      },
    ],
    rotationSummary: {
      mainLines: [{ themeId: 'chip', themeName: '先进封装', persistentDays: 3 }],
      outflowThemes: [],
    },
    dragonRecord: {
      primaryRole: 'leader',
      authority: 'MARKET_CORE',
      tradeability: 'ACTIONABLE',
    },
    sentiment: {
      phaseName: '修复期',
      overall: 72,
    },
    now: 1778992800000,
    ...overrides,
  } as CandidateAnalysisContext
}

describe('CandidateAnalysisService', () => {
  it('generates a high grade candidate thesis from strong rank trend, theme and money flow', () => {
    const result = analyzeCandidateStock(baseContext())

    expect(result.score).toBeGreaterThanOrEqual(80)
    expect(result.grade).toBe('A')
    expect(result.suggestedStatus).toBe('candidate')
    expect(result.entryReason).toContain('A_MAIN')
    expect(result.entryReason).toContain('先进封装')
    expect(result.tradeHypothesis).toContain('3-5 天')
    expect(result.entryPrerequisites).toContain('排名')
    expect(result.invalidationRules).toContain('D_EXIT_RISK')
    expect(result.riskWarnings).toEqual([])
    expect(result.evidence.map((item) => item.dimension)).toEqual([
      'rankTrend',
      'theme',
      'dragon',
      'sentiment',
      'moneyFlow',
    ])
    expect(result.evidence).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ dimension: 'rankTrend', kind: 'positive', title: expect.stringContaining('A_MAIN') }),
        expect.objectContaining({ dimension: 'theme', kind: 'positive', title: expect.stringContaining('先进封装') }),
        expect.objectContaining({ dimension: 'dragon', kind: 'positive' }),
        expect.objectContaining({ dimension: 'moneyFlow', kind: 'positive' }),
      ]),
    )
    expect(result.penalties).toEqual([])
    expect(result.structuredThesis.triggerConditions).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ dimension: 'rankTrend', status: 'met' }),
        expect.objectContaining({ dimension: 'theme', status: 'met' }),
        expect.objectContaining({ dimension: 'moneyFlow', status: 'met' }),
      ]),
    )
    expect(result.structuredThesis.entryPrerequisites.length).toBeGreaterThan(0)
    expect(result.structuredThesis.invalidationConditions).toEqual(
      expect.arrayContaining([expect.objectContaining({ dimension: 'rankTrend' })]),
    )
    expect(result.structuredRisks).toEqual([])
    expect(result.signalsSnapshot.candidateAnalysis).toMatchObject({
      version: 'candidate-rules-v1',
      grade: 'A',
      evidence: expect.any(Array),
      penalties: [],
      structuredThesis: expect.objectContaining({
        triggerConditions: expect.any(Array),
        entryPrerequisites: expect.any(Array),
        invalidationConditions: expect.any(Array),
      }),
      structuredRisks: [],
    })
  })

  it('keeps crowded or exit-risk stocks out of triggered status and records explicit risks', () => {
    const result = analyzeCandidateStock(
      baseContext({
        rankTrend: {
          strategy: {
            candidateTier: 'C_CROWDED',
            action: 'watch',
            reasons: ['进入拥挤区'],
            regime: { state: 'retreat', score: 30, reasons: [] },
            momentum: { short: 1, mid: 2, long: 3, acceleration: -2, shock: 8, composite: 35 },
          },
          technical: {
            momentumProfile: { composite: 35 },
          },
          cycle: {
            stage: 'crowded',
          },
          decision: {
            final: { signal: 'hold', confidence: 40 },
          },
        },
        sentiment: {
          phaseName: '退潮期',
          overall: 28,
        },
        stock: {
          code: '600584',
          name: '长电科技',
          zlje: -3.5,
          zljzb: -2.4,
          cddje: -2.8,
          volumeRatio: 2.4,
          turnoverRate: 18,
          themes: [{ id: 'chip', name: '先进封装', role: 'noise', exposureWeight: 25 }],
        },
      }),
    )

    expect(result.score).toBeLessThan(65)
    expect(result.suggestedStatus).toBe('observe')
    expect(result.riskWarnings).toEqual(
      expect.arrayContaining([
        expect.stringContaining('拥挤'),
        expect.stringContaining('退潮'),
        expect.stringContaining('主力净额转负'),
      ]),
    )
    expect(result.invalidationRules).toContain('拥挤')
    expect(result.penalties).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ dimension: 'rankTrend', kind: 'negative' }),
        expect.objectContaining({ dimension: 'sentiment', kind: 'negative' }),
        expect.objectContaining({ dimension: 'moneyFlow', kind: 'negative' }),
      ]),
    )
    expect(result.structuredRisks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: 'RANKTREND_CROWDED', level: 'warning' }),
        expect.objectContaining({ code: 'SENTIMENT_EBB', level: 'warning' }),
        expect.objectContaining({ code: 'MONEY_FLOW_NEGATIVE', level: 'warning' }),
      ]),
    )
    expect(result.signalsSnapshot.candidateAnalysis).toMatchObject({
      version: 'candidate-rules-v1',
      suggestedStatus: 'observe',
    })
  })

  it('returns structured missing-data risks without producing NaN scores', () => {
    const result = analyzeCandidateStock(
      baseContext({
        rankTrend: null,
        themeExposures: [],
        dragonRecord: null,
        sentiment: null,
        stock: {
          code: '600000',
          name: '低样本',
          zlje: Number.NaN,
          zljzb: Number.NaN,
          cddje: Number.NaN,
          volumeRatio: Number.NaN,
          turnoverRate: Number.NaN,
          themes: [],
        },
        allStocks: [{ code: '600001', name: '低样本参照' }],
      }),
    )

    expect(Number.isNaN(result.score)).toBe(false)
    expect(result.evidence).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ dimension: 'rankTrend', kind: 'missing' }),
        expect.objectContaining({ dimension: 'theme', kind: 'missing' }),
        expect.objectContaining({ dimension: 'dragon', kind: 'missing' }),
        expect.objectContaining({ dimension: 'sentiment', kind: 'missing' }),
        expect.objectContaining({ dimension: 'moneyFlow', kind: 'missing' }),
      ]),
    )
    expect(result.structuredRisks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: 'RANKTREND_MISSING', level: 'warning' }),
        expect.objectContaining({ code: 'THEME_MISSING', level: 'info' }),
        expect.objectContaining({ code: 'SENTIMENT_MISSING', level: 'info' }),
        expect.objectContaining({ code: 'MONEY_FLOW_MISSING', level: 'info' }),
        expect.objectContaining({ code: 'DATA_LOW_SAMPLE', level: 'info', dimension: 'dataQuality' }),
      ]),
    )
    expect(result.structuredThesis.triggerConditions).toEqual(
      expect.arrayContaining([expect.objectContaining({ dimension: 'rankTrend', status: 'unknown' })]),
    )
  })

  it('treats null and blank money-flow fields as missing data instead of neutral samples', () => {
    const result = analyzeCandidateStock(
      baseContext({
        stock: {
          code: '600000',
          name: '空资金字段',
          zlje: null,
          zljzb: '',
          cddje: ' ',
          volumeRatio: undefined,
          themes: [{ id: 'chip', name: '先进封装' }],
        },
      }),
    )

    expect(result.evidence).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ dimension: 'moneyFlow', kind: 'missing' }),
      ]),
    )
    expect(result.structuredRisks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: 'MONEY_FLOW_MISSING', level: 'info' }),
      ]),
    )
    expect(result.structuredThesis.triggerConditions).toEqual(
      expect.arrayContaining([expect.objectContaining({ dimension: 'moneyFlow', status: 'unknown' })]),
    )
  })

  it('does not use suspicious capped volume ratio as candidate money-flow evidence', () => {
    const result = analyzeCandidateStock(
      baseContext({
        stock: {
          code: '600000',
          name: '异常量比',
          zlje: null,
          zljzb: '',
          cddje: ' ',
          volumeRatio: 99.99,
          volumeRatioMeta: {
            status: 'suspicious',
            source: 'intraday_snapshot',
            calculatedAt: Date.now(),
            currentVolume: 100000,
            capped: true,
            reason: 'ratio_capped',
          },
          themes: [{ id: 'chip', name: '先进封装' }],
        },
      }),
    )

    expect(result.evidence).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ dimension: 'moneyFlow', kind: 'missing' }),
      ]),
    )
    expect(result.structuredThesis.triggerConditions).toEqual(
      expect.arrayContaining([expect.objectContaining({ dimension: 'moneyFlow', status: 'unknown' })]),
    )
  })
})
