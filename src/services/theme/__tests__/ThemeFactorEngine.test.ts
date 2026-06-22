import { describe, expect, it } from 'vitest'
import { buildThemeFactors } from '../ThemeFactorEngine'
import { projectThemeStockExposures } from '../ThemeStockProjector'
import type { ThemeSourceContext } from '../types'

function createContext(overrides: Partial<ThemeSourceContext> = {}): ThemeSourceContext {
  return {
    timestamp: 1713751200000,
    snapshotId: 'half_hour:2026-04-22:10:00',
    themes: [
      { id: 'AI', name: '人工智能' },
      { id: 'POWER', name: '电力' },
    ],
    themeStocks: new Map([
      ['AI', ['000001', '000002', '000003']],
      ['POWER', ['000004']],
    ]),
    stockThemes: new Map([
      ['000001', ['AI']],
      ['000002', ['AI']],
      ['000003', ['AI']],
      ['000004', ['POWER']],
    ]),
    stocks: [
      {
        code: '000001',
        name: '样本一',
        change: 10,
        volumeRatio: 2.8,
        leadStatus: '龙一',
        leadTimes: 2,
        fengdan: 60000,
        maxFengdan: 70000,
        continuousDays: 2,
        turnoverRate: 8,
      },
      {
        code: '000002',
        name: '样本二',
        change: 5,
        volumeRatio: 1.8,
        mainNetInflow: 12000000,
        turnoverRate: 5,
      },
      {
        code: '000003',
        name: '样本三',
        change: -1,
        volumeRatio: 0.6,
      },
      {
        code: '000004',
        name: '样本四',
        change: Number.NaN,
        volumeRatio: Number.POSITIVE_INFINITY,
      },
    ],
    rotationAnalysis: {
      timestamp: 1713751200000,
      inflowThemes: [],
      outflowThemes: [],
      mainLines: [{ themeId: 'BKAI', themeName: '人工智能', persistentDays: 3 } as any],
      quickRotation: [],
      rotationSpeed: 32,
      marketPhase: 'rising',
      summary: {
        mainLineCount: 1,
        inflowCount: 1,
        outflowCount: 0,
        topInflow: '人工智能',
        topOutflow: '无',
        suggestion: '',
        strongCount: 1,
        topStrength: '人工智能',
      },
    },
    correlations: new Map([
      [
        'AI',
        {
          themeId: 'AI',
          themeName: '人工智能',
          overallCorrelation: 0.72,
          stocks: new Map([
            ['000001', { code: '000001', role: 'leader', avgCorrelation: 0.8 } as any],
            ['000002', { code: '000002', role: 'follower', avgCorrelation: 0.55 } as any],
          ]),
          coreStocks: ['000001'],
          followerStocks: ['000002'],
          independentStocks: [],
          lastUpdate: 1713751200000,
        },
      ],
    ]),
    ...overrides,
  }
}

