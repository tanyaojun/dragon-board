import { describe, expect, it } from 'vitest'
import { projectThemeStockExposures } from '../ThemeStockProjector'
import type { ThemeFactorSnapshot, ThemeSourceContext } from '../types'

function factor(overrides: Partial<ThemeFactorSnapshot> = {}): ThemeFactorSnapshot {
  return {
    themeId: 'AI',
    themeName: '人工智能',
    source: 'market_aggregate',
    timestamp: 1,
    heatScore: 2000,
    heatLevel: 90,
    momentumScore: 0,
    breadthScore: 0,
    fundScore: null,
    leadershipScore: 0,
    correlationScore: 0,
    crowdingRisk: 0,
    persistenceScore: 0,
    rotationState: 'neutral',
    stockCount: 1,
    ztCount: 0,
    leaderCount: 0,
    netInflow: null,
    strength: 2000,
    volumeRatio: 0,
    rank: 1,
    relatedThemeIds: [],
    qualityFlags: [],
    components: { breadthScore: 0, fundScore: null, leadershipScore: 0, correlationScore: 0, riskPenalty: 0 },
    ...overrides,
  } as ThemeFactorSnapshot
}

function context(heatLevelStockChange = 10): ThemeSourceContext {
  return {
    timestamp: 1,
    themes: [{ id: 'AI', name: '人工智能' }],
    themeStocks: new Map([['AI', ['000001']]]),
    stockThemes: new Map([['000001', ['AI']]]),
    stocks: [{ code: '000001', name: '样本', change: heatLevelStockChange }],
    rotationAnalysis: null,
    correlations: new Map(),
  }
}

describe('ThemeStockProjector heatLevel caliber', () => {
  it('maps heatLevel to themeScore (relative score, not absolute heatScore)', () => {
    const result = projectThemeStockExposures(context(), [factor()])
    expect(result.byCode.get('000001')?.[0]?.themeScore).toBe(90)
  })

  it('treats missing heatLevel as heatless: positive change is not noise', () => {
    const result = projectThemeStockExposures(context(10), [factor({ heatLevel: null })])
    expect(result.byCode.get('000001')?.[0]?.role).toBe('independent')
  })

  it('heatLevel < 20 with positive change is noise: sub-threshold exposure filtered out', () => {
    // 评审 H-2b：noise 贡献度 (10*0.1 + 12*0.08)*0.15 ≈ 0.29 < 1，被既有 themeContribution<1
    // 规则过滤，byCode 无该股条目——旧代码（heatScore 2000 → core/follower）会保留 exposure，
    // 该断言是真正的 RED 判别点，不能断言 role 值（拿不到被过滤的 exposure）。
    const result = projectThemeStockExposures(context(1), [factor({ heatLevel: 10 })])
    expect(result.byCode.get('000001') ?? []).toHaveLength(0)
  })

  it('deep drop (change < -5) is noise regardless of high heatLevel (regression lock)', () => {
    // 深跌 noise 走 change<-5 分支，贡献度 (90*0.1 + 12*0.08)*0.15 ≈ 1.49 ≥ 1 → exposure 保留，
    // 可断言 role；新旧代码对该分支行为一致，作为回归锁定而非 RED 判别点。
    const result = projectThemeStockExposures(context(-6), [factor({ heatLevel: 90 })])
    expect(result.byCode.get('000001')?.[0]?.role).toBe('noise')
  })

  it('heatLevel >= 70 with change >= 5 is core', () => {
    const result = projectThemeStockExposures(context(6), [factor({ heatLevel: 72 })])
    expect(result.byCode.get('000001')?.[0]?.role).toBe('core')
  })
})
