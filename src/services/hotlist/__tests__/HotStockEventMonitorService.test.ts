import { afterEach, describe, expect, it, vi } from 'vitest'

import { HotStockEventMonitorService } from '../HotStockEventMonitorService'
import { refreshScheduler, refreshTaskRegistry } from '../../refresh/RefreshTaskRuntime'
import type { HotStockAbnormalEvent } from '../hotStockEventTypes'

function makeEvent(overrides: Partial<HotStockAbnormalEvent>): HotStockAbnormalEvent {
  return {
    category: overrides.category || 'stock',
    id: String(overrides.id || `${overrides.type || 10001}-${overrides.code || '000001'}`),
    eventType: overrides.eventType || overrides.type || 10001,
    type: overrides.type || 10001,
    typeName: overrides.typeName || '火箭发射',
    direction: overrides.direction || 'up',
    severity: overrides.severity || 'normal',
    timestamp: overrides.timestamp || Date.parse('2026-05-15T10:00:00+08:00'),
    code: overrides.code || '000001',
    name: overrides.name || '测试股',
    changePct: overrides.changePct || 0,
    price: overrides.price || 10,
    relatedPlates: overrides.relatedPlates || [],
    sectorName: overrides.sectorName || '',
    matchedHotStock: false,
    matchedCandidate: false,
    raw: overrides.raw || {},
  }
}

describe('HotStockEventMonitorService', () => {
  afterEach(() => {
    refreshScheduler.stopTask('hotStockEvent.monitor')
    refreshTaskRegistry.resetRuntimeState()
    vi.useRealTimers()
  })

  it('splits today events into hot stocks, other stocks and sectors', async () => {
    const feed = {
      fetchEvents: vi.fn().mockResolvedValue([
        makeEvent({ id: 'old', code: '600001', timestamp: Date.parse('2026-05-14T14:00:00+08:00') }),
        makeEvent({ id: 'a', code: '600001', timestamp: Date.parse('2026-05-15T09:40:00+08:00') }),
        makeEvent({ id: 'a', code: '600001', timestamp: Date.parse('2026-05-15T09:41:00+08:00') }),
        makeEvent({ id: 'b', code: '000002.SZ', timestamp: Date.parse('2026-05-15T10:01:00+08:00') }),
        makeEvent({ id: 'c', code: '300001', timestamp: Date.parse('2026-05-15T10:02:00+08:00') }),
        makeEvent({
          id: 'sector-a',
          category: 'sector',
          code: '',
          name: '',
          sectorName: '机器人',
          type: 11000,
          eventType: 11000,
          typeName: '板块拉升',
          timestamp: Date.parse('2026-05-15T10:03:00+08:00'),
        }),
      ]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([
        { code: '600001', name: '一号' },
        { code: '000002', name: '二号' },
      ]),
      getDragonReview: vi.fn().mockReturnValue({
        candidates: [{ code: '600001' }],
        trueLeaders: [{ code: '000003' }],
        attentionBoard: [],
      }),
    }
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    const result = await service.refresh()

    expect(result.ok).toBe(true)
    expect(result.added).toBe(4)
    expect(result.watchedCodes).toEqual(['600001', '000002'])
    expect(result.hotStockEvents.map(event => event.id)).toEqual(['b', 'a'])
    expect(result.otherStockEvents.map(event => event.id)).toEqual(['c'])
    expect(result.sectorEvents.map(event => event.id)).toEqual(['sector-a'])
    expect(result.events.map(event => event.id)).toEqual(['sector-a', 'c', 'b', 'a'])
    expect(result.hotStockEvents[0]).toMatchObject({
      code: '000002',
      matchedHotStock: true,
      matchedCandidate: false,
    })
    expect(result.hotStockEvents[1]).toMatchObject({
      code: '600001',
      matchedHotStock: true,
      matchedCandidate: true,
    })
    expect(result.otherStockEvents[0]).toMatchObject({
      code: '300001',
      matchedHotStock: false,
      matchedCandidate: false,
    })
    expect(result.sectorEvents[0]).toMatchObject({
      category: 'sector',
      sectorName: '机器人',
      matchedHotStock: false,
      matchedCandidate: false,
    })
    expect(service.getState().latestHotStockAdded.map(event => event.id)).toEqual(['b', 'a'])
  })

  it('preserves previous events when feed fails', async () => {
    const firstFeed = {
      fetchEvents: vi.fn().mockResolvedValue([
        makeEvent({ id: 'a', code: '600001', timestamp: Date.parse('2026-05-15T09:40:00+08:00') }),
      ]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([{ code: '600001', name: '一号' }]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const service = new HotStockEventMonitorService({
      feed: firstFeed,
      dataLayer,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    await service.refresh()
    service.setFeed({
      fetchEvents: vi.fn().mockRejectedValue(new Error('network')),
    })
    const result = await service.refresh()

    expect(result.ok).toBe(false)
    expect(result.added).toBe(0)
    expect(result.error).toBe('network')
    expect(result.events.map(event => event.id)).toEqual(['a'])
    expect(result.hotStockEvents.map(event => event.id)).toEqual(['a'])
  })

  it('runs panel polling through the shared scheduler and pauses when hidden', async () => {
    vi.useFakeTimers()
    const visibility = { visibilityState: 'hidden' }
    vi.stubGlobal('document', visibility)
    const feed = {
      fetchEvents: vi.fn().mockResolvedValue([
        makeEvent({ id: 'a', code: '600001', timestamp: Date.parse('2026-05-15T09:40:00+08:00') }),
      ]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([{ code: '600001', name: '一号' }]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      intervalMs: 1_000,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    service.start()
    await vi.advanceTimersByTimeAsync(1_000)

    expect(feed.fetchEvents).not.toHaveBeenCalled()
    expect(refreshTaskRegistry.getTask('hotStockEvent.monitor')).toMatchObject({
      visibilityPolicy: 'pause',
      running: false,
      successCount: 0,
    })

    visibility.visibilityState = 'visible'
    await vi.advanceTimersByTimeAsync(1_000)

    expect(feed.fetchEvents).toHaveBeenCalledTimes(1)
    expect(refreshTaskRegistry.getTask('hotStockEvent.monitor')).toMatchObject({
      running: false,
      lastSuccessAt: expect.any(Number),
      successCount: 1,
      source: 'scheduler',
    })

    service.stop()
  })
})
