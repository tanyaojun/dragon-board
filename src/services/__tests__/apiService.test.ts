import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiHttpError, ApiService } from '../apiService'

describe('ApiService', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('starts request timeout only when the queued fetch begins', async () => {
    vi.useFakeTimers()
    const api = new ApiService()

    const releaseBlockers: Array<() => void> = []
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.includes('blocker')) {
        return new Promise<Response>((resolve) => {
          releaseBlockers.push(() =>
            resolve(
              new Response(JSON.stringify({ ok: true }), {
                status: 200,
                headers: { 'content-type': 'application/json' },
              }),
            ),
          )
        })
      }

      if (init?.signal?.aborted) {
        return Promise.reject(new DOMException('signal is aborted without reason', 'AbortError'))
      }

      return Promise.resolve(
        new Response(JSON.stringify({ ok: true, queued: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)

    const blockers = [1, 2, 3].map((index) =>
      api.get(`/api/test/blocker-${index}`, {
        timeout: 1000,
        retries: 0,
        cache: false,
      }),
    )
    await vi.waitFor(() => expect(releaseBlockers).toHaveLength(3))

    const queued = api.get('/api/test/queued', {
      timeout: 1000,
      retries: 0,
      cache: false,
    })

    await vi.advanceTimersByTimeAsync(1500)
    releaseBlockers.forEach((release) => release())
    await Promise.all(blockers)

    await expect(queued).resolves.toMatchObject({ ok: true, queued: true })
  })

  it('requests ths segmented limit-up pools through the limitup proxy endpoint', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ ok: true, pools: {} }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.getThsLimitUpPools({ date: '20260515' }, { cache: false, retries: 0 })

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/limitup/ths/pools?date=20260515'),
      expect.any(Object),
    )
  })

  it('routes full-market theme heat through QuantBoard proxy', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ ok: true, data: { factors: [] } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.getThemeHeat({ force: true })

    const url = new URL(String(fetchMock.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/themes/heat')
    expect(url.searchParams.get('force')).toBe('true')
  })

  it('routes theme stock details with paging parameters', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ ok: true, data: { stocks: [] } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.getThemeHeatStocks('AI/算力', { offset: 20, limit: 40 })

    const url = new URL(String(fetchMock.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/themes/heat/AI%2F%E7%AE%97%E5%8A%9B/stocks')
    expect(url.searchParams.get('offset')).toBe('20')
    expect(url.searchParams.get('limit')).toBe('40')
  })

  it('routes ths money-flow quote requests to the batch endpoint', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          rc: 0,
          data: {
            diff: [{ f12: '603773', f62: 197969013.5 }],
          },
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.getQuotes(['603773'], { source: 'thsMoneyFlow', retries: 0 })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/quotes/ths-money-flow?codes=603773')
  })

  it('cancels a queued request before its fetch begins', async () => {
    const api = new ApiService()

    const releaseBlockers: Array<() => void> = []
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('blocker')) {
        return new Promise<Response>((resolve) => {
          releaseBlockers.push(() =>
            resolve(
              new Response(JSON.stringify({ ok: true }), {
                status: 200,
                headers: { 'content-type': 'application/json' },
              }),
            ),
          )
        })
      }

      return Promise.resolve(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)

    const blockers = [1, 2, 3].map((index) =>
      api.get(`/api/test/blocker-${index}`, {
        timeout: 1000,
        retries: 0,
        cache: false,
      }),
    )
    await vi.waitFor(() => expect(releaseBlockers).toHaveLength(3))

    const queued = api.get('/api/test/queued-cancel', {
      requestId: 'queued-cancel',
      retries: 0,
      cache: false,
    })
    api.cancelRequest('queued-cancel')

    releaseBlockers.forEach((release) => release())
    await Promise.all(blockers)

    await expect(queued).rejects.toMatchObject({ name: 'AbortError' })
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('queued-cancel'),
      expect.anything(),
    )
  })

  it('retries retryable HTTP errors and throws structured ApiHttpError', async () => {
    const api = new ApiService()
    vi.spyOn(api as any, 'delay').mockResolvedValue(undefined)
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ok: false,
            errorCode: 'quantboard_unavailable',
            message: 'QuantBoard backend unavailable',
            details: { retryAfterMs: 1000 },
          }),
          {
            status: 503,
            statusText: 'Service Unavailable',
            headers: { 'content-type': 'application/json' },
          },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ok: false,
            errorCode: 'quantboard_unavailable',
            message: 'QuantBoard backend unavailable',
            details: { retryAfterMs: 1000 },
          }),
          {
            status: 503,
            statusText: 'Service Unavailable',
            headers: { 'content-type': 'application/json' },
          },
        ),
      )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      api.ingestSnapshotBundle(
        {
          version: 'v4',
          tradingDate: '2026-04-21',
          items: [],
          frames: [],
          stockRows: [],
          sectorRows: [],
        },
        {
          retries: 1,
          retryDelay: 1,
          silent: true,
        },
      ),
    ).rejects.toMatchObject({
      name: 'ApiHttpError',
      status: 503,
      errorCode: 'quantboard_unavailable',
      details: { retryAfterMs: 1000 },
      retryable: true,
    } satisfies Partial<ApiHttpError>)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('does not retry non-retryable HTTP errors', async () => {
    const api = new ApiService()
    vi.spyOn(api as any, 'delay').mockResolvedValue(undefined)
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: false,
          errorCode: 'bad_request',
          message: 'invalid payload',
        }),
        {
          status: 400,
          statusText: 'Bad Request',
          headers: { 'content-type': 'application/json' },
        },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      api.ingestSnapshotBundle(
        {
          version: 'v4',
          tradingDate: '2026-04-21',
          items: [],
          frames: [],
          stockRows: [],
          sectorRows: [],
        },
        {
          retries: 2,
          retryDelay: 1,
          silent: true,
        },
      ),
    ).rejects.toMatchObject({
      name: 'ApiHttpError',
      status: 400,
      errorCode: 'bad_request',
      retryable: false,
    } satisfies Partial<ApiHttpError>)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('maps mongo snapshot frame query params to QuantBoard snake case API', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, frames: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.listMongoSnapshotFrames({
      datasetId: 'dragonboard_live',
      type: 'half_hour',
      tradingDate: '2026-04-24',
      beforeTradingDate: '2026-04-25',
      allowedCaptureModes: ['real_time', 'delayed'],
      excludeRestored: true,
      sort: 'asc',
      limit: 20,
    })

    const requestedUrl = String(fetchMock.mock.calls[0][0])
    expect(requestedUrl).toContain('http://localhost:3000/api/snapshots/frames?')
    expect(requestedUrl).toContain('dataset_id=dragonboard_live')
    expect(requestedUrl).toContain('snapshot_type=half_hour')
    expect(requestedUrl).toContain('trading_date=2026-04-24')
    expect(requestedUrl).toContain('before_trading_date=2026-04-25')
    expect(requestedUrl).toContain('allowed_capture_modes=real_time%2Cdelayed')
    expect(requestedUrl).toContain('exclude_restored=true')
    expect(requestedUrl).toContain('sort=asc')
    expect(requestedUrl).toContain('limit=20')
  })

  it('maps mongo snapshot frame projection params to QuantBoard API', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, frames: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.listMongoSnapshotFrames({
      datasetId: 'dragonboard_live',
      type: 'half_hour',
      projection: 'ranktrend',
    })

    const requestedUrl = String(fetchMock.mock.calls[0][0])
    expect(requestedUrl).toContain('projection=ranktrend')
  })

  it('maps ranktrend rank series params to QuantBoard API', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, frames: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.getRankTrendRankSeries({
      datasetId: 'dragonboard_live',
      type: 'half_hour',
      startDate: '2026-04-21',
      allowedCaptureModes: ['real_time', 'delayed'],
      excludeRestored: true,
      sort: 'desc',
      limit: 50,
      codes: ['600001', '600002'],
    })

    const requestedUrl = String(fetchMock.mock.calls[0][0])
    expect(requestedUrl).toContain('http://localhost:3000/api/ranktrend/rank-series?')
    expect(requestedUrl).toContain('dataset_id=dragonboard_live')
    expect(requestedUrl).toContain('snapshot_type=half_hour')
    expect(requestedUrl).toContain('start_date=2026-04-21')
    expect(requestedUrl).toContain('allowed_capture_modes=real_time%2Cdelayed')
    expect(requestedUrl).toContain('exclude_restored=true')
    expect(requestedUrl).toContain('sort=desc')
    expect(requestedUrl).toContain('limit=50')
    expect(requestedUrl).toContain('codes=600001%2C600002')
  })

  it('serializes windowBars for ranktrend rank series', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, frames: [], series: {} }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.getRankTrendRankSeries({
      datasetId: 'dragonboard_live',
      type: 'half_hour',
      windowBars: 50,
    })

    const requestedUrl = String(fetchMock.mock.calls[0][0])
    expect(requestedUrl).toContain('window_bars=50')
  })

  it('parses series field from ranktrend rank series response', async () => {
    const api = new ApiService()
    const seriesData = {
      '600001': {
        code: '600001',
        bars: [{ snapshotId: 's1', timestamp: 1, rank: 5, tradingDate: '2026-01-01', slotTime: '10:00' }],
        totalCount: 1,
        latestSnapshotId: 's1',
        latestTradingDate: '2026-01-01',
        latestSlotTime: '10:00',
      },
    }
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, frames: [], series: seriesData }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const response = await api.getRankTrendRankSeries()

    expect(response.series).toBeDefined()
    expect(response.series['600001'].bars).toHaveLength(1)
    expect(response.series['600001'].bars[0].rank).toBe(5)
    expect(response.series['600001'].totalCount).toBe(1)
  })

  it('keeps ranktrend rank series requests alive beyond 15 seconds before timing out', async () => {
    vi.useFakeTimers()
    const api = new ApiService()
    let aborted = false

    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          'abort',
          () => {
            aborted = true
            reject(new DOMException('signal is aborted without reason', 'AbortError'))
          },
          { once: true },
        )
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    const request = api
      .getRankTrendRankSeries({}, { retries: 0 })
      .then(
        () => ({ ok: true as const }),
        (error) => ({ ok: false as const, error }),
      )

    await vi.advanceTimersByTimeAsync(20_000)
    expect(aborted).toBe(false)

    await vi.advanceTimersByTimeAsync(60_000)
    const result = await request
    expect(result.ok).toBe(false)
    if (result.ok) {
      throw new Error('expected ranktrend request to abort after extended timeout')
    }
    expect(result.error).toMatchObject({ name: 'AbortError' })
    expect(aborted).toBe(true)
  })

  it('maps mongo snapshot record detail formal policy params to QuantBoard API', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, record: null }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.getMongoSnapshotRecord('half_hour:2026-04-24:10:00', {
      datasetId: 'dragonboard_live',
      allowedCaptureModes: ['real_time', 'delayed'],
      excludeRestored: true,
    })

    const requestedUrl = String(fetchMock.mock.calls[0][0])
    expect(requestedUrl).toContain(
      'http://localhost:3000/api/snapshots/records/half_hour%3A2026-04-24%3A10%3A00?',
    )
    expect(requestedUrl).toContain('dataset_id=dragonboard_live')
    expect(requestedUrl).toContain('allowed_capture_modes=real_time%2Cdelayed')
    expect(requestedUrl).toContain('exclude_restored=true')
  })

  it('routes mongo theme mapping reads to QuantBoard API', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, mapping: { themes: [] } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.getMongoThemeMapping()

    const requestedUrl = new URL(String(fetchMock.mock.calls[0][0]))
    expect(requestedUrl.origin).toBe('http://localhost:3000')
    expect(requestedUrl.pathname).toBe('/api/themes/mapping')
  })

  it('routes ThemeTrend research summary reads to QuantBoard API without throwing on unavailable summary', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ available: false, reason: 'backend unavailable' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await api.getThemeResearchSummary({
      datasetId: 'dragonboard_live',
      snapshotType: 'half_hour',
    })

    const requestedUrl = new URL(String(fetchMock.mock.calls[0][0]))
    expect(requestedUrl.origin).toBe('http://localhost:3000')
    expect(requestedUrl.pathname).toBe('/api/research/theme-summary')
    expect(requestedUrl.searchParams.get('dataset_id')).toBe('dragonboard_live')
    expect(requestedUrl.searchParams.get('snapshot_type')).toBe('half_hour')
    expect(result.available).toBe(false)
  })

  it('routes stock name reads to QuantBoard API', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, source: 'mongodb', stocks: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.listStockNames()

    const requestedUrl = new URL(String(fetchMock.mock.calls[0][0]))
    expect(requestedUrl.origin).toBe('http://localhost:3000')
    expect(requestedUrl.pathname).toBe('/api/stocks/names')
  })

  it('routes journal reads to QuantBoard API', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ entries: [], total: 0 }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.get('/api/journal/entries?status=candidate')

    const requestedUrl = new URL(String(fetchMock.mock.calls[0][0]))
    expect(requestedUrl.origin).toBe('http://localhost:3000')
    expect(requestedUrl.pathname).toBe('/api/journal/entries')
    expect(requestedUrl.searchParams.get('status')).toBe('candidate')
  })
})
