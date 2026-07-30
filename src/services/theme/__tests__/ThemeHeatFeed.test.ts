import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiHttpError } from '@/services/apiService'
import { AppEvents } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { ThemeHeatFeed } from '../ThemeHeatFeed'
import type { ThemeHeatApiSnapshot } from '../types'


const apiSnapshot: ThemeHeatApiSnapshot = {
  computedAt: 1782018300000,
  cacheBucket: '2026-06-21T09:05:00+08:00',
  factorVersion: 'theme-market-v1',
  mappingVersion: 'theme-v8-test',
  factors: [
    {
      themeId: 'AI',
      themeName: '人工智能',
      source: 'market_aggregate',
      timestamp: 1782018300000,
      heatScore: 88,
      momentumScore: 90,
      breadthScore: 80,
      fundScore: null,
      leadershipScore: 75,
      correlationScore: 82,
      crowdingRisk: 20,
      persistenceScore: 60,
      rotationState: 'mainline',
      stockCount: 120,
      ztCount: 4,
      leaderCount: 2,
      netInflow: null,
      strength: 88,
      volumeRatio: 1.8,
      rank: 1,
      relatedThemeIds: [],
      qualityFlags: [],
      components: {
        breadthScore: 80,
        fundScore: null,
        leadershipScore: 75,
        correlationScore: 82,
        riskPenalty: 2.8,
      },
      rankEligible: true,
      degraded: true,
      metadata: {},
    },
    {
      themeId: 'LOW',
      themeName: '低覆盖',
      source: 'market_aggregate',
      timestamp: 1782018300000,
      heatScore: null,
      momentumScore: 0,
      breadthScore: 0,
      fundScore: null,
      leadershipScore: 0,
      correlationScore: 0,
      crowdingRisk: 0,
      persistenceScore: 0,
      rotationState: 'neutral',
      stockCount: 10,
      ztCount: 0,
      leaderCount: 0,
      netInflow: null,
      strength: 0,
      volumeRatio: 0,
      rank: 0,
      relatedThemeIds: [],
      qualityFlags: [],
      components: {
        breadthScore: 0,
        fundScore: null,
        leadershipScore: 0,
        correlationScore: 0,
        riskPenalty: 0,
      },
      rankEligible: false,
      degraded: true,
      metadata: {},
    },
  ],
  quality: {},
  sources: {},
}


describe('ThemeHeatFeed', () => {
  let api: {
    getThemeHeat: ReturnType<typeof vi.fn>
    getThemeHeatStocks: ReturnType<typeof vi.fn>
  }

  beforeEach(() => {
    api = {
      getThemeHeat: vi.fn().mockResolvedValue({ ok: true, data: apiSnapshot }),
      getThemeHeatStocks: vi.fn().mockResolvedValue({
        ok: true,
        data: {
          stocks: [{ code: '000001', name: '样本', change: 6, price: 10, rank: 1 }],
        },
      }),
    }
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('keeps nullable audit factors separate from runtime factors', async () => {
    const feed = new ThemeHeatFeed(api as any)

    await feed.refresh()

    expect(feed.getSnapshot()?.factors).toHaveLength(2)
    expect(feed.getRuntimeFactors()).toHaveLength(1)
    expect(feed.getRuntimeFactors()[0]).toMatchObject({
      themeId: 'AI',
      source: 'market_aggregate',
      heatScore: 88,
      fundScore: null,
    })
  })

  it('coalesces concurrent refresh requests', async () => {
    const feed = new ThemeHeatFeed(api as any)

    const [first, second] = await Promise.all([feed.refresh(), feed.refresh()])

    expect(first).toBe(second)
    expect(api.getThemeHeat).toHaveBeenCalledTimes(1)
  })

  it('keeps last success explicit when refresh returns stale failure', async () => {
    const feed = new ThemeHeatFeed(api as any)
    await feed.refresh()
    api.getThemeHeat.mockRejectedValueOnce(
      new ApiHttpError({
        method: 'GET',
        url: 'http://localhost:3000/api/themes/heat',
        status: 503,
        statusText: 'Service Unavailable',
        body: { errorCode: 'quote_coverage_blocked', staleData: apiSnapshot },
      }),
    )

    await expect(feed.refresh({ force: true })).rejects.toThrow('quote_coverage_blocked')

    expect(feed.getSnapshot()).toMatchObject({ stale: true, factors: expect.any(Array) })
  })

  it('loads and caches normalized theme stock details', async () => {
    const feed = new ThemeHeatFeed(api as any)

    const first = await feed.loadThemeStocks('AI', { limit: 40 })
    const second = await feed.loadThemeStocks('AI', { limit: 40 })

    expect(first).toEqual(second)
    expect(first[0]).toMatchObject({ code: '000001', role: 'follower', qualityFlags: [] })
    expect(api.getThemeHeatStocks).toHaveBeenCalledTimes(1)

    feed.clear()
  })

  it('patches cached theme stocks immediately and debounces one factor refresh', async () => {
    vi.useFakeTimers()
    const feed = new ThemeHeatFeed(api as any)
    await feed.loadThemeStocks('AI')
    api.getThemeHeat.mockClear()

    EventManager.emit(AppEvents.WEBSOCKET.QUOTE_PATCH, {
      items: [
        { code: '000001', zlje: 88, version: 2, moneyFlowSource: 'ths_main_monitor' },
      ],
    })

    expect((await feed.loadThemeStocks('AI'))[0].mainNetInflow).toBe(88)
    expect(api.getThemeHeat).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(300)
    expect(api.getThemeHeat).toHaveBeenCalledTimes(1)

    EventManager.emit(AppEvents.WEBSOCKET.QUOTE_PATCH, {
      items: [
        { code: '000001', zlje: 1, version: 1, moneyFlowSource: 'ths_main_monitor' },
      ],
    })
    expect((await feed.loadThemeStocks('AI'))[0].mainNetInflow).toBe(88)
    feed.destroy()
  })
})
