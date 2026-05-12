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

  it('maps sqlite snapshot frame query params to QuantBoard snake case API', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, frames: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.listSqliteSnapshotFrames({
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
    expect(requestedUrl).toContain('http://localhost:8000/api/snapshots/frames?')
    expect(requestedUrl).toContain('dataset_id=dragonboard_live')
    expect(requestedUrl).toContain('snapshot_type=half_hour')
    expect(requestedUrl).toContain('trading_date=2026-04-24')
    expect(requestedUrl).toContain('before_trading_date=2026-04-25')
    expect(requestedUrl).toContain('allowed_capture_modes=real_time%2Cdelayed')
    expect(requestedUrl).toContain('exclude_restored=true')
    expect(requestedUrl).toContain('sort=asc')
    expect(requestedUrl).toContain('limit=20')
  })

  it('maps sqlite snapshot frame projection params to QuantBoard API', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, frames: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.listSqliteSnapshotFrames({
      datasetId: 'dragonboard_live',
      type: 'half_hour',
      projection: 'ranktrend',
    })

    const requestedUrl = String(fetchMock.mock.calls[0][0])
    expect(requestedUrl).toContain('projection=ranktrend')
  })

  it('maps sqlite snapshot record detail formal policy params to QuantBoard API', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, record: null }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.getSqliteSnapshotRecord('half_hour:2026-04-24:10:00', {
      datasetId: 'dragonboard_live',
      allowedCaptureModes: ['real_time', 'delayed'],
      excludeRestored: true,
    })

    const requestedUrl = String(fetchMock.mock.calls[0][0])
    expect(requestedUrl).toContain(
      'http://localhost:8000/api/snapshots/records/half_hour%3A2026-04-24%3A10%3A00?',
    )
    expect(requestedUrl).toContain('dataset_id=dragonboard_live')
    expect(requestedUrl).toContain('allowed_capture_modes=real_time%2Cdelayed')
    expect(requestedUrl).toContain('exclude_restored=true')
  })

  it('routes sqlite theme mapping reads to QuantBoard API', async () => {
    const api = new ApiService()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, mapping: { themes: [] } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.getSqliteThemeMapping()

    const requestedUrl = new URL(String(fetchMock.mock.calls[0][0]))
    expect(requestedUrl.origin).toBe('http://localhost:8000')
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
    expect(requestedUrl.origin).toBe('http://localhost:8000')
    expect(requestedUrl.pathname).toBe('/api/research/theme-summary')
    expect(requestedUrl.searchParams.get('dataset_id')).toBe('dragonboard_live')
    expect(requestedUrl.searchParams.get('snapshot_type')).toBe('half_hour')
    expect(result.available).toBe(false)
  })
})
