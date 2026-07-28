import { describe, it, expect, afterAll, afterEach, beforeAll, vi } from 'vitest'
import {
  isAshareTradingDay,
  isTradingTime,
  getTradingStatus,
  isOpeningAuction,
  isClosingAuction,
  isAfterHoursFixedPrice,
  refreshCalendar,
  TRADING_STATUS_LABEL,
} from '../time'
import type { TradingStatus } from '../time'

// 2026-07-10 是周五（交易日），2026-07-11 是周六（非交易日）
const TRADING_DAY = new Date(2026, 6, 10) // 2026-07-10 Friday
const WEEKEND_DAY = new Date(2026, 6, 11) // 2026-07-11 Saturday

beforeAll(async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
    const date = new URL(String(input)).searchParams.get('date')
    return {
      ok: true,
      json: async () => ({ ok: true, isTradingDay: date === '2026-07-10' }),
    }
  }))
  await refreshCalendar(TRADING_DAY)
  await refreshCalendar(WEEKEND_DAY)
  await refreshCalendar(new Date(2026, 6, 12))
  await refreshCalendar(new Date(2026, 9, 1))
})

afterAll(() => {
  vi.unstubAllGlobals()
})

function setTime(hour: number, minute: number, date: Date = TRADING_DAY): Date {
  const d = new Date(date)
  d.setHours(hour, minute, 0, 0)
  return d
}

afterEach(() => {
  vi.useRealTimers()
})

describe('isAshareTradingDay', () => {
  it('交易日（周五）返回 true', () => {
    expect(isAshareTradingDay(TRADING_DAY)).toBe(true)
  })

  it('周六返回 false', () => {
    expect(isAshareTradingDay(WEEKEND_DAY)).toBe(false)
  })

  it('周日返回 false', () => {
    const sun = new Date(2026, 6, 12) // 2026-07-12 Sunday
    expect(isAshareTradingDay(sun)).toBe(false)
  })

  it('国庆假期返回 false', () => {
    const nationalDay = new Date(2026, 9, 1) // 2026-10-01
    expect(isAshareTradingDay(nationalDay)).toBe(false)
  })

  it('bridge 日历不可用时不按工作日猜测', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error('bridge unavailable'))
    const unknownWeekday = new Date(2026, 6, 13)

    await refreshCalendar(unknownWeekday)

    expect(isAshareTradingDay(unknownWeekday)).toBe(false)
  })
})

describe('isTradingTime', () => {
  it('非交易日返回 false', () => {
    expect(isTradingTime(setTime(10, 0, WEEKEND_DAY))).toBe(false)
  })

  it('9:14 返回 false（集合竞价之前）', () => {
    expect(isTradingTime(setTime(9, 14))).toBe(false)
  })

  it('9:15 返回 true（集合竞价开始）', () => {
    expect(isTradingTime(setTime(9, 15))).toBe(true)
  })

  it('9:25 返回 true（集合竞价期间）', () => {
    expect(isTradingTime(setTime(9, 25))).toBe(true)
  })

  it('10:00 返回 true（早盘连续竞价）', () => {
    expect(isTradingTime(setTime(10, 0))).toBe(true)
  })

  it('11:30 返回 true（早盘收盘快照槽位）', () => {
    expect(isTradingTime(setTime(11, 30))).toBe(true)
  })

  it('12:00 返回 false（午间休市）', () => {
    expect(isTradingTime(setTime(12, 0))).toBe(false)
  })

  it('13:00 返回 true（下午盘开始）', () => {
    expect(isTradingTime(setTime(13, 0))).toBe(true)
  })

  it('15:00 返回 true（收盘快照槽位）', () => {
    expect(isTradingTime(setTime(15, 0))).toBe(true)
  })

  it('15:30 返回 true（盘后固定价格交易结束）', () => {
    expect(isTradingTime(setTime(15, 30))).toBe(true)
  })

  it('15:31 返回 false（盘后交易结束后）', () => {
    expect(isTradingTime(setTime(15, 31))).toBe(false)
  })
})

