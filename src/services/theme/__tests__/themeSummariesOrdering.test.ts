import { beforeEach, describe, expect, it, vi } from 'vitest'

import { dataLayer } from '@/services/DataLayer'
import { getThemeSummaries, refreshThemeFacadeState, resetThemeSortSpec, setThemeSortSpec } from '../ThemeFacade'
import { themeHeatFeed } from '../ThemeHeatFeed'
import { themeRuntimeStore } from '../ThemeRuntimeStore'
import type { ThemeFactorSnapshot, ThemeSourceContext } from '../types'

// 三键降序契约：heatScore → ztCount → momentumScore 依次降序保持确定性。
// ZT_TOP（涨停 8、动量 99）热度垫底排第五，用于证明主键不是涨停数/动量。
const THEME_FIXTURES = [
  { id: 'HEAT_TOP', name: '热度最高', heatScore: 99, ztCount: 0, momentum: 10 },
  { id: 'TIE_MORE_ZT', name: '同热度多涨停', heatScore: 70, ztCount: 5, momentum: 50 },
  { id: 'TIE_MOM_HIGH', name: '同热度同涨停高动量', heatScore: 70, ztCount: 2, momentum: 90 },
  { id: 'TIE_MOM_LOW', name: '同热度同涨停低动量', heatScore: 70, ztCount: 2, momentum: 60 },
  { id: 'ZT_TOP', name: '涨停最多', heatScore: 55, ztCount: 8, momentum: 99 },
  { id: 'HEAT_LAST', name: '热度最低', heatScore: 5, ztCount: 0, momentum: 10 },
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

describe('theme summaries order by heat/zt/momentum desc', () => {
  beforeEach(() => {
    dataLayer.reset()
    themeRuntimeStore.clear()
    resetThemeSortSpec()
    vi.spyOn(themeHeatFeed, 'getRuntimeFactors').mockReturnValue(
      THEME_FIXTURES.map((theme) =>
        factor({
          themeId: theme.id,
          themeName: theme.name,
          heatScore: theme.heatScore,
          ztCount: theme.ztCount,
          momentumScore: theme.momentum,
        }),
      ),
    )
    refreshThemeFacadeState({ context: context(), emitAlerts: false })
  })

  it('orders all summaries by heatScore/ztCount/momentumScore desc', () => {
    expect(getThemeSummaries(Number.MAX_SAFE_INTEGER).map((theme) => theme.id)).toEqual([
      'HEAT_TOP',
      'TIE_MORE_ZT',
      'TIE_MOM_HIGH',
      'TIE_MOM_LOW',
      'ZT_TOP',
      'HEAT_LAST',
    ])
  })

  it('selects the top slice after heat/zt ordering', () => {
    expect(getThemeSummaries(2).map((theme) => theme.id)).toEqual(['HEAT_TOP', 'TIE_MORE_ZT'])
  })

  it('keeps heatScore as the primary sort key on each summary', () => {
    const summaries = getThemeSummaries(Number.MAX_SAFE_INTEGER)
    expect(summaries.map((theme) => theme.heatScore)).toEqual([99, 70, 70, 70, 55, 5])
  })

  it('reorders summaries when the user sort spec changes', () => {
    setThemeSortSpec([{ field: 'momentumScore', direction: 'desc' }])
    expect(getThemeSummaries(Number.MAX_SAFE_INTEGER).map((theme) => theme.id)).toEqual([
      // 动量降序：99/90/60/50；同动量 10 的按补位热度排
      'ZT_TOP',
      'TIE_MOM_HIGH',
      'TIE_MOM_LOW',
      'TIE_MORE_ZT',
      'HEAT_TOP',
      'HEAT_LAST',
    ])
  })

  it('normalizes an invalid user spec back to the default ordering', () => {
    setThemeSortSpec([{ field: 'hack', direction: 'desc' }])
    expect(getThemeSummaries(Number.MAX_SAFE_INTEGER).map((theme) => theme.id)).toEqual([
      'HEAT_TOP',
      'TIE_MORE_ZT',
      'TIE_MOM_HIGH',
      'TIE_MOM_LOW',
      'ZT_TOP',
      'HEAT_LAST',
    ])
  })

  it('restores the default ordering after reset', () => {
    setThemeSortSpec([{ field: 'momentumScore', direction: 'desc' }])
    resetThemeSortSpec()
    expect(getThemeSummaries(Number.MAX_SAFE_INTEGER).map((theme) => theme.id)).toEqual([
      'HEAT_TOP',
      'TIE_MORE_ZT',
      'TIE_MOM_HIGH',
      'TIE_MOM_LOW',
      'ZT_TOP',
      'HEAT_LAST',
    ])
  })
})
