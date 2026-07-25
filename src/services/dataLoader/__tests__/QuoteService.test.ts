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
  it('returns basic quotes before lazy money-flow enrichment when force is false', async () => {
    const service = new QuoteService({ now: () => 1000 })

    const codes = ['603773']
    const result = await service.fetchMergedQuotes(codes)
    const quote = result.get('603773')

    expect(quote?.price).toBeDefined()
    expect(quote?.sources).toBeDefined()
  })

  it('does not publish legacy HTTP money-flow enrichment as authoritative funds', async () => {
    const applyRealtimeQuoteBatch = vi.fn()
    const fetchFullData = vi.fn().mockResolvedValue(
      new Map([
        [
          '603773',
          {
            ...httpQuote({ zlje: 5_450_857_714.71, zljzb: 21.63, moneyFlowSource: 'ths_l2', moneyFlowEstimated: false }),
          },
        ],
      ]),
    )

    const service = new QuoteService({
      now: () => 1000,
      dataLayer: { getQuote: () => null, getStock: () => null, applyRealtimeQuoteBatch, updateQuote: () => undefined } as any,
      feed: { fetchBasicData: () => new Map(), fetchFullData } as any,
    })

    await service.fetchMergedQuotes(['603773'])
    await vi.waitFor(() => { expect(applyRealtimeQuoteBatch).toHaveBeenCalled() })

    const patch = applyRealtimeQuoteBatch.mock.calls[0]?.[0]?.[0]
    expect(patch?.zlje).toBeUndefined()
    expect(patch?.moneyFlowSource).toBeUndefined()
  })

  it('does not label basic-source fund flow as having money flow data', async () => {
    const dataLayer = {
      getQuote: () => null,
      getStock: () => null,
      applyRealtimeQuoteBatch: vi.fn(),
      updateQuote: () => undefined,
    } as any

    const service = new QuoteService({
      now: () => 1000,
      dataLayer,
      feed: {
        fetchBasicData: () => new Map([['603773', httpQuote({ source: 'tencent', zlje: 0 })] as any]),
        fetchFullData: () => new Map(),
      } as any,
    })

    const result = await service.fetchMergedQuotes(['603773'])
    const quote = result.get('603773')
    expect(quote?.zlje).toBeUndefined()
  })

  it('uses HTTP quote supplement fields when realtime TDX quote has no valuation fields', async () => {
    const service = new QuoteService({
      now: () => 1000,
      webSocketService: {
        getQuotesBatch: () =>
          new Map([
            [
              '603773',
              {
                code: '603773',
                lastPrice: 10.1,
                changePct: 0.5,
                volume: 1200,
                amount: 11000,
                turnoverRate: 0,
                name: '沃格光电',
              } as any,
            ],
          ]),
      },
      isRealtimePrimaryHealthy: () => true,
      feed: {
        fetchBasicData: () => new Map([['603773', httpQuote({ turnoverRate: 2.3, pe: 12, pb: 1.8 })] as any]),
        fetchFullData: () => new Map(),
      } as any,
    })

    const result = await service.fetchMergedQuotes(['603773'])
    const quote = result.get('603773')
    expect(quote?.turnoverRate).toBe(2.3)
    expect(quote?.pe).toBe(12)
    expect(quote?.pb).toBe(1.8)
    expect(quote?.price).toBe(10.1)
  })

  it('returns cached single quote within five seconds when force is false', async () => {
    const now = vi.fn().mockReturnValueOnce(0).mockReturnValueOnce(4900)
    const service = new QuoteService({
      now,
      dataLayer: {
        getQuote: (code: string) => (code === '603773' ? { ...httpQuote(), timestamp: 0 } : undefined),
        getStock: () => null,
        updateQuote: () => undefined,
      } as any,
    })

    const result = await service.getQuote('603773')
    expect(result?.timestamp).toBe(0)
    expect(now).toHaveBeenCalled()
  })

  it('batch fetches quotes and writes full quotes back to DataLayer', async () => {
    const updateQuote = vi.fn()
    const fetchFullData = vi.fn().mockResolvedValue(new Map([['603773', httpQuote({ zlje: 500, moneyFlowSource: 'ths_l2' })] as any]))

    const service = new QuoteService({
      now: () => 1000,
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote,
        applyRealtimeQuoteBatch: undefined,
      } as any,
      feed: {
        fetchBasicData: () =>
          new Map([['603773', httpQuote({ source: 'tencent' })] as any]),
        fetchFullData,
      } as any,
    })

    await service.getQuotes(['603773'], true)
    expect(updateQuote).toHaveBeenCalled()
  })

  it('resolves overlapping batch callers from one shared flush', async () => {
    const fetchFullData = vi.fn().mockResolvedValue(new Map())
    const updateQuote = vi.fn()

    const service = new QuoteService({
      batchDelay: 10,
      now: () => 1000,
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote,
        applyRealtimeQuoteBatch: undefined,
      } as any,
      feed: { fetchBasicData: () => new Map(), fetchFullData } as any,
    })

    const [a, b] = await Promise.all([
      service.getQuoteBatch(['000001']),
      service.getQuoteBatch(['000002']),
    ])

    expect(a).toBeInstanceOf(Map)
    expect(b).toBeInstanceOf(Map)
  })

  it('reports HTTP progress only after both basic and full quote feeds advance', async () => {
    const onProgress = vi.fn()
    const now = vi.fn().mockReturnValue(1000)

    const service = new QuoteService({
      batchDelay: 2,
      now,
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote: () => undefined,
      } as any,
      feed: {
        fetchBasicData: () => new Map([['000001', httpQuote()]] as any),
        fetchFullData: () => new Map(),
      } as any,
    })

    await service.fetchMergedQuotes(['000001'], { force: true, onProgress })
    expect(onProgress).toHaveBeenCalled()
  })

  it('completes HTTP progress when full quote feed settles without progress events', async () => {
    const onProgress = vi.fn()
    const service = new QuoteService({
      batchDelay: 2,
      now: () => 1000,
      dataLayer: {
        getQuote: () => null,
        getStock: () => null,
        updateQuote: () => undefined,
      } as any,
      feed: {
        fetchBasicData: () => new Map([['000001', httpQuote()]] as any),
        fetchFullData: () => new Map(),
      } as any,
    })

    await service.fetchMergedQuotes(['000001'], { force: true, onProgress })
    expect(onProgress).toHaveBeenCalled()
  })

})