describe('ThemeFactorEngine', () => {
  it('computes theme factors with quality flags and rotation state', () => {
    const factors = buildThemeFactors(createContext())

    expect(factors[0]).toMatchObject({
      themeId: 'AI',
      themeName: '人工智能',
      rotationState: 'mainline',
    })
    expect(factors[0].heatScore).toBeGreaterThan(60)
    expect(factors[0].breadthScore).toBeGreaterThan(50)
    expect(factors[0].leadershipScore).toBeGreaterThan(45)

    const power = factors.find((factor) => factor.themeId === 'POWER')
    expect(power?.qualityFlags.map((flag) => flag.code)).toContain('invalid_number')
    expect(factors.find((factor) => factor.themeId === 'AI')?.relatedThemeIds).toEqual([])
  })

  it('does not produce false heat for empty or unmapped themes', () => {
    const factors = buildThemeFactors(
      createContext({
        themes: [{ id: 'EMPTY', name: '空题材' }],
        themeStocks: new Map([['EMPTY', []]]),
        stocks: [],
      }),
    )

    expect(factors[0].heatScore).toBe(0)
    expect(factors[0].qualityFlags.map((flag) => flag.code)).toEqual(
      expect.arrayContaining(['empty_theme']),
    )
  })

  it('handles all invalid stock numbers without producing false heat', () => {
    const factors = buildThemeFactors(
      createContext({
        themes: [{ id: 'BROKEN', name: '异常题材' }],
        themeStocks: new Map([['BROKEN', ['000005', '000006']]]),
        stockThemes: new Map([
          ['000005', ['BROKEN']],
          ['000006', ['BROKEN']],
        ]),
        stocks: [
          { code: '000005', name: '异常一', change: Number.NaN, volumeRatio: Number.POSITIVE_INFINITY },
          { code: '000006', name: '异常二', change: Number.POSITIVE_INFINITY, volumeRatio: Number.NaN },
        ],
      }),
    )

    expect(factors[0].heatScore).toBe(0)
    expect(factors[0].qualityFlags.map((flag) => flag.code)).toContain('invalid_number')
  })

  it('reports invalid raw stock volume ratio even when trusted ratio is zeroed', () => {
    const factors = buildThemeFactors(
      createContext({
        themes: [{ id: 'BROKEN', name: '异常题材' }],
        themeStocks: new Map([['BROKEN', ['000005']]]),
        stockThemes: new Map([['000005', ['BROKEN']]]),
        stocks: [
          {
            code: '000005',
            name: '异常量比',
            change: 3,
            volumeRatio: Number.POSITIVE_INFINITY,
            volumeRatioMeta: {
              status: 'suspicious',
              source: 'intraday_snapshot',
              calculatedAt: Date.now(),
              currentVolume: 100000,
              capped: true,
              reason: 'ratio_capped',
            },
          },
        ],
      }),
    )

    expect(factors[0].qualityFlags.map((flag) => flag.code)).toContain('invalid_number')
  })

  it('ignores suspicious capped stock volume ratio when calculating crowding risk', () => {
    const suspicious = buildThemeFactors(
      createContext({
        stocks: [
          {
            code: '000001',
            name: '样本一',
            change: 10,
            volumeRatio: 99.99,
            volumeRatioMeta: {
              status: 'suspicious',
              source: 'intraday_snapshot',
              calculatedAt: Date.now(),
              currentVolume: 100000,
              capped: true,
              reason: 'ratio_capped',
            },
            leadStatus: '龙一',
          },
          { code: '000002', name: '样本二', change: 4, volumeRatio: 1.2 },
          { code: '000003', name: '样本三', change: -1, volumeRatio: 0.6 },
        ],
      }),
    )
    const trusted = buildThemeFactors(
      createContext({
        stocks: [
          {
            code: '000001',
            name: '样本一',
            change: 10,
            volumeRatio: 99.99,
            volumeRatioMeta: {
              status: 'fresh',
              source: 'intraday_snapshot',
              calculatedAt: Date.now(),
              currentVolume: 100000,
            },
            leadStatus: '龙一',
          },
          { code: '000002', name: '样本二', change: 4, volumeRatio: 1.2 },
          { code: '000003', name: '样本三', change: -1, volumeRatio: 0.6 },
        ],
      }),
    )

    expect(suspicious.find((factor) => factor.themeId === 'AI')?.crowdingRisk).toBeLessThan(
      trusted.find((factor) => factor.themeId === 'AI')?.crowdingRisk || 0,
    )
  })

  it('marks outflow themes as cooling in distribution or falling phases', () => {
    const factors = buildThemeFactors(
      createContext({
        rotationAnalysis: {
          timestamp: 1713751200000,
          inflowThemes: [],
          outflowThemes: [{ themeId: 'AI', themeName: '人工智能' } as any],
          mainLines: [],
          quickRotation: [],
          rotationSpeed: 48,
          marketPhase: 'distribution',
          summary: {
            mainLineCount: 0,
            inflowCount: 0,
            outflowCount: 1,
            topInflow: '无',
            topOutflow: '人工智能',
            suggestion: '',
            strongCount: 0,
            topStrength: '无',
          },
        },
      }),
    )

    expect(factors.find((factor) => factor.themeId === 'AI')?.rotationState).toBe('cooling')
  })
})

describe('ThemeStockProjector', () => {
  it('projects stock theme exposure with bounded contribution and role reasons', () => {
    const factors = buildThemeFactors(createContext())
    const exposures = projectThemeStockExposures(createContext(), factors)
    const leaderExposure = exposures.byCode.get('000001')?.[0]

    expect(leaderExposure).toMatchObject({
      code: '000001',
      themeId: 'AI',
      themeName: '人工智能',
      role: 'leader',
    })
    expect(leaderExposure?.themeContribution).toBeGreaterThan(0)
    expect(leaderExposure?.themeContribution).toBeLessThanOrEqual(18)
    expect(leaderExposure?.reasons).toContain('题材处于主线')
  })

  it('drops noise exposures when contribution is zero', () => {
    const context = createContext({
      themes: [{ id: 'WEAK', name: '弱题材' }],
      themeStocks: new Map([['WEAK', ['000007']]]),
      stockThemes: new Map([['000007', ['WEAK']]]),
      stocks: [{ code: '000007', name: '弱样本', change: -8, volumeRatio: 0.5 }],
      rotationAnalysis: null,
      correlations: new Map(),
    })
    const factors = buildThemeFactors(context)
    const exposures = projectThemeStockExposures(context, factors)

    expect(exposures.byCode.get('000007')).toBeUndefined()
    expect(exposures.byTheme.get('WEAK')).toBeUndefined()
  })
})
