import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchPhaseHistory, fetchPhaseMonitorBoard } from '../phaseApi'

afterEach(() => vi.unstubAllGlobals())

describe('fetchPhaseHistory', () => {
  it('正常响应：days 与 threshold 透传', async () => {
    vi.stubGlobal('fetch', vi.fn(async () =>
      new Response(
        JSON.stringify({
          datasetId: 'dragonboard_live',
          snapshotType: 'half_hour',
          threshold: 50.0,
          count: 2,
          days: [
            { tradingDate: '2026-09-26', eodScore: 65.6, phase: 'offense' },
            { tradingDate: '2026-09-27', eodScore: 48.3, phase: 'defense' },
          ],
        }),
        { status: 200 },
      ),
    ))
    const result = await fetchPhaseHistory()
    expect(result).toEqual({
      degraded: false,
      threshold: 50.0,
      days: [
        { tradingDate: '2026-09-26', eodScore: 65.6, phase: 'offense' },
        { tradingDate: '2026-09-27', eodScore: 48.3, phase: 'defense' },
      ],
    })
  })

  it('HTTP 非 2xx：degraded + reason，不抛错', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('boom', { status: 503 })))
    const result = await fetchPhaseHistory()
    expect(result).toEqual({ degraded: true, days: [], threshold: null, reason: 'HTTP 503' })
  })

  it('网络异常：degraded + reason', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('connection refused')
    }))
    const result = await fetchPhaseHistory()
    expect(result).toEqual({ degraded: true, days: [], threshold: null, reason: 'connection refused' })
  })
})

describe('fetchPhaseMonitorBoard', () => {
  it('正常响应：board 透传', async () => {
    const board = {
      northstar: { _id: 'northstar:gen7-sentiment2b', kind: 'northstar', key: 'gen7-sentiment2b', report: {}, updatedAt: 't1' },
      months: [],
      count: 0,
    }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(board), { status: 200 })))
    const result = await fetchPhaseMonitorBoard()
    expect(result).toEqual(board)
  })

  it('HTTP 非 2xx：degraded + reason', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('boom', { status: 500 })))
    const result = await fetchPhaseMonitorBoard()
    expect(result).toEqual({ degraded: true, reason: 'HTTP 500' })
  })
})
