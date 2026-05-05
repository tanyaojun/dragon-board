import { describe, expect, it, vi } from 'vitest'
import { FACTORS } from '../factors'

vi.mock('@/services/theme/ThemeFacade', () => ({
  themeFacade: {
    getStockExposures: vi.fn((code?: string) =>
      code === '000001'
        ? [
            {
              themeId: 'AI',
              themeName: '人工智能',
              code: '000001',
              exposureWeight: 0.8,
              themeScore: 76,
              role: 'leader',
              roleScore: 90,
              themeContribution: 68,
              riskPenalty: 4,
              reasons: ['主线题材'],
            },
          ]
        : [],
    ),
    getThemeFactors: vi.fn(() => [
      {
        themeId: 'AI',
        themeName: '人工智能',
        momentumScore: 72,
        leadershipScore: 65,
      },
    ]),
  },
}))

vi.mock('@/services/DragonBreathAnalyzer', () => ({
  dragonBreathAnalyzer: {
    getMarketSentiment: vi.fn(() => ({ phase: '启动' })),
    getMarketData: vi.fn(() => ({ ztCount: 20, dtCount: 2 })),
  },
}))

describe('theme factors config', () => {
  it('calculates theme factors from themeFacade stock exposures', () => {
    const stock = { code: '000001' } as any

    expect(FACTORS.themeHeat.calculate(stock)).toBe(76)
    expect(FACTORS.themeLeaderCount.calculate(stock)).toBeGreaterThan(0)
    expect(FACTORS.themeMomentum.calculate(stock)).toBe(72)
  })

  it('returns stable zero values when a stock has no theme exposure', () => {
    const stock = { code: '999999' } as any

    expect(FACTORS.themeHeat.calculate(stock)).toBe(0)
    expect(FACTORS.themeLeaderCount.calculate(stock)).toBe(0)
    expect(FACTORS.themeMomentum.calculate(stock)).toBe(0)
  })
})