describe('getTradingStatus', () => {
  it('日历查询尚未完成时不伪装成非交易日', () => {
    const uncachedDate = new Date(2026, 6, 14, 10, 0)

    expect(getTradingStatus(uncachedDate)).toBe('calendar_pending')
  })

  it('非交易日返回 non_trading_day', () => {
    expect(getTradingStatus(setTime(10, 0, WEEKEND_DAY))).toBe('non_trading_day')
  })

  it('9:00 返回 pre_market', () => {
    expect(getTradingStatus(setTime(9, 0))).toBe('pre_market')
  })

  it('9:15 返回 call_auction（早盘集合竞价开始）', () => {
    expect(getTradingStatus(setTime(9, 15))).toBe('call_auction')
  })

  it('9:20 返回 call_auction（早盘集合竞价期间）', () => {
    expect(getTradingStatus(setTime(9, 20))).toBe('call_auction')
  })

  it('9:25 返回 call_auction（早盘集合竞价最后时刻）', () => {
    expect(getTradingStatus(setTime(9, 25))).toBe('call_auction')
  })

  it('9:26 返回 trading（集合竞价结束，进入开盘匹配/连续竞价）', () => {
    expect(getTradingStatus(setTime(9, 26))).toBe('trading')
  })

  it('10:00 返回 trading（早盘连续竞价）', () => {
    expect(getTradingStatus(setTime(10, 0))).toBe('trading')
  })

  it('11:30 返回 trading（早盘收盘）', () => {
    expect(getTradingStatus(setTime(11, 30))).toBe('trading')
  })

  it('12:00 返回 lunch_break（午间休市）', () => {
    expect(getTradingStatus(setTime(12, 0))).toBe('lunch_break')
  })

  it('13:00 返回 trading（下午盘开始）', () => {
    expect(getTradingStatus(setTime(13, 0))).toBe('trading')
  })

  it('14:57 返回 trading（收盘集合竞价期间）', () => {
    expect(getTradingStatus(setTime(14, 57))).toBe('trading')
  })

  it('15:00 返回 trading（收盘集合竞价结束）', () => {
    expect(getTradingStatus(setTime(15, 0))).toBe('trading')
  })

  it('15:01 返回 after_hours（盘后固定价格交易）', () => {
    expect(getTradingStatus(setTime(15, 1))).toBe('after_hours')
  })

  it('15:30 返回 after_hours（盘后交易最后时刻）', () => {
    expect(getTradingStatus(setTime(15, 30))).toBe('after_hours')
  })

  it('15:31 返回 closed（已收盘）', () => {
    expect(getTradingStatus(setTime(15, 31))).toBe('closed')
  })

  it('18:00 返回 closed（盘后）', () => {
    expect(getTradingStatus(setTime(18, 0))).toBe('closed')
  })
})

describe('TRADING_STATUS_LABEL', () => {
  it('所有 TradingStatus 值都有对应标签', () => {
    const allStatuses: TradingStatus[] = [
      'calendar_pending',
      'non_trading_day',
      'pre_market',
      'call_auction',
      'trading',
      'lunch_break',
      'after_hours',
      'closed',
    ]
    for (const s of allStatuses) {
      expect(TRADING_STATUS_LABEL[s]).toBeDefined()
      expect(typeof TRADING_STATUS_LABEL[s]).toBe('string')
    }
  })
})

describe('isOpeningAuction', () => {
  it('9:14 返回 false', () => {
    vi.setSystemTime(setTime(9, 14))
    expect(isOpeningAuction()).toBe(false)
  })

  it('9:15 返回 true', () => {
    vi.setSystemTime(setTime(9, 15))
    expect(isOpeningAuction()).toBe(true)
  })

  it('9:25 返回 true', () => {
    vi.setSystemTime(setTime(9, 25))
    expect(isOpeningAuction()).toBe(true)
  })

  it('9:26 返回 false', () => {
    vi.setSystemTime(setTime(9, 26))
    expect(isOpeningAuction()).toBe(false)
  })
})

describe('isClosingAuction', () => {
  it('14:56 返回 false', () => {
    vi.setSystemTime(setTime(14, 56))
    expect(isClosingAuction()).toBe(false)
  })

  it('14:57 返回 true', () => {
    vi.setSystemTime(setTime(14, 57))
    expect(isClosingAuction()).toBe(true)
  })

  it('15:00 返回 true', () => {
    vi.setSystemTime(setTime(15, 0))
    expect(isClosingAuction()).toBe(true)
  })

  it('15:01 返回 false', () => {
    vi.setSystemTime(setTime(15, 1))
    expect(isClosingAuction()).toBe(false)
  })
})

describe('isAfterHoursFixedPrice', () => {
  it('14:59 返回 false', () => {
    vi.setSystemTime(setTime(14, 59))
    expect(isAfterHoursFixedPrice()).toBe(false)
  })

  it('15:00 返回 true', () => {
    vi.setSystemTime(setTime(15, 0))
    expect(isAfterHoursFixedPrice()).toBe(true)
  })

  it('15:30 返回 true', () => {
    vi.setSystemTime(setTime(15, 30))
    expect(isAfterHoursFixedPrice()).toBe(true)
  })

  it('15:31 返回 false', () => {
    vi.setSystemTime(setTime(15, 31))
    expect(isAfterHoursFixedPrice()).toBe(false)
  })
})
