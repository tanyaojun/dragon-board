import { describe, expect, it, vi } from 'vitest'
import { createThemeRuntimeStore } from '../ThemeRuntimeStore'
import { buildThemeRotationSummary } from '../ThemeRotationEngine'
import { buildThemeEvents } from '../ThemeAlertEngine'
import { buildThemeFactors } from '../ThemeFactorEngine'
import { projectThemeStockExposures } from '../ThemeStockProjector'
import {
  refreshThemeFacadeState,
  refreshJxbkAndFactors,
  getHotThemesCompat,
  getRotationSummary,
  getJxbkBlocksCompat,
  getJxbkLastUpdate,
  getRuntimeSnapshot,
  getThemeStockMapCompat,
} from '../ThemeFacade'
import { jxbkThemeFeed } from '../JxbkThemeFeed'
import { dataLayer } from '@/services/DataLayer'
import type { ThemeFactorSnapshot, ThemeSourceContext } from '../types'

function factor(overrides: Partial<ThemeFactorSnapshot>): ThemeFactorSnapshot {
  return {
    themeId: 'AI',
    themeName: '人工智能',
    source: 'mixed',
    timestamp: 1713751200000,
    heatScore: 86,
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
      baseScore: 20,
      jxbkScore: 90,
      stockScore: 70,
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
    jxbkBlocks: [
      {
        code: 'BKAI',
        name: '人工智能',
        strength: 4200,
        change: 4,
        mainNetInflow: 180000000,
        bigMoney300: 30000000,
        institutionBuy: 10000000,
        volumeRatio: 2.4,
        ztCount: 2,
      },
    ],
    rotationAnalysis: null,
    correlations: new Map(),
  }
}

describe('ThemeRuntimeStore', () => {
  it('stores immutable runtime snapshots and notifies subscribers', () => {
    const store = createThemeRuntimeStore()
    const listener = vi.fn()
    const unsubscribe = store.subscribe(listener)

    store.update({
      factors: [factor({ themeId: 'AI' })],
      rotationSummary: buildThemeRotationSummary([factor({ themeId: 'AI' })]),
    })
    const snapshot = store.getSnapshot()
    snapshot.factors.push(factor({ themeId: 'MUTATED' }))
    snapshot.rotationSummary?.mainLines.push({ themeId: 'MUTATED', themeName: '污染题材' } as any)

    expect(listener).toHaveBeenCalledTimes(1)
    expect(store.getSnapshot().factors).toHaveLength(1)
    expect(store.getSnapshot().rotationSummary?.mainLines).toHaveLength(1)

    unsubscribe()
    store.update({ factors: [] })
    expect(listener).toHaveBeenCalledTimes(1)
  })
})

describe('ThemeRotationEngine', () => {
  it('builds deterministic rotation summary from theme factors and previous runtime snapshot', () => {
    const previous = buildThemeRotationSummary(
      [
        factor({ themeId: 'AI', themeName: '人工智能', heatScore: 80, rank: 2 }),
        factor({ themeId: 'POWER', themeName: '电力设备', heatScore: 70, rank: 1, netInflow: -1000000 }),
      ],
      { timestamp: 1713750000000 },
    )

    const current = buildThemeRotationSummary(
      [
        factor({ themeId: 'AI', themeName: '人工智能', heatScore: 88, rank: 1 }),
        factor({
          themeId: 'POWER',
          themeName: '电力设备',
          heatScore: 40,
          rank: 2,
          netInflow: -60000000,
          rotationState: 'cooling',
        }),
      ],
      { timestamp: 1713751200000, previous },
    )

    expect(current.mainLines[0]).toMatchObject({ themeId: 'AI', persistentDays: 2, rankChange: 1 })
    expect(current.outflowThemes[0]).toMatchObject({ themeId: 'POWER', direction: 'outflow' })
    expect(current.marketPhase).toBe('rising')
  })
})

