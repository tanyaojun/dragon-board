import { describe, expect, it, vi } from 'vitest'

import { HotStockEventMonitorService } from '../HotStockEventMonitorService'
import type { HotStockAbnormalEvent } from '../hotStockEventTypes'

function makeEvent(overrides: Partial<HotStockAbnormalEvent>): HotStockAbnormalEvent {
  return {
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
    matchedHotStock: false,
    matchedCandidate: false,
    raw: overrides.raw || {},
  }
}

describe('HotStockEventMonitorService', () => {
  it('keeps only watched hotlist codes, marks candidates, dedupes and sorts today events', async () => {
    const feed = {
      fetchEvents: vi.fn().mockResolvedValue([
        makeEvent({ id: 'old', code: '600001', timestamp: Date.parse('2026-05-14T14:00:00+08:00') }),
        makeEvent({ id: 'a', code: '600001', timestamp: Date.parse('2026-05-15T09:40:00+08:00') }),
        makeEvent({ id: 'a', code: '600001', timestamp: Date.parse('2026-05-15T09:41:00+08:00') }),
        makeEvent({ id: 'b', code: '000002.SZ', timestamp: Date.parse('2026-05-15T10:01:00+08:00') }),
        makeEvent({ id: 'c', code: '300001', timestamp: Date.parse('2026-05-15T10:02:00+08:00') }),
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
    expect(result.added).toBe(2)
    expect(result.watchedCodes).toEqual(['600001', '000002'])
    expect(result.events.map(event => event.id)).toEqual(['b', 'a'])
    expect(result.events[0]).toMatchObject({
      code: '000002',
      matchedHotStock: true,
      matchedCandidate: false,
    })
    expect(result.events[1]).toMatchObject({
      code: '600001',
      matchedHotStock: true,
      matchedCandidate: true,
    })
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
  })
})
