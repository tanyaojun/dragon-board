import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiService } from '../../apiService'
import {
  refreshThemeFacadeState,
  getHotThemes,
  loadThemeMomentumScores,
} from '../ThemeFacade'
import { themeHeatFeed } from '../ThemeHeatFeed'
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
    rotationAnalysis: null,
    correlations: new Map(),
  }
}

function momentumSummary(factors: { themeId: string; score: number | null }[]) {
  return {
    ok: true,
    status: 'ok',
    version: 'theme_momentum_v2',
    factors: factors.map((f) => ({
      themeId: f.themeId,
      themeName: f.themeId,
      score: f.score,
      direction: 'up' as const,
      phaseLabel: '扩散',
    })),
    qualityFlags: [],
    computedAt: 1713751200000,
  }
}

function setupFactors() {
  vi.spyOn(themeHeatFeed, 'getRuntimeFactors').mockReturnValue([
    factor({ themeId: 'AI', themeName: '人工智能' }),
    factor({ themeId: 'POWER', themeName: '电力设备', momentumScore: 82 }),
  ])
  refreshThemeFacadeState({ context: context(), emitAlerts: false })
}

function momentumApiCalls(spy: ReturnType<typeof vi.spyOn>) {
  return spy.mock.calls.filter(([url]) => String(url).includes('/api/theme-momentum/summary'))
}

// 注意：ThemeFacade 的 v2 缓存为模块级单例（momentumScoresLoaded / lastMomentumScoreMap），
// 用例之间共享；因此用例按「状态演进」设计，重载统一走 force 路径。
describe('theme momentum v2 unification in getHotThemes', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('keeps heat-engine values when v2 load fails, then overrides after a successful retry', async () => {
    setupFactors()
    vi.spyOn(apiService, 'get').mockResolvedValue(null)

    await loadThemeMomentumScores()

    expect(getHotThemes(10).find((theme) => theme.id === 'AI')?.momentumScore).toBe(82)
    // getHotThemes 会惰性触发一次加载（仍返回 null）；等它在途请求收尾后再重试
    await new Promise((resolve) => setTimeout(resolve, 0))
    // 失败不置已加载：下次访问允许重试
    vi.mocked(apiService.get).mockResolvedValue(momentumSummary([{ themeId: 'AI', score: 91 }]))
    await loadThemeMomentumScores()
    expect(getHotThemes(10).find((theme) => theme.id === 'AI')?.momentumScore).toBe(91)
  })

  it('uses v2 momentum score, overriding the heat-engine value', async () => {
    setupFactors()
    vi.spyOn(apiService, 'get').mockResolvedValue(momentumSummary([{ themeId: 'AI', score: 88 }]))

    await loadThemeMomentumScores(true)

    const ai = getHotThemes(10).find((theme) => theme.id === 'AI')
    expect(ai?.momentumScore).toBe(88)
    expect(ai?.momentum).toBe(88)
  })

  it('falls back to the heat-engine momentum score when v2 has no result for a theme', async () => {
    setupFactors()
    const getSpy = vi.spyOn(apiService, 'get').mockResolvedValue(
      momentumSummary([{ themeId: 'AI', score: 88 }]),
    )

    await loadThemeMomentumScores(true)

    expect(getHotThemes(10).find((theme) => theme.id === 'POWER')?.momentumScore).toBe(82)
    expect(momentumApiCalls(getSpy)).toHaveLength(1)
  })

  it('does not re-request the momentum endpoint once loaded (idempotent)', async () => {
    setupFactors()
    const getSpy = vi.spyOn(apiService, 'get').mockResolvedValue(
      momentumSummary([{ themeId: 'AI', score: 88 }]),
    )

    await loadThemeMomentumScores(true)
    getSpy.mockClear()

    await loadThemeMomentumScores()
    await loadThemeMomentumScores()
    getHotThemes(10)
    getHotThemes(10)

    expect(momentumApiCalls(getSpy)).toHaveLength(0)
  })
})
