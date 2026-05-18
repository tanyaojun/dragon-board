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
})
