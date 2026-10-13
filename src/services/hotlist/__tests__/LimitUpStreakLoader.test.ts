import { describe, expect, it, vi } from 'vitest'

import { LimitUpStreakLoader, parseDateResponse } from '../LimitUpStreakLoader'

describe('LimitUpStreakLoader（对齐 LimitUpStreakLoader.cs）', () => {
  it('parseDateResponse：只取 data.info 的 6 位数字码', () => {
    expect(parseDateResponse({
      data: { info: [{ code: '600001' }, { code: 'abc' }, { code: '000002' }, {}] },
    })).toEqual(['600001', '000002'])
    expect(parseDateResponse({ data: null })).toEqual([])
    expect(parseDateResponse(null)).toEqual([])
  })

  it('连续交易日涨停 → 连板天数累加；中断日截断', async () => {
    const fetcher = vi.fn(async (url: string) => {
      const date = new URL(url, 'http://localhost').searchParams.get('date')
      // 2026-10-13 为周二；候选日 13(二),12(一),11(日跳过),10(六跳过),9(五),8(四),7(三),6(二)
      const pools: Record<string, string[]> = {
        '2026-10-13': [], // 今日（盘前空池常态，跳过）
        '2026-10-12': ['600001', '600002'], // 昨日：连板第 1 天
        '2026-10-09': ['600001'], // 周五：600001 连板第 2 天
        '2026-10-08': ['600001'], // 周四：600001 连板第 3 天
        '2026-10-07': [], // 空池 → 非交易日序列终止
      }
      return { ok: true, json: async () => ({ data: { info: (pools[date] || []).map(code => ({ code })) } }) }
    }) as unknown as typeof fetch

    const loader = new LimitUpStreakLoader({ fetcher, storage: null, now: () => Date.parse('2026-10-13T08:30:00+08:00') })
    const result = await loader.load()

    expect(result.streaks.get('600001')).toBe(3)
    expect(result.streaks.get('600002')).toBe(1)
    expect(result.coveredDates).toEqual(['2026-10-12', '2026-10-09', '2026-10-08'])
    expect(result.errors.some(item => item.includes('empty_pool_treated_as_non_trading_day'))).toBe(true)
  })

  it('盘中今日已有涨停池：今日数据不参与 streak 基准', async () => {
    const fetcher = vi.fn(async (url: string) => {
      const date = new URL(url, 'http://localhost').searchParams.get('date')
      const pools: Record<string, string[]> = {
        '2026-10-13': ['600001'], // 今日盘中涨停，不计入昨日基准
        '2026-10-12': ['600001'],
        '2026-10-11': [],
      }
      return { ok: true, json: async () => ({ data: { info: (pools[date] || []).map(code => ({ code })) } }) }
    }) as unknown as typeof fetch

    const loader = new LimitUpStreakLoader({ fetcher, storage: null, now: () => Date.parse('2026-10-13T10:30:00+08:00') })
    const result = await loader.load()
    // 今日封板不得污染"截至昨日"的连板计数
    expect(result.streaks.get('600001')).toBe(1)
  })
})
