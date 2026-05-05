import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/services/theme/ThemeFacade', () => ({
  themeFacade: {
    getThemeDetailCompat: vi.fn(() => ({
      heatScore: 82,
      momentum: 71,
      leaders: [{ code: '000001' }, { code: '000002' }],
    })),
  },
}))

vi.mock('@/services/DragonBreathAnalyzer', () => ({
  dragonBreathAnalyzer: {
    getMarketData: vi.fn(() => ({ zhabanRate: 0, fengbanRate: 0 })),
    getMarketSentiment: vi.fn(() => ({ phase: '启动' })),
  },
}))

import { themeFacade } from '@/services/theme/ThemeFacade'
import { buildSectorContext } from '../ContextBuilder'

describe('dragon ContextBuilder', () => {
  beforeEach(() => {
    ;(globalThis as any).window = {
      allData: {
        merged: [
          {
            code: '000001',
            name: '样本一',
            change: 10,
            themes: [{ name: '人工智能' }],
            limitTime: '09:35',
            fengdan: 1000,
          },
          {
            code: '000002',
            name: '样本二',
            change: 10,
            themes: [{ name: '人工智能' }],
            limitTime: '09:45',
            fengdan: 2000,
          },
        ],
      },
    }
  })

  it('builds sector context from themeFacade detail compat', () => {
    const context = buildSectorContext('人工智能')

    expect(themeFacade.getThemeDetailCompat).toHaveBeenCalledWith('人工智能')
    expect(context.sectorHeat).toBe(82)
    expect(context.sectorMomentum).toBe(71)
    expect(context.sectorLeaderCount).toBe(2)
    expect(context.firstLimitCode).toBe('000001')
    expect(context.maxFengdanCode).toBe('000002')
  })
})
