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

  it('merges Sina main money flow fallback with Tencent turnover and estimates main ratio', async () => {
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
              '600522',
              {
                ...httpQuote({
                  source: 'tencent',
                  price: 49.53,
                  turnover: 25_205_130_127,
                }),
                source: 'tencent',
              },
            ],
          ]),
        ),
        fetchFullData: vi.fn().mockResolvedValue(
          new Map([
            [
              '600522',
              {
                ...httpQuote({
                  source: 'sina',
                  price: 0,
                  turnover: 0,
                  zlje: 5_450_857_714.71,
                  zljzb: 0,
                  moneyFlowSource: 'sina',
                  moneyFlowEstimated: true,
                  capitalFlowSource: 'sina_money_flow',
                  capitalFlowConfidence: 'low',
                }),
                source: 'sina',
              },
            ],
          ]),
        ),
      },
    })

    const result = await service.fetchMergedQuotes(['600522'], { force: true })
    const quote = result.get('600522')

    expect(quote).toMatchObject({
      price: 49.53,
      turnover: 25_205_130_127,
      zlje: 5_450_857_714.71,
      zljzb: 21.63,
      moneyFlowSource: 'sina',
      moneyFlowEstimated: true,
      capitalFlowSource: 'sina_money_flow',
      capitalFlowConfidence: 'low',
    })
  })

  it('returns basic quotes before lazy money-flow enrichment when force is false', async () => {
    let releaseFullData: (() => void) | null = null
    const updateQuote = vi.fn()
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => false,
      webSocketService: { getQuotesBatch: () => new Map() },
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote,
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(
          new Map([
            [
              '600522',
              {
                ...httpQuote({
                  source: 'tencent',
                  price: 49.53,
                  turnover: 25_205_130_127,
                }),
                source: 'tencent',
              },
            ],
          ]),
        ),
        fetchFullData: vi.fn(
          () =>
            new Promise((resolve) => {
              releaseFullData = () =>
                resolve(
                  new Map([
                    [
                      '600522',
                      {
                        ...httpQuote({
                          source: 'sina',
                          price: 0,
                          turnover: 0,
                          zlje: 5_450_857_714.71,
                          zljzb: 0,
                          moneyFlowSource: 'sina',
                          moneyFlowEstimated: true,
                          capitalFlowSource: 'sina_money_flow',
                          capitalFlowConfidence: 'low',
                        }),
                        source: 'sina',
                      },
                    ],
                  ]),
                )
            }),
        ),
      },
    })

    const pendingMarker = Symbol('pending')
    const request = service.fetchMergedQuotes(['600522'], { force: false })
    const immediate = await Promise.race([
      request,
      new Promise((resolve) => setTimeout(() => resolve(pendingMarker), 20)),
    ])

    expect(immediate).not.toBe(pendingMarker)
    expect((immediate as Map<string, MergedQuoteData>).get('600522')).toMatchObject({
      price: 49.53,
      zlje: 0,
    })

    releaseFullData?.()
    await vi.waitFor(() => {
      expect(updateQuote).toHaveBeenCalledWith(
        '600522',
        expect.objectContaining({
          zlje: 5_450_857_714.71,
          zljzb: 21.63,
          moneyFlowSource: 'sina',
        }),
      )
    })
  })

  it('publishes lazy money-flow enrichment through realtime batch updates when available', async () => {
    let releaseFullData: (() => void) | null = null
    const updateQuote = vi.fn()
    const applyRealtimeQuoteBatch = vi.fn()
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => false,
      webSocketService: { getQuotesBatch: () => new Map() },
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote,
        applyRealtimeQuoteBatch,
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(
          new Map([
            [
              '603773',
              {
                ...httpQuote({
                  source: 'tencent',
                  price: 31.04,
                  turnover: 5_155_443_060,
                }),
                source: 'tencent',
              },
            ],
          ]),
        ),
        fetchFullData: vi.fn(
          () =>
            new Promise((resolve) => {
              releaseFullData = () =>
                resolve(
                  new Map([
                    [
                      '603773',
                      {
                        ...httpQuote({
                          source: 'sina',
                          price: 0,
                          turnover: 0,
                          zlje: 197_969_013.5,
                          zljzb: 0,
                          moneyFlowSource: 'sina',
                          moneyFlowEstimated: true,
                          capitalFlowSource: 'sina_money_flow',
                          capitalFlowConfidence: 'low',
                        }),
                        source: 'sina',
                      },
                    ],
                  ]),
                )
            }),
        ),
      },
    })

    const result = await service.fetchMergedQuotes(['603773'], { force: false })
    expect(result.get('603773')).toMatchObject({
      price: 31.04,
      zlje: 0,
    })

    releaseFullData?.()
    await vi.waitFor(() => {
      expect(applyRealtimeQuoteBatch).toHaveBeenCalledWith([
        expect.objectContaining({
          code: '603773',
          zlje: 197_969_013.5,
          zljzb: 3.84,
          moneyFlowSource: 'sina',
        }),
      ])
    })
    expect(updateQuote).not.toHaveBeenCalled()
  })

  it('publishes each lazy money-flow batch without waiting for later batches', async () => {
    const codes = Array.from({ length: 21 }, (_, index) => String(600522 + index))
    let releaseSecondBatch: (() => void) | null = null
    const applyRealtimeQuoteBatch = vi.fn()
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => false,
      webSocketService: { getQuotesBatch: () => new Map() },
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote: vi.fn(),
        applyRealtimeQuoteBatch,
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(
          new Map(
            codes.map((code) => [
              code,
              {
                ...httpQuote({
                  source: 'tencent',
                  turnover: 10_000,
                }),
                source: 'tencent',
              },
            ]),
          ),
        ),
        fetchFullData: vi.fn((requestedCodes: string[]) => {
          if (requestedCodes.length === 20) {
            return Promise.resolve(
              new Map([
                [
                  requestedCodes[0],
                  {
                    ...httpQuote({
                      source: 'sina',
                      price: 0,
                      turnover: 0,
                      zlje: 1_000,
                      zljzb: 0,
                      moneyFlowSource: 'sina',
                      moneyFlowEstimated: true,
                      capitalFlowSource: 'sina_money_flow',
                      capitalFlowConfidence: 'low',
                    }),
                    source: 'sina',
                  },
                ],
              ]),
            )
          }

          return new Promise((resolve) => {
            releaseSecondBatch = () => resolve(new Map())
          })
        }),
      },
    })

    await service.fetchMergedQuotes(codes, { force: false })

    await vi.waitFor(
      () => {
        expect(applyRealtimeQuoteBatch).toHaveBeenCalledWith([
          expect.objectContaining({
            code: '600522',
            zlje: 1_000,
            zljzb: 10,
            moneyFlowSource: 'sina',
          }),
        ])
      },
      { timeout: 100 },
    )

    releaseSecondBatch?.()
  })

  it('uses Sina money-flow directly for lazy background enrichment when available', async () => {
    const applyRealtimeQuoteBatch = vi.fn()
    const fetchFullData = vi.fn()
    const fetchFromSinaMoneyFlow = vi.fn().mockResolvedValue(
      new Map([
        [
          '603773',
          {
            ...httpQuote({
              source: 'sina',
              price: 0,
              turnover: 0,
              zlje: 197_969_013.5,
              zljzb: 0,
              moneyFlowSource: 'sina',
              moneyFlowEstimated: true,
              capitalFlowSource: 'sina_money_flow',
              capitalFlowConfidence: 'low',
            }),
            source: 'sina',
          },
        ],
      ]),
    )
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => false,
      webSocketService: { getQuotesBatch: () => new Map() },
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote: vi.fn(),
        applyRealtimeQuoteBatch,
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(
          new Map([
            [
              '603773',
              {
                ...httpQuote({
                  source: 'tencent',
                  price: 136.5,
                  turnover: 5_178_221_056,
                }),
                source: 'tencent',
              },
            ],
          ]),
        ),
        fetchFullData,
        fetchFromSinaMoneyFlow,
      },
    })

    await service.fetchMergedQuotes(['603773'], { force: false })

    await vi.waitFor(() => {
      expect(applyRealtimeQuoteBatch).toHaveBeenCalledWith([
        expect.objectContaining({
          code: '603773',
          zlje: 197_969_013.5,
          zljzb: 3.82,
          moneyFlowSource: 'sina',
        }),
      ])
    })
    expect(fetchFromSinaMoneyFlow).toHaveBeenCalledWith(['603773'], false)
    expect(fetchFullData).not.toHaveBeenCalled()
  })

  it('starts later lazy money-flow batches without waiting for earlier batches to finish', async () => {
    const codes = Array.from({ length: 41 }, (_, index) => String(600522 + index))
    const applyRealtimeQuoteBatch = vi.fn()
    const fetchFromSinaMoneyFlow = vi.fn((requestedCodes: string[]) => {
      if (requestedCodes.includes('600522')) {
        return new Promise<Map<string, MergedQuoteData>>(() => undefined)
      }

      return Promise.resolve(
        new Map([
          [
            requestedCodes[0],
            {
              ...httpQuote({
                source: 'sina',
                price: 0,
                turnover: 0,
                zlje: 2_000,
                zljzb: 0,
                moneyFlowSource: 'sina',
                moneyFlowEstimated: true,
                capitalFlowSource: 'sina_money_flow',
                capitalFlowConfidence: 'low',
              }),
              source: 'sina',
            },
          ],
        ]),
      )
    })
    const service = new QuoteService({
      now: () => 1000,
      isRealtimePrimaryHealthy: () => false,
      webSocketService: { getQuotesBatch: () => new Map() },
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote: vi.fn(),
        applyRealtimeQuoteBatch,
      },
      feed: {
        fetchBasicData: vi.fn().mockResolvedValue(
          new Map(
            codes.map((code) => [
              code,
              {
                ...httpQuote({
                  source: 'tencent',
                  turnover: 10_000,
                }),
                source: 'tencent',
              },
            ]),
          ),
        ),
        fetchFullData: vi.fn(),
        fetchFromSinaMoneyFlow,
      },
    })

    await service.fetchMergedQuotes(codes, { force: false })

    await vi.waitFor(
      () => {
        expect(fetchFromSinaMoneyFlow).toHaveBeenCalledWith(codes.slice(20, 40), false)
        expect(applyRealtimeQuoteBatch).toHaveBeenCalledWith([
          expect.objectContaining({
            code: codes[20],
            zlje: 2_000,
            zljzb: 20,
            moneyFlowSource: 'sina',
          }),
        ])
      },
      { timeout: 100 },
    )
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
