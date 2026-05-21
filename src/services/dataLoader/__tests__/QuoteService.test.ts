import { describe, expect, it, vi } from 'vitest'

import { QuoteService } from '../QuoteService'
import type { MergedQuoteData } from '../types'

function httpQuote(overrides: Partial<MergedQuoteData> = {}): MergedQuoteData {
  return {
    price: 10,
    change: 1,
    volume: 1000,
    turnover: 10000,
    turnoverRate: 2,
    pe: 10,
    totalMV: 100000,
    cirMV: 90000,
    pb: 1,
    zlje: 0,
    zljzb: 0,
    cddje: 0,
    cddjzb: 0,
    sources: ['tencent'],
    confidence: 70,
    timestamp: 1,
    ...overrides,
  }
}

describe('QuoteService', () => {
  it('uses realtime quotes first and lets EastMoney real fund flow replace TDX estimates', async () => {
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => true,
      webSocketService: {
        getQuotesBatch: () =>
          new Map([
            [
              '000001',
              {
                code: '000001',
                lastPrice: 11,
                changePct: 3,
                volume: 2000,
                amount: 22000,
                tdxBuyVolume: 100,
                tdxSellVolume: 50,
                tdxCurrentVolume: 20,
              },
            ],
          ]),
      },
      dataLayer: {
        getQuote: () => null,
        getStock: () => ({ code: '000001', turnoverRate: 0 }),
        updateQuote: vi.fn(),
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(new Map()),
        fetchFullData: vi.fn().mockResolvedValue(
          new Map([
            [
              '000001',
              {
                ...httpQuote({
                  source: 'eastmoney',
                  zlje: 5000,
                  zljzb: 5,
                  cddje: 2000,
                  cddjzb: 2,
                  moneyFlowSource: 'eastmoney',
                  moneyFlowEstimated: false,
                }),
                source: 'eastmoney',
              },
            ],
          ]),
        ),
      },
    })

    const result = await service.fetchMergedQuotes(['000001'], { force: true })
    const quote = result.get('000001')

    expect(quote?.price).toBe(11)
    expect(quote?.moneyFlowSource).toBe('eastmoney')
    expect(quote?.zlje).toBe(5000)
    expect(quote?.sources).toEqual(['tdx_l2', 'eastmoney'])
  })

  it('uses EastMoney fund flow when realtime L1 has no QMT L2 money flow', async () => {
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => true,
      webSocketService: {
        getQuotesBatch: () =>
          new Map([
            [
              '000001',
              {
                code: '000001',
                lastPrice: 11,
                changePct: 3,
                volume: 2000,
                amount: 22000,
              },
            ],
          ]),
      },
      dataLayer: {
        getQuote: () => null,
        getStock: () => ({ code: '000001', turnoverRate: 0 }),
        updateQuote: vi.fn(),
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(new Map()),
        fetchFullData: vi.fn().mockResolvedValue(
          new Map([
            [
              '000001',
              {
                ...httpQuote({
                  source: 'eastmoney',
                  zlje: 9000,
                  zljzb: 7,
                  cddje: 4000,
                  cddjzb: 3,
                  moneyFlowSource: 'eastmoney',
                  moneyFlowEstimated: false,
                }),
                source: 'eastmoney',
              },
            ],
          ]),
        ),
      },
    })

    const result = await service.fetchMergedQuotes(['000001'], { force: true })
    const quote = result.get('000001')

    expect(quote?.moneyFlowSource).toBe('eastmoney')
    expect(quote?.moneyFlowEstimated).toBe(false)
    expect(quote?.zlje).toBe(9000)
    expect(quote?.cddje).toBe(4000)
  })

  it('keeps Tencent quote supplement fields when EastMoney only supplies money flow', async () => {
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => false,
      webSocketService: { getQuotesBatch: () => new Map() },
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote: vi.fn(),
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(
          new Map([
            [
              '600584',
              {
                ...httpQuote({
                  source: 'tencent',
                  price: 66.84,
                  change: 0.94,
                  volume: 3_125_058,
                  turnover: 21_324_471_319,
                  turnoverRate: 17.46,
                  pe: 72.39,
                  totalMV: 119_604_000_000,
                  cirMV: 119_604_000_000,
                  pb: 4.16,
                }),
                source: 'tencent',
              },
            ],
          ]),
        ),
        fetchFullData: vi.fn().mockResolvedValue(
          new Map([
            [
              '600584',
              {
                ...httpQuote({
                  source: 'eastmoney',
                  price: 0,
                  change: 0,
                  volume: 0,
                  turnover: 0,
                  turnoverRate: 0,
                  pe: 0,
                  totalMV: 0,
                  cirMV: 0,
                  pb: 0,
                  zlje: -970465792,
                  zljzb: -4.55,
                  cddje: -1080225280,
                  cddjzb: -5.07,
                  moneyFlowSource: 'eastmoney',
                  moneyFlowEstimated: false,
                  capitalFlowSource: 'official_l2',
                  capitalFlowConfidence: 'medium',
                }),
                source: 'eastmoney',
              },
            ],
          ]),
        ),
      },
    })

    const result = await service.fetchMergedQuotes(['600584'], { force: true })
    const quote = result.get('600584')

    expect(quote).toMatchObject({
      price: 66.84,
      turnoverRate: 17.46,
      pe: 72.39,
      totalMV: 119_604_000_000,
      cirMV: 119_604_000_000,
      pb: 4.16,
      zlje: -970465792,
      zljzb: -4.55,
      cddje: -1080225280,
      cddjzb: -5.07,
      moneyFlowSource: 'eastmoney',
    })
  })

  it('does not label basic-source fund flow as EastMoney when EastMoney has no fund flow', async () => {
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => false,
      webSocketService: { getQuotesBatch: () => new Map() },
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote: vi.fn(),
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(
          new Map([
            [
              '600584',
              {
                ...httpQuote({
                  source: 'tencent',
                  zlje: 12_000,
                  zljzb: 1.2,
                  cddje: 6_000,
                  cddjzb: 0.6,
                }),
                source: 'tencent',
              },
            ],
          ]),
        ),
        fetchFullData: vi.fn().mockResolvedValue(
          new Map([
            [
              '600584',
              {
                ...httpQuote({
                  source: 'eastmoney',
                  zlje: 0,
                  zljzb: 0,
                  cddje: 0,
                  cddjzb: 0,
                  moneyFlowSource: 'eastmoney',
                  moneyFlowEstimated: false,
                  capitalFlowSource: 'official_l2',
                  capitalFlowConfidence: 'medium',
                }),
                source: 'eastmoney',
              },
            ],
          ]),
        ),
      },
    })

    const result = await service.fetchMergedQuotes(['600584'], { force: true })
    const quote = result.get('600584')

    expect(quote).toMatchObject({
      zlje: 12_000,
      zljzb: 1.2,
      cddje: 6_000,
      cddjzb: 0.6,
    })
    expect(quote?.moneyFlowSource).toBeUndefined()
    expect(quote?.moneyFlowEstimated).toBeUndefined()
    expect(quote?.capitalFlowSource).toBeUndefined()
  })

  it('uses HTTP quote supplement fields when realtime TDX quote has no valuation fields', async () => {
    const fetchBasicData = vi.fn().mockResolvedValue(
      new Map([
        [
          '600584',
          {
            ...httpQuote({
              source: 'tencent',
              turnoverRate: 17.46,
              pe: 72.39,
              totalMV: 119_604_000_000,
              cirMV: 119_604_000_000,
              pb: 4.16,
            }),
            source: 'tencent',
          },
        ],
      ]),
    )
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => true,
      webSocketService: {
        getQuotesBatch: () =>
          new Map([
            [
              '600584',
              {
                code: '600584',
                lastPrice: 66.84,
                changePct: 0.94,
                volume: 3_125_058,
                amount: 21_324_471_319,
              },
            ],
          ]),
      },
      dataLayer: {
        getQuote: () => null,
        getStock: () => ({ code: '600584' }),
        updateQuote: vi.fn(),
      },
      feed: {
        fetchBasicData,
        fetchFullData: vi.fn().mockResolvedValue(new Map()),
      },
    })

    const result = await service.fetchMergedQuotes(['600584'], { force: true })
    const quote = result.get('600584')

    expect(fetchBasicData).toHaveBeenCalledWith(['600584'])
    expect(quote).toMatchObject({
      price: 66.84,
      turnoverRate: 17.46,
      pe: 72.39,
      totalMV: 119_604_000_000,
      cirMV: 119_604_000_000,
      pb: 4.16,
    })
  })

  it('still enriches from EastMoney when cached realtime money flow is only an L1 estimate', async () => {
    const fetchFullData = vi.fn().mockResolvedValue(
      new Map([
        [
          '000001',
          {
            ...httpQuote({
              source: 'eastmoney',
              zlje: -9700,
              zljzb: -4.5,
              cddje: -10800,
              cddjzb: -5.1,
              moneyFlowSource: 'eastmoney',
              moneyFlowEstimated: false,
            }),
            source: 'eastmoney',
          },
        ],
      ]),
    )
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => true,
      webSocketService: {
        getQuotesBatch: () =>
          new Map([
            [
              '000001',
              {
                code: '000001',
                lastPrice: 11,
                changePct: 3,
                volume: 2000,
                amount: 22000,
                tdxBuyVolume: 100,
                tdxSellVolume: 50,
              },
            ],
          ]),
      },
      dataLayer: {
        getQuote: () => ({
          ...httpQuote({
            zlje: 5460,
            zljzb: 2.56,
            cddje: 0,
            cddjzb: 0,
            moneyFlowSource: 'tdx_estimate',
            moneyFlowEstimated: true,
            capitalFlowSource: 'estimated_l1',
            capitalFlowConfidence: 'low',
          }),
        }),
        getStock: () => ({ code: '000001', turnoverRate: 2 }),
        updateQuote: vi.fn(),
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(new Map()),
        fetchFullData,
      },
    })

    const result = await service.fetchMergedQuotes(['000001'], { force: true })
    const quote = result.get('000001')

    expect(fetchFullData).toHaveBeenCalledWith(['000001'], true)
    expect(quote?.moneyFlowSource).toBe('eastmoney')
    expect(quote?.moneyFlowEstimated).toBe(false)
    expect(quote?.zlje).toBe(-9700)
    expect(quote?.cddje).toBe(-10800)
  })

  it('keeps existing EastMoney fund flow when realtime L1 estimates are the only live update', async () => {
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => true,
      webSocketService: {
        getQuotesBatch: () =>
          new Map([
            [
              '000001',
              {
                code: '000001',
                lastPrice: 11,
                changePct: 3,
                volume: 2000,
                amount: 22000,
                tdxBuyVolume: 100,
                tdxSellVolume: 50,
                tdxCurrentVolume: 20,
              },
            ],
          ]),
      },
      dataLayer: {
        getQuote: () => null,
        getStock: () => ({
          code: '000001',
          turnoverRate: 0,
          zlje: 5000,
          zljzb: 5,
          cddje: 2000,
          cddjzb: 2,
          moneyFlowSource: 'eastmoney',
          moneyFlowEstimated: false,
          capitalFlowSource: 'official_l2',
          capitalFlowConfidence: 'medium',
        }),
        updateQuote: vi.fn(),
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(new Map()),
        fetchFullData: vi.fn().mockResolvedValue(new Map()),
      },
    })

    const result = await service.fetchMergedQuotes(['000001'], { force: true })
    const quote = result.get('000001')

    expect(quote?.price).toBe(11)
    expect(quote?.moneyFlowSource).toBe('eastmoney')
    expect(quote?.moneyFlowEstimated).toBe(false)
    expect(quote?.capitalFlowSource).toBe('official_l2')
    expect(quote?.capitalFlowConfidence).toBe('medium')
    expect(quote?.zlje).toBe(5000)
    expect(quote?.cddje).toBe(2000)
  })

  it('refreshes existing EastMoney fund flow when new EastMoney quote has updated values', async () => {
    const fetchFullData = vi.fn().mockResolvedValue(
      new Map([
        [
          '000001',
          {
            ...httpQuote({
              source: 'eastmoney',
              zlje: -9700,
              zljzb: -4.5,
              cddje: -10800,
              cddjzb: -5.1,
              moneyFlowSource: 'eastmoney',
              moneyFlowEstimated: false,
            }),
            source: 'eastmoney',
          },
        ],
      ]),
    )
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => true,
      webSocketService: {
        getQuotesBatch: () =>
          new Map([
            [
              '000001',
              {
                code: '000001',
                lastPrice: 11,
                changePct: 3,
                volume: 2000,
                amount: 22000,
                tdxBuyVolume: 100,
                tdxSellVolume: 50,
              },
            ],
          ]),
      },
      dataLayer: {
        getQuote: () => null,
        getStock: () => ({
          code: '000001',
          turnoverRate: 0,
          zlje: 5000,
          zljzb: 5,
          cddje: 2000,
          cddjzb: 2,
          moneyFlowSource: 'eastmoney',
          moneyFlowEstimated: false,
          capitalFlowSource: 'official_l2',
          capitalFlowConfidence: 'medium',
        }),
        updateQuote: vi.fn(),
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(new Map()),
        fetchFullData,
      },
    })

    const result = await service.fetchMergedQuotes(['000001'], { force: true })
    const quote = result.get('000001')

    expect(fetchFullData).toHaveBeenCalledWith(['000001'], true)
    expect(quote?.moneyFlowSource).toBe('eastmoney')
    expect(quote?.moneyFlowEstimated).toBe(false)
    expect(quote?.zlje).toBe(-9700)
    expect(quote?.cddje).toBe(-10800)
  })

  it('does not refresh money-flow fields from realtime L1 active-volume data', async () => {
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => true,
      webSocketService: {
        getQuotesBatch: () =>
          new Map([
            [
              '000001',
              {
                code: '000001',
                lastPrice: 10,
                changePct: 1,
                volume: 2000,
                amount: 200_000,
                tdxBuyVolume: 80,
                tdxSellVolume: 30,
                tdxCurrentVolume: 10,
              },
            ],
          ]),
      },
      dataLayer: {
        getQuote: () => null,
        getStock: () => ({
          code: '000001',
          turnoverRate: 0,
          zlje: 100,
          zljzb: 1,
          cddje: 50,
          cddjzb: 0.5,
          moneyFlowSource: 'tdx_estimate',
          moneyFlowEstimated: true,
          capitalFlowSource: 'estimated_l1',
          capitalFlowConfidence: 'low',
        }),
        updateQuote: vi.fn(),
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(new Map()),
        fetchFullData: vi.fn().mockResolvedValue(new Map()),
      },
    })

    const result = await service.fetchMergedQuotes(['000001'], { force: true })
    const quote = result.get('000001')

    expect(quote?.moneyFlowSource).toBe('tdx_estimate')
    expect(quote?.capitalFlowSource).toBe('estimated_l1')
    expect(quote?.zlje).toBe(100)
    expect(quote?.cddje).toBe(50)
    expect(quote?.cddjzb).toBe(0.5)
  })

  it('uses the higher priority cached money flow source over the merged stock source', async () => {
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => true,
      webSocketService: {
        getQuotesBatch: () =>
          new Map([
            [
              '000001',
              {
                code: '000001',
                lastPrice: 11,
                changePct: 3,
                volume: 2000,
                amount: 22000,
                tdxBuyVolume: 100,
                tdxSellVolume: 50,
                tdxCurrentVolume: 20,
              },
            ],
          ]),
      },
      dataLayer: {
        getQuote: () =>
          httpQuote({
            zlje: 5000,
            zljzb: 5,
            cddje: 2000,
            cddjzb: 2,
            moneyFlowSource: 'eastmoney',
            moneyFlowEstimated: false,
            capitalFlowSource: 'official_l2',
            capitalFlowConfidence: 'medium',
          }),
        getStock: () => ({
          code: '000001',
          turnoverRate: 0,
          zlje: 100,
          zljzb: 1,
          cddje: 50,
          cddjzb: 0.5,
          moneyFlowSource: 'tdx_estimate',
          moneyFlowEstimated: true,
          capitalFlowSource: 'estimated_l1',
          capitalFlowConfidence: 'low',
        }),
        updateQuote: vi.fn(),
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(new Map()),
        fetchFullData: vi.fn().mockResolvedValue(new Map()),
      },
    })

    const result = await service.fetchMergedQuotes(['000001'], { force: true })
    const quote = result.get('000001')

    expect(quote?.moneyFlowSource).toBe('eastmoney')
    expect(quote?.moneyFlowEstimated).toBe(false)
    expect(quote?.capitalFlowSource).toBe('official_l2')
    expect(quote?.zlje).toBe(5000)
    expect(quote?.cddje).toBe(2000)
  })

  it('keeps QMT L2 fund flow as the realtime source instead of recomputing TDX estimates', async () => {
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => true,
      webSocketService: {
        getQuotesBatch: () =>
          new Map([
            [
              '000001',
              {
                code: '000001',
                lastPrice: 11,
                changePct: 3,
                volume: 2000,
                amount: 22000,
                tdxBuyVolume: 1000,
                tdxSellVolume: 1,
                zlje: 8800,
                zljzb: 8,
                cddje: 6600,
                cddjzb: 6,
                moneyFlowSource: 'qmt_l2',
                moneyFlowEstimated: false,
                capitalFlowSource: 'broker_l2',
                capitalFlowConfidence: 'high',
              },
            ],
          ]),
      },
      dataLayer: {
        getQuote: () => null,
        getStock: () => ({ code: '000001', turnoverRate: 0 }),
        updateQuote: vi.fn(),
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(new Map()),
        fetchFullData: vi.fn().mockResolvedValue(new Map()),
      },
    })

    const result = await service.fetchMergedQuotes(['000001'], { force: true })
    const quote = result.get('000001')

    expect(quote?.moneyFlowSource).toBe('qmt_l2')
    expect(quote?.moneyFlowEstimated).toBe(false)
    expect(quote?.capitalFlowSource).toBe('broker_l2')
    expect(quote?.capitalFlowConfidence).toBe('high')
    expect(quote?.zlje).toBe(8800)
    expect(quote?.cddje).toBe(6600)
    expect(quote?.sources).toEqual(['qmt_l2'])
  })

  it('returns cached single quote within five seconds when force is false', async () => {
    const cached = httpQuote({ timestamp: 8000 })
    const updateQuote = vi.fn()
    const service = new QuoteService({
      now: () => 10000,
      dataLayer: {
        getQuote: () => cached,
        getStock: () => null,
        updateQuote,
      },
      feed: {
        fetchBasicData: vi.fn(),
        fetchFullData: vi.fn(),
      },
      webSocketService: { getQuotesBatch: () => new Map() },
      isRealtimePrimaryHealthy: () => false,
    })

    await expect(service.getQuote('000001')).resolves.toBe(cached)
    expect(updateQuote).not.toHaveBeenCalled()
  })

  it('batch fetches quotes and writes full quotes back to DataLayer', async () => {
    const updateQuote = vi.fn()
    const service = new QuoteService({
      now: () => 1000,
      batchDelay: 1,
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote,
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(
          new Map([
            [
              '000001',
              {
                ...httpQuote({ name: '样本股' }),
                source: 'tencent',
              },
            ],
          ]),
        ),
        fetchFullData: vi.fn().mockResolvedValue(new Map()),
      },
      webSocketService: { getQuotesBatch: () => new Map() },
      isRealtimePrimaryHealthy: () => false,
    })

    const result = await service.getQuoteBatch(['000001'], true)

    expect(result.get('000001')?.name).toBe('样本股')
    expect(updateQuote).toHaveBeenCalledWith('000001', expect.objectContaining({ name: '样本股' }))
  })

  it('resolves overlapping batch callers from one shared flush', async () => {
    const updateQuote = vi.fn()
    const fetchBasicData = vi.fn().mockResolvedValue(
      new Map([
        [
          '000001',
          {
            ...httpQuote({ name: '平安银行' }),
            source: 'tencent',
          },
        ],
        [
          '000002',
          {
            ...httpQuote({ name: '万科A', price: 12 }),
            source: 'tencent',
          },
        ],
      ]),
    )
    const service = new QuoteService({
      now: () => 1000,
      batchDelay: 1,
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote,
      },
      feed: {
        fetchBasicData,
        fetchFullData: vi.fn().mockResolvedValue(new Map()),
      },
      webSocketService: { getQuotesBatch: () => new Map() },
      isRealtimePrimaryHealthy: () => false,
    })

    const first = service.getQuoteBatch(['000001'])
    const second = service.getQuoteBatch(['000001', '000002'])
    const [firstResult, secondResult] = await Promise.all([first, second])

    expect(firstResult.get('000001')?.name).toBe('平安银行')
    expect(secondResult.get('000001')?.name).toBe('平安银行')
    expect(secondResult.get('000002')?.name).toBe('万科A')
    expect(fetchBasicData).toHaveBeenCalledTimes(1)
    expect(fetchBasicData).toHaveBeenCalledWith(['000001', '000002'])
  })

  it('reports HTTP progress only after both basic and full quote feeds advance', async () => {
    const progressEvents: Array<{ completedCodes: number; totalCodes: number }> = []
    let releaseFullData: (() => void) | null = null
    const service = new QuoteService({
      now: () => 1000,
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote: vi.fn(),
      },
      feed: {
        fetchBasicData: vi.fn(async (_codes, options) => {
          options?.onProgress?.({
            source: 'tencent',
            completedBatches: 1,
            totalBatches: 1,
            completedCodes: 2,
            totalCodes: 2,
          })
          return new Map()
        }),
        fetchFullData: vi.fn(async (_codes, _force, options) => {
          await new Promise<void>((resolve) => {
            releaseFullData = resolve
          })
          options?.onProgress?.({
            source: 'eastmoney',
            completedBatches: 1,
            totalBatches: 1,
            completedCodes: 2,
            totalCodes: 2,
          })
          return new Map()
        }),
      },
      webSocketService: { getQuotesBatch: () => new Map() },
      isRealtimePrimaryHealthy: () => false,
    })

    const request = service.fetchMergedQuotes(['000001', '000002'], {
      force: true,
      onProgress: (progress) => progressEvents.push(progress),
    })

    await vi.waitFor(() => {
      expect(releaseFullData).toEqual(expect.any(Function))
    })
    expect(progressEvents).toEqual([
      expect.objectContaining({
        completedCodes: 1,
        totalCodes: 2,
      }),
    ])

    releaseFullData?.()
    await request

    expect(progressEvents.at(-1)).toEqual(
      expect.objectContaining({
        completedCodes: 2,
        totalCodes: 2,
      }),
    )
  })

  it('completes HTTP progress when full quote feed settles without progress events', async () => {
    const progressEvents: Array<{ completedCodes: number; totalCodes: number }> = []
    const service = new QuoteService({
      now: () => 1000,
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote: vi.fn(),
      },
      feed: {
        fetchBasicData: vi.fn(async (_codes, options) => {
          options?.onProgress?.({
            source: 'tencent',
            completedBatches: 1,
            totalBatches: 1,
            completedCodes: 2,
            totalCodes: 2,
          })
          return new Map()
        }),
        fetchFullData: vi.fn(async () => new Map()),
      },
      webSocketService: { getQuotesBatch: () => new Map() },
      isRealtimePrimaryHealthy: () => false,
    })

    await service.fetchMergedQuotes(['000001', '000002'], {
      force: true,
      onProgress: (progress) => progressEvents.push(progress),
    })

    expect(progressEvents.at(-1)).toEqual(
      expect.objectContaining({
        completedCodes: 2,
        totalCodes: 2,
      }),
    )
  })
})
