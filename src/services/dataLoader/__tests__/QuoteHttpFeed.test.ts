import { describe, expect, it, vi } from 'vitest'

import { QuoteHttpFeed } from '../QuoteHttpFeed'

describe('QuoteHttpFeed', () => {
  it('fetches and normalizes Tencent quote rows without projecting fund fields', async () => {
    const getQuotes = vi.fn().mockResolvedValue({
      data: {
        diff: [{
          f12: 'SZ000001',
          f2: '10.5',
          f3: '2.1',
          f6: '1200',
          f5: '500000',
          f8: '3.2',
          f9: '12',
          f10: '1.4',
          f23: '1.5',
          f14: '平安银行',
          f20: '100',
          f21: '80',
          f62: '2000',
        }],
      },
    })
    const feed = new QuoteHttpFeed({ api: { getQuotes }, sleep: async () => undefined })

    const result = await feed.fetchFromTencent(['000001'])

    expect(getQuotes).toHaveBeenCalledWith(['000001'], { source: 'tencent' })
    expect(result.get('000001')).toMatchObject({
      price: 10.5,
      change: 2.1,
      volume: 1200,
      turnover: 500000,
      volumeRatio: 1.4,
      source: 'tencent',
      totalMV: 1_000_000,
      cirMV: 800_000,
    })
    expect(result.get('000001')).not.toHaveProperty('zlje')
  })

  it('falls back to Sina when Tencent basic quote fetch fails', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const getQuotes = vi
      .fn()
      .mockRejectedValueOnce(new Error('tencent down'))
      .mockResolvedValueOnce({
        data: { diff: [{ f12: '600001', f2: '8.8', f3: '-1.1', f6: '100', f5: '2000', f14: '样本股' }] },
      })
    const feed = new QuoteHttpFeed({ api: { getQuotes }, sleep: async () => undefined })

    const result = await feed.fetchBasicData(['600001'])

    expect(getQuotes).toHaveBeenNthCalledWith(1, ['600001'], { source: 'tencent' })
    expect(getQuotes).toHaveBeenNthCalledWith(2, ['600001'], { source: 'sina' })
    expect(result.get('600001')).toMatchObject({ price: 8.8, change: -1.1, source: 'sina' })
    warn.mockRestore()
  })

  it('batches basic quote requests in groups of 50', async () => {
    const codes = Array.from({ length: 101 }, (_, index) => String(600000 + index))
    const getQuotes = vi.fn().mockImplementation(async (batch: string[]) => ({
      data: { diff: batch.map(code => ({ f12: code, f2: '10' })) },
    }))
    const sleep = vi.fn().mockResolvedValue(undefined)
    const feed = new QuoteHttpFeed({ api: { getQuotes }, sleep })

    const result = await feed.fetchFromTencent(codes)

    expect(getQuotes).toHaveBeenCalledTimes(3)
    expect(getQuotes.mock.calls.map(call => call[0].length)).toEqual([50, 50, 1])
    expect(sleep).toHaveBeenCalledTimes(2)
    expect(result.size).toBe(101)
  })

  it('does not request fund rows during full quote refresh', async () => {
    const getQuotes = vi.fn()
    const feed = new QuoteHttpFeed({ api: { getQuotes } as any })

    const result = await feed.fetchFullData(['000001'], true)

    expect(result.size).toBe(0)
    expect(getQuotes).not.toHaveBeenCalled()
  })

  it('does not project fund fields from basic quote responses', async () => {
    const getQuotes = vi.fn().mockResolvedValue({
      data: { diff: [{ f12: '000001', f2: 10, f3: 2, f62: 999 }] },
    })
    const feed = new QuoteHttpFeed({ api: { getQuotes } as any, sleep: async () => {} })

    const row = (await feed.fetchBasicData(['000001'])).get('000001')

    expect(row).not.toHaveProperty('zlje')
  })
})
