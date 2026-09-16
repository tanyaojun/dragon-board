import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchHotlistSentimentSeries, fetchHotlistSentimentSlots } from '../hotlistSentimentApi'

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

  it('missing 日被过滤并收集进 missingDays（reason 原样）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ok: true,
            items: [
              docStub,
              { tradingDate: '2026-09-05', missing: true, reason: 'empty_stock_rows' },
              { tradingDate: '2026-09-04', missing: true, reason: 'no_snapshot' },
            ],
          }),
          { status: 200 },
        ),
      ),
    )
    const result = await fetchHotlistSentimentSeries()
    expect(result.items).toHaveLength(1)
    expect(result.items[0].tradingDate).toBe('2026-09-06')
    expect(result.missingDays).toHaveLength(2)
    expect(result.missingDays).toEqual([
      { tradingDate: '2026-09-05', reason: 'empty_stock_rows' },
      { tradingDate: '2026-09-04', reason: 'no_snapshot' },
    ])
  })

  it('missing 条目缺 tradingDate 时 missingDays 用空字符串占位', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ok: true,
            items: [docStub, { missing: true, reason: 'no_snapshot' }],
          }),
          { status: 200 },
        ),
      ),
    )
    const result = await fetchHotlistSentimentSeries()
    expect(result.items).toHaveLength(1)
    expect(result.missingDays).toEqual([{ tradingDate: '', reason: 'no_snapshot' }])
  })

  it('degraded 响应 missingDays 为空数组', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ ok: false, degraded: true, reason: 'no_snapshot', items: [] }),
          { status: 200 },
        ),
      ),
    )
    const result = await fetchHotlistSentimentSeries()
    expect(result.degraded).toBe(true)
    expect(result.missingDays).toEqual([])
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

describe('fetchHotlistSentimentSlots', () => {
  it('正常响应返回当日槽位升序 items 与 tradingDate', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ok: true,
            datasetId: 'dragonboard_live',
            tradingDate: '2026-09-15',
            items: [
              { ...docStub, slotTime: '09:30' },
              { ...docStub, slotTime: '10:00' },
            ],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )
    const result = await fetchHotlistSentimentSlots()
    expect(result.degraded).toBe(false)
    expect(result.tradingDate).toBe('2026-09-15')
    expect(result.items.map((item) => item.slotTime)).toEqual(['09:30', '10:00'])
  })

  it('degraded 响应透传错误态，不伪造数据', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ok: false, degraded: true, reason: 'no_snapshot_trading_date' }), {
          status: 200,
        }),
      ),
    )
    const result = await fetchHotlistSentimentSlots()
    expect(result.degraded).toBe(true)
    expect(result.items).toHaveLength(0)
    expect(result.reason).toBe('no_snapshot_trading_date')
  })

  it('HTTP 错误返回错误态', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('err', { status: 502 })))
    const result = await fetchHotlistSentimentSlots()
    expect(result.degraded).toBe(true)
    expect(result.reason).toBe('HTTP 502')
  })
})
