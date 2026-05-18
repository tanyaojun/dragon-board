import { describe, expect, it } from 'vitest'

import { ThsLimitUpEventFeed } from '../ThsLimitUpEventFeed'

describe('ThsLimitUpEventFeed', () => {
  it('maps ths limit-up pools to abnormal stock events', async () => {
    const feed = new ThsLimitUpEventFeed({
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
      api: {
        getThsLimitUpPools: async () => ({
          pools: {
            one: {
              ok: true,
              items: [
                {
                  stock_code: '600001',
                  stock_name: '样本一',
                  change: 10.01,
                  limit_up_time: '09:35',
                  limit_up_reason: '机器人+低空经济',
                },
              ],
            },
            failed: {
              ok: true,
              items: [
                {
                  stock_code: '600002',
                  stock_name: '样本二',
                  change_rate: 7.6,
                  limit_up_time: '10:12:03',
                  limit_up_reason: '汽车零部件',
                },
              ],
            },
            rushing: {
              ok: true,
              items: [
                {
                  stock_code: '600003',
                  stock_name: '样本三',
                  change_rate: 9.2,
                  limit_up_reason: '消费电子',
                },
              ],
            },
            drawdown: {
              ok: true,
              items: [
                {
                  stock_code: '600004',
                  stock_name: '大面样本',
                  max_drawdown: -12.5,
                },
              ],
            },
          },
        }),
      },
    })

    const events = await feed.fetchEvents()
    const byCode = new Map(events.map(event => [event.code, event]))

    expect([...byCode.keys()].sort()).toEqual(['600001', '600002', '600003'])
    expect(byCode.get('600001')).toMatchObject({
      type: 10001,
      typeName: '封涨停板',
      direction: 'up',
      severity: 'important',
      timestamp: Date.parse('2026-05-15T09:35:00+08:00'),
      changePct: 0.1001,
      relatedPlates: ['机器人', '低空经济'],
    })
    expect(byCode.get('600002')).toMatchObject({
      type: 10003,
      typeName: '打开涨停板',
      direction: 'up',
      severity: 'normal',
      timestamp: Date.parse('2026-05-15T10:12:03+08:00'),
      relatedPlates: ['汽车零部件'],
    })
    expect(byCode.get('600003')).toMatchObject({
      type: 10005,
      typeName: '逼近涨停',
      direction: 'up',
      relatedPlates: ['消费电子'],
    })
  })

  it('keeps event id stable when ths row has no limit-up time', async () => {
    let now = Date.parse('2026-05-15T10:05:00+08:00')
    const feed = new ThsLimitUpEventFeed({
      now: () => now,
      api: {
        getThsLimitUpPools: async () => ({
          pools: {
            rushing: {
              ok: true,
              items: [
                {
                  stock_code: '600003',
                  stock_name: '样本三',
                  change_rate: 9.2,
                  limit_up_reason: '消费电子',
                },
              ],
            },
          },
        }),
      },
    })

    const first = await feed.fetchEvents()
    now = Date.parse('2026-05-15T10:06:00+08:00')
    const second = await feed.fetchEvents()

    expect(first[0].id).toBe(second[0].id)
    expect(second[0].timestamp).toBe(Date.parse('2026-05-15T10:06:00+08:00'))
  })
})
