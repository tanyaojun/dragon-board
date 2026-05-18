import { describe, expect, it } from 'vitest'

import { CompositeHotStockEventFeed } from '../CompositeHotStockEventFeed'
import type { HotStockAbnormalEvent } from '../hotStockEventTypes'

function makeEvent(overrides: Partial<HotStockAbnormalEvent>): HotStockAbnormalEvent {
  return {
    category: 'stock',
    id: overrides.id || `${overrides.type || 10001}-${overrides.code || '600001'}`,
    eventType: overrides.eventType || overrides.type || 10001,
    type: overrides.type || 10001,
    typeName: overrides.typeName || '封涨停板',
    direction: overrides.direction || 'up',
    severity: overrides.severity || 'normal',
    timestamp: overrides.timestamp || Date.parse('2026-05-15T10:00:00+08:00'),
    code: overrides.code || '600001',
    name: overrides.name || '样本股',
    changePct: overrides.changePct ?? 0.1,
    price: overrides.price ?? null,
    relatedPlates: overrides.relatedPlates || [],
    sectorName: overrides.sectorName || '',
    matchedHotStock: false,
    matchedCandidate: false,
    raw: overrides.raw || {},
  }
}

describe('CompositeHotStockEventFeed', () => {
  it('keeps the first source event when feeds report the same code type and timestamp', async () => {
    const timestamp = Date.parse('2026-05-15T10:00:00+08:00')
    const feed = new CompositeHotStockEventFeed([
      {
        fetchEvents: async () => [
          makeEvent({ id: 'xgb-a', code: '600001', timestamp, raw: { source: 'xuangubao' } }),
        ],
      },
      {
        fetchEvents: async () => [
          makeEvent({ id: 'ths-a', code: '600001', timestamp, raw: { source: 'ths-limitup-pools' } }),
          makeEvent({ id: 'ths-b', code: '600002', timestamp: timestamp + 1000 }),
        ],
      },
    ])

    const events = await feed.fetchEvents()

    expect(events.map(event => event.id)).toEqual(['ths-b', 'xgb-a'])
  })

  it('returns successful feed events when a secondary source fails', async () => {
    const feed = new CompositeHotStockEventFeed([
      {
        fetchEvents: async () => [makeEvent({ id: 'xgb-a' })],
      },
      {
        fetchEvents: async () => {
          throw new Error('ths offline')
        },
      },
    ])

    await expect(feed.fetchEvents()).resolves.toEqual([expect.objectContaining({ id: 'xgb-a' })])
  })

  it('returns an empty list when any source succeeds even if another source fails', async () => {
    const feed = new CompositeHotStockEventFeed([
      {
        fetchEvents: async () => [],
      },
      {
        fetchEvents: async () => {
          throw new Error('ths offline')
        },
      },
    ])

    await expect(feed.fetchEvents()).resolves.toEqual([])
  })
})