describe('ThemeAlertEngine', () => {
  it('creates structured theme events from factors and stock exposures', () => {
    const factors = [
      factor({ themeId: 'AI', themeName: '人工智能', snapshotId: 's1' }),
      factor({ themeId: 'POWER', themeName: '电力设备', rotationState: 'neutral', heatScore: 30 }),
    ]
    const exposures = projectThemeStockExposures(context(), factors)
    const events = buildThemeEvents({
      factors,
      exposures,
      previousFactors: [],
      timestamp: 1713751200000,
    })

    expect(events.map((event) => event.type)).toEqual(
      expect.arrayContaining(['theme_mainline_started', 'theme_strength_surge', 'theme_fund_inflow']),
    )
    expect(events[0]).toMatchObject({
      themeId: 'AI',
      source: 'theme',
    })
    expect(events[0].stockCodes.length).toBeGreaterThan(0)
  })

  it('does not emit strong events for fatal or empty quality factors', () => {
    const events = buildThemeEvents({
      factors: [
        factor({
          themeId: 'EMPTY',
          themeName: '空题材',
          heatScore: 90,
          rotationState: 'mainline',
          qualityFlags: [{ code: 'empty_theme', level: 'fatal', message: 'empty' }],
        }),
      ],
      timestamp: 1713751200000,
    })

    expect(events.some((event) => event.type === 'theme_mainline_started')).toBe(false)
    expect(events.map((event) => event.type)).toContain('theme_mapping_quality_warning')
  })
})

describe('ThemeFacade V3 compatibility', () => {
  it('refreshes runtime state and exposes hot theme and rotation compat views', () => {
    const result = refreshThemeFacadeState({
      context: {
        ...context(),
        rotationAnalysis: {
          timestamp: 1713751200000,
          inflowThemes: [],
          outflowThemes: [],
          mainLines: [{ themeId: 'BKAI', themeName: '人工智能', persistentDays: 2 } as any],
          quickRotation: [],
          rotationSpeed: 20,
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
      },
      emitAlerts: false,
    })
    const hotThemes = getHotThemesCompat(3)

    expect(result.factors[0].themeName).toBe('人工智能')
    expect(hotThemes[0]).toMatchObject({ id: 'AI', name: '人工智能' })
    expect(getRotationSummary()?.mainLines[0]?.themeId).toBe('AI')
  })
})

describe('ThemeFacade V4 UI compatibility', () => {
  it('exposes stable UI read models and immutable runtime snapshots', () => {
    const freshTimestamp = Date.now()
    refreshThemeFacadeState({ context: { ...context(), timestamp: freshTimestamp }, emitAlerts: false })

    const blocks = getJxbkBlocksCompat(5)
    const stockMap = getThemeStockMapCompat()
    const snapshot = getRuntimeSnapshot()

    snapshot.factors.push(factor({ themeId: 'MUTATED' }))
    snapshot.exposures.byCode.set('999999', [])

    expect(blocks[0]).toMatchObject({ code: 'BKAI', name: '人工智能', strength: 4200 })
    expect(getJxbkLastUpdate()).toBe(freshTimestamp)
    expect(stockMap).toEqual({})
    expect(getRuntimeSnapshot().factors.some((item) => item.themeId === 'MUTATED')).toBe(false)
    expect(getRuntimeSnapshot().exposures.byCode.has('999999')).toBe(false)
  })

  it('keeps factor, rotation and event output deterministic for the same context', () => {
    const first = refreshThemeFacadeState({ context: context(), emitAlerts: false })
    const second = refreshThemeFacadeState({ context: context(), emitAlerts: false })

    expect(second.factors).toEqual(first.factors)
    expect(second.rotationSummary).toEqual(first.rotationSummary)
    expect(second.events).toEqual(first.events)
  })

  it('refreshes JXBK feed before rebuilding factors when no explicit context is provided', async () => {
    const spy = vi.spyOn(jxbkThemeFeed, 'refreshBlocks').mockResolvedValue([])

    await refreshJxbkAndFactors({ skipJxbkRefresh: false, emitAlerts: false })

    expect(spy).toHaveBeenCalledWith({ force: undefined })
    spy.mockRestore()
  })

  it('falls back to fresh feed blocks when the last explicit context is stale', () => {
    refreshThemeFacadeState({
      context: {
        ...context(),
        timestamp: Date.now() - 10 * 60 * 1000,
      },
      emitAlerts: false,
    })
    dataLayer.updateJxbkBlocks([
      {
        code: 'BKNEW',
        name: '新鲜板块',
        strength: 5000,
        change: 5,
        mainNetInflow: 100000000,
        bigMoney300: 0,
        institutionBuy: 0,
        volumeRatio: 2,
        ztCount: 1,
      },
    ])

    expect(getJxbkBlocksCompat(1)[0]).toMatchObject({ code: 'BKNEW', name: '新鲜板块' })
  })

  it('returns cloned stock map entries so callers cannot mutate feed state', () => {
    dataLayer.updateJxbkStocks([{ code: '000001', name: '样本一', blocks: ['人工智能'] } as any])

    const stockMap = getThemeStockMapCompat()
    stockMap['000001'].blocks.push('污染板块')

    expect(getThemeStockMapCompat()['000001'].blocks).toEqual(['人工智能'])
  })
})
