import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchHotlistJevRange, fetchHotlistJevSeries } from '../hotlistJevApi'
import type { HotlistJevDoc } from '@/types/hotlistJev'

const slotDoc = (overrides: Partial<HotlistJevDoc>): HotlistJevDoc => ({
  kind: 'slot',
  datasetId: 'dragonboard_live',
  snapshotType: 'half_hour',
  tradingDate: '2026-09-29',
  slotTime: '09:30',
  status: 'ok',
  answers: {
    sequence_stage: { type: 'choice', choice: 'start', probabilities: { start: 0.6 } },
  },
  scores: { temperature: 24, crowding: 15 },
  ...overrides,
})

afterEach(() => vi.unstubAllGlobals())

describe('fetchHotlistJevSeries', () => {
  it('正常响应返回类型化 slots + eod', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ ok: true, date: '2026-09-29', slots: [slotDoc({})], eod: null }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )
    const result = await fetchHotlistJevSeries()
    expect(result.degraded).toBe(false)
    expect(result.date).toBe('2026-09-29')
    expect(result.slots).toHaveLength(1)
  })

  it('degraded 响应透传错误态，不伪造数据', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ok: false, degraded: true, reason: 'mongodb_unavailable: x' }), {
          status: 200,
        }),
      ),
    )
    const result = await fetchHotlistJevSeries()
    expect(result.degraded).toBe(true)
    expect(result.slots).toHaveLength(0)
    expect(result.reason).toBe('mongodb_unavailable: x')
  })
})

describe('fetchHotlistJevRange', () => {
  it('正常响应拆分文档日与缺失日（missing 收集进 missingDays，不吞掉）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ok: true,
            datasetId: 'dragonboard_live',
            days: [
              { tradingDate: '2026-09-26', missing: true, reason: 'no_jev_docs' },
              {
                tradingDate: '2026-09-29',
                slots: [slotDoc({ tradingDate: '2026-09-29' })],
                eod: {
                  kind: 'eod',
                  tradingDate: '2026-09-29',
                  status: 'ok',
                  answers: { day_stage: { type: 'choice', choice: 'climax' } },
                  scores: { day_temperature: 73, day_crowding: 32 },
                },
              },
            ],
            degradedCount: 0,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )
    const result = await fetchHotlistJevRange(5)
    expect(result.degraded).toBe(false)
    expect(result.days).toHaveLength(1)
    expect(result.days[0].tradingDate).toBe('2026-09-29')
    expect(result.days[0].slots[0].scores?.temperature).toBe(24)
    expect(result.missingDays).toEqual([{ tradingDate: '2026-09-26', reason: 'no_jev_docs' }])
  })

  it('degraded 响应透传错误态', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ ok: false, degraded: true, reason: 'no_snapshot_trading_date' }),
          { status: 200 },
        ),
      ),
    )
    const result = await fetchHotlistJevRange()
    expect(result.degraded).toBe(true)
    expect(result.days).toHaveLength(0)
    expect(result.reason).toBe('no_snapshot_trading_date')
  })

  it('HTTP 错误返回错误态', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('err', { status: 502 })))
    const result = await fetchHotlistJevRange()
    expect(result.degraded).toBe(true)
    expect(result.reason).toBe('HTTP 502')
  })

  it('网络异常返回错误态，不抛出', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    const result = await fetchHotlistJevRange()
    expect(result.degraded).toBe(true)
    expect(result.reason).toBe('network down')
  })
})
