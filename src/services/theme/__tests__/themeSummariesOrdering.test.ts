import { beforeEach, describe, expect, it, vi } from 'vitest'

import { dataLayer } from '@/services/DataLayer'
import { getThemeSummaries, refreshThemeFacadeState } from '../ThemeFacade'
import { themeHeatFeed } from '../ThemeHeatFeed'
import { themeRuntimeStore } from '../ThemeRuntimeStore'
import type { ThemeFactorSnapshot, ThemeSourceContext } from '../types'

// 涨停家数降序契约：ztCount 相同时按 heatScore 降序保持确定性
const THEME_FIXTURES = [
  { id: 'HIGH_ZT', name: '高涨停', ztCount: 8, heatScore: 95 },
  { id: 'HIGH_ZT_LOW_HEAT', name: '高涨停低热', ztCount: 8, heatScore: 70 },
  { id: 'MID_ZT', name: '中涨停', ztCount: 3, heatScore: 90 },
  { id: 'NO_ZT', name: '无涨停', ztCount: 0, heatScore: 99 },
]

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
    themes: THEME_FIXTURES.map((theme) => ({ id: theme.id, name: theme.name })),
    themeStocks: new Map(THEME_FIXTURES.map((theme) => [theme.id, ['000001']])),
    stockThemes: new Map([['000001', THEME_FIXTURES.map((theme) => theme.id)]]),
    stocks: [{ code: '000001', name: '样本一', change: 10, volumeRatio: 3, leadStatus: '龙一' }],
    rotationAnalysis: null,
    correlations: new Map(),
  }
}

describe('theme summaries order by ztCount desc', () => {
  beforeEach(() => {
    dataLayer.reset()
    themeRuntimeStore.clear()
    vi.spyOn(themeHeatFeed, 'getRuntimeFactors').mockReturnValue(
      THEME_FIXTURES.map((theme) =>
        factor({
          themeId: theme.id,
          themeName: theme.name,
          ztCount: theme.ztCount,
          heatScore: theme.heatScore,
        }),
      ),
    )
    refreshThemeFacadeState({ context: context(), emitAlerts: false })
  })

  it('orders all summaries by ztCount desc with heatScore tie-break', () => {
    expect(getThemeSummaries(Number.MAX_SAFE_INTEGER).map((theme) => theme.id)).toEqual([
      'HIGH_ZT',
      'HIGH_ZT_LOW_HEAT',
      'MID_ZT',
      'NO_ZT',
    ])
  })

  it('selects the top slice after ztCount ordering', () => {
    expect(getThemeSummaries(2).map((theme) => theme.id)).toEqual(['HIGH_ZT', 'HIGH_ZT_LOW_HEAT'])
  })
})
