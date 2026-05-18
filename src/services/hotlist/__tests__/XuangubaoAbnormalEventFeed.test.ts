import { describe, expect, it, vi } from 'vitest'

import {
  XUANGUBAO_STOCK_ABNORMAL_EVENT_TYPES,
  XuangubaoAbnormalEventFeed,
  parseXuangubaoAbnormalEvents,
} from '../XuangubaoAbnormalEventFeed'

describe('XuangubaoAbnormalEventFeed', () => {
  it('binds the default browser fetch to globalThis', async () => {
    const originalFetch = globalThis.fetch
    const fetcher = vi.fn(function (this: typeof globalThis) {
      if (this !== globalThis) throw new TypeError('Illegal invocation')
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ data: [] }),
      } as Response)
    })
    vi.stubGlobal('fetch', fetcher)

    try {
      const feed = new XuangubaoAbnormalEventFeed()
      await expect(feed.fetchEvents()).resolves.toEqual([])
      expect(fetcher).toHaveBeenCalledWith('/api/xuangubao/events')
    } finally {
      vi.stubGlobal('fetch', originalFetch)
    }
  })

  it('requests local proxy and parses stock abnormal events', async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        data: {
          stock_abnormal_event_data: [
            {
              id: 'evt-1',
              event_type: 10001,
              event_type_name: '火箭发射',
              created_at: 1714379400000,
              stock_code: '300750.SZ',
              stock_name: '宁德时代',
              change_percent: 4.56,
              price: 198.5,
              related_plates: [
                { plate_name: '锂电池' },
                { name: '储能' },
              ],
            },
          ],
          plate_abnormal_event_data: [
            {
              id: 'sector-1',
              event_type: 11000,
              event_type_name: '板块拉升',
              stock_code: 'BK001',
            },
          ],
        },
      }),
    })

    const feed = new XuangubaoAbnormalEventFeed({ fetcher })
    const events = await feed.fetchEvents()

    expect(fetcher).toHaveBeenCalledWith('/api/xuangubao/events')
    expect(events).toHaveLength(2)
    expect(events[0]).toMatchObject({
      category: 'stock',
      id: 'evt-1',
      eventType: 10001,
      type: 10001,
      typeName: '火箭发射',
      direction: 'up',
      severity: 'normal',
      timestamp: 1714379400000,
      code: '300750',
      name: '宁德时代',
      changePct: 0.0456,
      price: 198.5,
      relatedPlates: ['锂电池', '储能'],
      matchedHotStock: false,
      matchedCandidate: false,
    })
    expect(events[1]).toMatchObject({
      category: 'sector',
      id: 'sector-1',
      eventType: 11000,
      type: 11000,
      typeName: '板块拉升',
      direction: 'up',
      sectorName: 'BK001',
    })
  })

  it('parses event history rows with nested stock_abnormal_event_data', () => {
    const events = parseXuangubaoAbnormalEvents({
      data: [
        {
          id: 100,
          event_type: 10007,
          event_timestamp: 1778810400,
          stock_abnormal_event_data: {
            symbol: '002445.SZ',
            name: '中南文化',
            pcp: 0.0954,
            current_price: 3.21,
            related_plates: [
              { plate_name: '影视' },
              { plate_name: '知识产权' },
            ],
          },
        },
        {
          id: 101,
          event_type: 11000,
          event_timestamp: 1778810401,
          plate_abnormal_event_data: {
            plate_name: '影视',
          },
        },
      ],
    })

    expect(events).toHaveLength(2)
    expect(events[0]).toMatchObject({
      category: 'stock',
      id: '100',
      eventType: 10007,
      type: 10007,
      typeName: '即将打开涨停',
      timestamp: 1778810400000,
      code: '002445',
      name: '中南文化',
      changePct: 0.0954,
      price: 3.21,
      relatedPlates: ['影视', '知识产权'],
    })
    expect(events[1]).toMatchObject({
      category: 'sector',
      id: '101',
      eventType: 11000,
      typeName: '板块拉升',
      timestamp: 1778810401000,
      sectorName: '影视',
      direction: 'up',
    })
  })

  it('uses plate_abnormal_event_data when stock_abnormal_event_data is an empty object', () => {
    const events = parseXuangubaoAbnormalEvents({
      data: [
        {
          id: 9110082,
          target: '785',
          event_type: 11000,
          event_timestamp: 1779081368,
          stock_abnormal_event_data: {},
          plate_abnormal_event_data: {
            plate_id: 86475809,
            plate_name: '英伟达概念',
            pcp: 0.01203161291621622,
          },
          good_or_bad: 1,
        },
      ],
    })

    expect(events).toHaveLength(1)
    expect(events[0]).toMatchObject({
      category: 'sector',
      id: '9110082',
      eventType: 11000,
      typeName: '板块拉升',
      timestamp: 1779081368000,
      sectorName: '英伟达概念',
      name: '英伟达概念',
      changePct: 0.012032,
    })
  })

  it('parses alternate payload shapes and keeps sector event types', () => {
    const events = parseXuangubaoAbnormalEvents({
      stock_abnormal_event_data: [
        {
          event_id: 'evt-2',
          type: 10006,
          type_name: '有大卖盘',
          timestamp: 1714381200,
          code: 'SH600519',
          name: '贵州茅台',
          change: -2.34,
          current_price: '1700.1',
        },
        {
          event_id: 'evt-3',
          type: 11001,
          type_name: '板块跳水',
          code: '000001.SZ',
        },
      ],
    })

    expect(XUANGUBAO_STOCK_ABNORMAL_EVENT_TYPES).not.toContain(11000)
    expect(XUANGUBAO_STOCK_ABNORMAL_EVENT_TYPES).not.toContain(11001)
    expect(events).toEqual([
      expect.objectContaining({
        category: 'stock',
        id: 'evt-2',
        type: 10006,
        typeName: '有大卖盘',
        direction: 'down',
        severity: 'normal',
        timestamp: 1714381200000,
        code: '600519',
        name: '贵州茅台',
        changePct: -0.0234,
        price: 1700.1,
      }),
      expect.objectContaining({
        category: 'sector',
        id: 'evt-3',
        type: 11001,
        typeName: '板块跳水',
        direction: 'down',
      }),
    ])
  })

  it('throws when the local proxy returns a degraded envelope', async () => {
    const feed = new XuangubaoAbnormalEventFeed({
      fetcher: vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({
          ok: false,
          degraded: true,
          errorCode: 'upstream_network_error',
          message: 'upstream unavailable',
          data: [],
        }),
      }),
    })

    await expect(feed.fetchEvents()).rejects.toThrow('upstream unavailable')
  })
})
