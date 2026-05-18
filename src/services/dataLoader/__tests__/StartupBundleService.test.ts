import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('../../apiService', () => ({
  apiService: {
    get: api.get,
    post: api.post,
  },
}))

describe('StartupBundleService', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-18T09:30:00+08:00'))
    api.get.mockReset()
    api.post.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('rejects cached startup bundles from a different trading date', async () => {
    api.get.mockResolvedValue({
      data: {
        schemaVersion: 1,
        tradingDate: '2026-05-17',
        createdAt: Date.now(),
        platformData: {
          eastmoney: [{ code: '000001', name: '旧缓存' }],
        },
        stocks: [{ code: '000001', name: '旧缓存' }],
      },
      dragonMeta: {
        cache: {
          stale: false,
        },
      },
    })
    const { startupBundleService } = await import('../StartupBundleService')

    await expect(startupBundleService.read()).resolves.toBeNull()
  })

  it('marks cached volume ratio metadata stale when hydrating startup bundles', async () => {
    api.get.mockResolvedValue({
      data: {
        schemaVersion: 1,
        tradingDate: '2026-05-18',
        createdAt: Date.now(),
        platformData: {
          eastmoney: [{ code: '000001', name: '缓存数据' }],
        },
        stocks: [
          {
            code: '000001',
            name: '缓存数据',
            volume: 120000,
            volumeRatio: 99.99,
            volumeRatioMeta: {
              status: 'fresh',
              source: 'intraday_snapshot',
              calculatedAt: Date.now(),
              currentVolume: 100000,
              rawRatio: 135.2,
              capped: true,
            },
          },
        ],
      },
      dragonMeta: {
        cache: {
          stale: false,
        },
      },
    })
    const { startupBundleService } = await import('../StartupBundleService')

    const bundle = await startupBundleService.read()

    expect(bundle?.stocks[0]).toEqual(
      expect.objectContaining({
        volumeRatio: 99.99,
        volumeRatioMeta: expect.objectContaining({
          status: 'stale',
          source: 'intraday_snapshot',
          currentVolume: 120000,
          rawRatio: 135.2,
          capped: true,
          reason: 'startup_cache_hydrated',
        }),
      }),
    )
  })

  it('creates stale metadata for legacy cached naked volume ratios', async () => {
    api.get.mockResolvedValue({
      data: {
        schemaVersion: 1,
        tradingDate: '2026-05-18',
        createdAt: Date.now(),
        platformData: {
          eastmoney: [{ code: '000001', name: '旧缓存' }],
        },
        stocks: [
          {
            code: '000001',
            name: '旧缓存',
            volume: 88000,
            volumeRatio: 8.88,
          },
        ],
      },
      dragonMeta: {
        cache: {
          stale: false,
        },
      },
    })
    const { startupBundleService } = await import('../StartupBundleService')

    const bundle = await startupBundleService.read()

    expect(bundle?.stocks[0]).toEqual(
      expect.objectContaining({
        volumeRatio: 8.88,
        volumeRatioMeta: expect.objectContaining({
          status: 'stale',
          source: 'unavailable',
          currentVolume: 88000,
          reason: 'startup_cache_hydrated',
        }),
      }),
    )
  })
})
