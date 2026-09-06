import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchHotlistSentimentSeries } from '../hotlistSentimentApi'

const docStub = {
  datasetId: 'dragonboard_live',
  snapshotType: 'half_hour',
  tradingDate: '2026-09-06',
  stage: '高潮' as const,
  riskLevel: '低' as const,
  confidence: 78,
  summary: '热榜情绪处于高潮阶段',
  metrics: { topN: 120, layers: {} as any, comparison: {} as any, limitEvidence: {} as any },
  turnover: {
    previousPoolSize: 0,
    currentPoolSize: 0,
    retainedFromYesterday: 0,
    newEntries: [],
    eliminated: [],
    newEntryDetails: [],
    eliminatedDetails: [],
  },
  signals: [],
  warnings: [],
}

afterEach(() => vi.unstubAllGlobals())

describe('fetchHotlistSentimentSeries', () => {
  it('正常响应返回类型化 items', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ok: true, items: [docStub] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    const result = await fetchHotlistSentimentSeries()
    expect(result.degraded).toBe(false)
    expect(result.items).toHaveLength(1)
    expect(result.items[0].tradingDate).toBe('2026-09-06')
    expect(result.items[0].stage).toBe('高潮')
  })

  it('degraded 响应透传错误态，不伪造数据', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ok: false,
            degraded: true,
            reason: 'no_snapshot_trading_date',
            items: [],
          }),
          { status: 200 },
        ),
      ),
    )
    const result = await fetchHotlistSentimentSeries()
    expect(result.degraded).toBe(true)
    expect(result.items).toHaveLength(0)
    expect(result.reason).toBe('no_snapshot_trading_date')
  })

  it('HTTP 错误返回错误态', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('err', { status: 502 })))
    const result = await fetchHotlistSentimentSeries()
    expect(result.degraded).toBe(true)
    expect(result.reason).toBe('HTTP 502')
  })

  it('missing 日被过滤', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ok: true,
            items: [
              docStub,
              { tradingDate: '2026-09-05', missing: true, reason: 'empty_stock_rows' },
            ],
          }),
          { status: 200 },
        ),
      ),
    )
    const result = await fetchHotlistSentimentSeries()
    expect(result.items).toHaveLength(1)
    expect(result.items[0].tradingDate).toBe('2026-09-06')
  })

  it('请求参数包含 dataset_id 与 days', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ ok: true, items: [] }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await fetchHotlistSentimentSeries(5, 'my_dataset')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/hotlist-sentiment/series?dataset_id=my_dataset&days=5',
    )
  })
})
