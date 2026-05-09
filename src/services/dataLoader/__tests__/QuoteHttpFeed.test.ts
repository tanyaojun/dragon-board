import { describe, expect, it, vi } from 'vitest'

import { QuoteHttpFeed } from '../QuoteHttpFeed'

describe('QuoteHttpFeed', () => {
  it('fetches and normalizes Tencent quote rows', async () => {
    const getQuotes = vi.fn().mockResolvedValue({
      data: {
        diff: [
          {
            f12: 'SZ000001',
            f2: '10.5',
            f3: '2.1',
            f6: '1200',
            f5: '500000',
            f8: '3.2',
            f9: '12',
            f23: '1.5',
            f14: '平安银行',
            f20: '100',
            f21: '80',
            f62: '2000',
            f184: '4.5',
            f66: '900',
            f69: '1.2',
          },
        ],
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
      source: 'tencent',
      totalMV: 1_000_000,
      cirMV: 800_000,
      zlje: 2000,
    })
  })

  it('falls back to Sina when Tencent basic quote fetch fails', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const getQuotes = vi
      .fn()
      .mockRejectedValueOnce(new Error('tencent down'))
      .mockResolvedValueOnce({
        data: {
          diff: [
            {
              f12: '600001',
              f2: '8.8',
              f3: '-1.1',
              f6: '100',
              f5: '2000',
              f14: '样本股',
            },
          ],
        },
      })

    const feed = new QuoteHttpFeed({ api: { getQuotes }, sleep: async () => undefined })
    const result = await feed.fetchBasicData(['600001'])

    expect(getQuotes).toHaveBeenNthCalledWith(1, ['600001'], { source: 'tencent' })
    expect(getQuotes).toHaveBeenNthCalledWith(2, ['600001'], { source: 'sina' })
    expect(result.get('600001')).toMatchObject({
      price: 8.8,
      change: -1.1,
      source: 'sina',
    })
    warn.mockRestore()
  })

  it('skips EastMoney full quote fetch when enrichment is disabled', async () => {
    const getQuotes = vi.fn()
    const feed = new QuoteHttpFeed({
      api: { getQuotes },
      eastmoneyQuoteEnrichmentEnabled: false,
      sleep: async () => undefined,
    })

    const result = await feed.fetchFullData(['000001'], true)

    expect(result.size).toBe(0)
    expect(getQuotes).not.toHaveBeenCalled()
  })

  it('fetches EastMoney full quote enrichment by default', async () => {
    const getQuotes = vi.fn().mockResolvedValue({
      data: {
        diff: [
          {
            f12: '000001',
            f2: '10.5',
            f3: '2.1',
            f5: '1200',
            f6: '500000',
            f62: '8000',
            f184: '6.5',
            f66: '3000',
            f69: '2.4',
            f14: '平安银行',
          },
        ],
      },
    })
    const feed = new QuoteHttpFeed({ api: { getQuotes }, sleep: async () => undefined })

    const result = await feed.fetchFullData(['000001'], true)

    expect(getQuotes).toHaveBeenCalledWith(
      ['000001'],
      expect.objectContaining({ source: 'eastmoney', force: true }),
    )
    expect(result.get('000001')).toMatchObject({
      source: 'eastmoney',
      moneyFlowSource: 'eastmoney',
      moneyFlowEstimated: false,
      capitalFlowSource: 'official_l2',
      capitalFlowConfidence: 'medium',
      zlje: 8000,
      zljzb: 6.5,
      cddje: 3000,
      cddjzb: 2.4,
    })
  })
})
