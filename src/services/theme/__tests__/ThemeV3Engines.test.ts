import { describe, expect, it, vi } from 'vitest'
import { createThemeRuntimeStore } from '../ThemeRuntimeStore'
import { projectThemeStockExposures } from '../ThemeStockProjector'
import { themeHeatFeed } from '../ThemeHeatFeed'
import {
  refreshThemeFacadeState,
  getHotThemes,
  getRuntimeSnapshot,
} from '../ThemeFacade'
import type { ThemeFactorSnapshot, ThemeSourceContext } from '../types'

function factor(overrides: Partial<ThemeFactorSnapshot>): ThemeFactorSnapshot {
  return {
    themeId: 'AI',
    themeName: '人工智能',
    source: 'mixed',
    timestamp: 1713751200000,
    heatScore: 86,
    heatLevel: 80,
    momentumScore: 82,
    breadthScore: 74,
    fundScore: 76,
    leadershipScore: 80,
    correlationScore: 70,
    crowdingRisk: 22,
    persistenceScore: 65,
    rotationState: 'mainline',
    stockCount: 30,
    ztCount: 4,
    leaderCount: 1,
    netInflow: 180000000,
    strength: 4200,
    volumeRatio: 2.2,
    rank: 1,
    relatedThemeIds: [],
    qualityFlags: [],
    components: {
      breadthScore: 74,
      fundScore: 76,
      leadershipScore: 80,
      correlationScore: 70,
      riskPenalty: 0,
    },
    ...overrides,
  }
}

function context(): ThemeSourceContext {
  return {
    timestamp: 1713751200000,
    themes: [
      { id: 'AI', name: '人工智能' },
      { id: 'POWER', name: '电力设备' },
    ],
    themeStocks: new Map([
      ['AI', ['000001', '000002']],
      ['POWER', ['000003']],
    ]),
    stockThemes: new Map([
      ['000001', ['AI']],
      ['000002', ['AI']],
      ['000003', ['POWER']],
    ]),
    stocks: [
      { code: '000001', name: '样本一', change: 10, volumeRatio: 2.8, leadStatus: '龙一' },
      { code: '000002', name: '样本二', change: 4, volumeRatio: 1.5 },
      { code: '000003', name: '样本三', change: -3, volumeRatio: 0.8 },
    ],
  }
}

describe('ThemeRuntimeStore', () => {
  it('stores immutable runtime snapshots and notifies subscribers', () => {
    const store = createThemeRuntimeStore()
    const listener = vi.fn()
    const unsubscribe = store.subscribe(listener)

    store.update({
      factors: [factor({ themeId: 'AI' })],
    })
    const snapshot = store.getSnapshot()
    snapshot.factors.push(factor({ themeId: 'MUTATED' }))

    expect(listener).toHaveBeenCalledTimes(1)
    expect(store.getSnapshot().factors).toHaveLength(1)

    unsubscribe()
    store.update({ factors: [] })
    expect(listener).toHaveBeenCalledTimes(1)
  })
})

describe('ThemeStockProjector', () => {
  it('projects stock exposures with roles derived from heat and lead status', () => {
    const factors = [
      factor({ themeId: 'AI', themeName: '人工智能' }),
      factor({ themeId: 'POWER', themeName: '电力设备', rotationState: 'neutral', heatScore: 30 }),
    ]
    const exposures = projectThemeStockExposures(context(), factors)

    expect(exposures.byCode.get('000001')?.[0]).toMatchObject({
      themeId: 'AI',
      role: 'leader',
    })
    expect(exposures.byTheme.get('POWER')?.length).toBeGreaterThan(0)
  })
})

describe('ThemeFacade runtime views', () => {
  it('refreshes runtime state and exposes hot theme views', () => {
    vi.spyOn(themeHeatFeed, 'getRuntimeFactors').mockReturnValue([
      factor({ themeId: 'AI', themeName: '人工智能' }),
    ])
    const result = refreshThemeFacadeState({
      context: context(),
    })
    const hotThemes = getHotThemes(3)

    expect(result.factors[0].themeName).toBe('人工智能')
    expect(hotThemes[0]).toMatchObject({ id: 'AI', name: '人工智能' })
  })
})

describe('ThemeFacade UI read models', () => {
  it('exposes immutable runtime snapshots', () => {
    const freshTimestamp = Date.now()
    refreshThemeFacadeState({ context: { ...context(), timestamp: freshTimestamp } })

    const snapshot = getRuntimeSnapshot()

    snapshot.factors.push(factor({ themeId: 'MUTATED' }))
    snapshot.exposures.byCode.set('999999', [])

    expect(getRuntimeSnapshot().factors.some((item) => item.themeId === 'MUTATED')).toBe(false)
    expect(getRuntimeSnapshot().exposures.byCode.has('999999')).toBe(false)
  })

  it('keeps factor output deterministic for the same context', () => {
    const first = refreshThemeFacadeState({ context: context() })
    const second = refreshThemeFacadeState({ context: context() })

    expect(second.factors).toEqual(first.factors)
  })
})
