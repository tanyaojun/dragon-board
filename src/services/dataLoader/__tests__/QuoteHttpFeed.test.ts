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
            f10: '1.4',
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
      volumeRatio: 1.4,
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
            f10: '1.88',
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
      expect.objectContaining({ source: 'eastmoney', force: true, refresh: '1' }),
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
      volumeRatio: 1.88,
    })
  })

  it('fills missing EastMoney main money flow from Sina and estimates main ratio from turnover', async () => {
    const getQuotes = vi
      .fn()
      .mockResolvedValueOnce({
        data: {
          diff: [
            {
              f12: '600522',
              f2: '49.53',
              f3: '7.51',
              f5: '5131565',
              f6: '25205130127',
              f10: '1.4',
              f62: '0',
              f184: '0',
              f14: '中天科技',
            },
          ],
        },
      })
      .mockResolvedValueOnce({
        data: {
          diff: [
            {
              f12: '600522',
              f14: '中天科技',
              f62: '5450857714.71',
            },
          ],
        },
      })
    const feed = new QuoteHttpFeed({ api: { getQuotes }, sleep: async () => undefined })

    const result = await feed.fetchFullData(['600522'], true)

    expect(getQuotes).toHaveBeenNthCalledWith(
      2,
      ['600522'],
      expect.objectContaining({ source: 'sinaMoneyFlow', force: true }),
    )
    expect(result.get('600522')).toMatchObject({
      zlje: 5450857714.71,
      zljzb: 21.63,
      moneyFlowSource: 'sina',
      moneyFlowEstimated: true,
      capitalFlowSource: 'sina_money_flow',
      capitalFlowConfidence: 'low',
    })
  })

  it('requests all missing Sina money flow rows in batches of 20', async () => {
    const codes = Array.from({ length: 25 }, (_, index) => String(600000 + index))
    const getQuotes = vi
      .fn()
      .mockResolvedValueOnce({
        data: {
          diff: codes.map((code) => ({
            f12: code,
            f6: '10000',
            f62: '0',
            f184: '0',
          })),
        },
      })
      .mockResolvedValueOnce({
        data: {
          diff: codes.slice(0, 20).map((code, index) => ({
            f12: code,
            f62: String((index + 1) * 100),
          })),
        },
      })
      .mockResolvedValueOnce({
        data: {
          diff: codes.slice(20).map((code, index) => ({
            f12: code,
            f62: String((index + 21) * 100),
          })),
        },
      })
    const feed = new QuoteHttpFeed({ api: { getQuotes }, sleep: async () => undefined })

    const result = await feed.fetchFullData(codes, true)

    expect(getQuotes).toHaveBeenNthCalledWith(
      2,
      codes.slice(0, 20),
      expect.objectContaining({ source: 'sinaMoneyFlow', force: true, timeout: 20000 }),
    )
    expect(getQuotes).toHaveBeenNthCalledWith(
      3,
      codes.slice(20),
      expect.objectContaining({ source: 'sinaMoneyFlow', force: true, timeout: 20000 }),
    )
    expect(result.get(codes[24])).toMatchObject({
      zlje: 2500,
      zljzb: 25,
      moneyFlowSource: 'sina',
    })
  })

  it('retries Sina money-flow batch as single-code requests when a throttled code skips the whole batch', async () => {
    const getQuotes = vi
      .fn()
      .mockResolvedValueOnce({
        data: { diff: [] },
        dragonMeta: {
          requested: 2,
          returned: 0,
          failed: 2,
          failures: [
            { code: '600745', error: 'native fetch failed with HTTP 456' },
            { code: '603773', error: 'skipped after HTTP 456' },
          ],
        },
      })
      .mockResolvedValueOnce({
        data: { diff: [] },
        dragonMeta: { requested: 1, returned: 0, failed: 1 },
      })
      .mockResolvedValueOnce({
        data: {
          diff: [
            {
              f12: '603773',
              f14: '沃格光电',
              f62: '197969013.5',
            },
          ],
        },
        dragonMeta: { requested: 1, returned: 1, failed: 0 },
      })
    const feed = new QuoteHttpFeed({ api: { getQuotes }, sleep: async () => undefined })

    const result = await feed.fetchFromSinaMoneyFlow(['600745', '603773'], false)

    expect(getQuotes).toHaveBeenNthCalledWith(
      1,
      ['600745', '603773'],
      expect.objectContaining({ source: 'sinaMoneyFlow', force: false }),
    )
    expect(getQuotes).toHaveBeenNthCalledWith(
      2,
      ['600745'],
      expect.objectContaining({ source: 'sinaMoneyFlow', force: false }),
    )
    expect(getQuotes).toHaveBeenNthCalledWith(
      3,
      ['603773'],
      expect.objectContaining({ source: 'sinaMoneyFlow', force: false }),
    )
    expect(result.get('603773')).toMatchObject({
      zlje: 197969013.5,
      moneyFlowSource: 'sina',
    })
  })

  it('falls back to Sina money flow when EastMoney full quote request fails', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const getQuotes = vi
      .fn()
      .mockRejectedValueOnce(new Error('eastmoney throttled'))
      .mockResolvedValueOnce({
        data: {
          diff: [
            {
              f12: '600522',
              f14: '中天科技',
              f62: '5450857714.71',
            },
          ],
        },
      })
    const feed = new QuoteHttpFeed({ api: { getQuotes }, sleep: async () => undefined })

    const result = await feed.fetchFullData(['600522'], true)

    expect(getQuotes).toHaveBeenNthCalledWith(
      2,
      ['600522'],
      expect.objectContaining({ source: 'sinaMoneyFlow', force: true }),
    )
    expect(result.get('600522')).toMatchObject({
      zlje: 5450857714.71,
      moneyFlowSource: 'sina',
    })
    warn.mockRestore()
  })
})
