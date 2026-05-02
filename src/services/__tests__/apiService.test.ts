import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiHttpError, ApiService } from '../apiService'

describe('ApiService', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
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
})
