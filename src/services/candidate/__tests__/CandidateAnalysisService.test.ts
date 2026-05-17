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
    expect(result.signalsSnapshot.candidateAnalysis).toMatchObject({
      version: 'candidate-rules-v1',
      grade: 'A',
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
    expect(result.signalsSnapshot.candidateAnalysis).toMatchObject({
      version: 'candidate-rules-v1',
      suggestedStatus: 'observe',
    })
  })
})
