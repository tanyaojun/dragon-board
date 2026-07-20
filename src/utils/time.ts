// src/utils/time.ts
// A 股交易日历 — 优先从通达信行情桥获取真实交易日历，不可用时回退到简单工作日判断。
// 所有交易时段相关的纯时间窗口判断（集合竞价、午休等）保持不变，只替换"哪天是交易日"这一层。

const BRIDGE_CALENDAR_URL = 'http://127.0.0.1:8765/api/calendar'
const dateCalendarCache = new Map<string, boolean>()
const pendingFetches = new Map<string, Promise<boolean | null>>()

// 硬编码假期列表仅作为桥不可达时的回退，真实交易日历以桥的 mootdx holiday 模块为准
const FALLBACK_HOLIDAY_RANGES: [string, string][] = [
  ['2026-01-01', '2026-01-03'],
  ['2026-02-15', '2026-02-23'],
  ['2026-04-04', '2026-04-06'],
  ['2026-05-01', '2026-05-05'],
  ['2026-06-19', '2026-06-21'],
  ['2026-09-25', '2026-09-27'],
  ['2026-10-01', '2026-10-07'],
]

function isFallbackHoliday(date: Date): boolean {
  const key = dateKey(date)
  return FALLBACK_HOLIDAY_RANGES.some(([start, end]) => key >= start && key <= end)
}

function dateKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

async function fetchCalendarForDate(dateStr: string): Promise<boolean | null> {
  try {
    const resp = await fetch(`${BRIDGE_CALENDAR_URL}?date=${encodeURIComponent(dateStr)}`)
    if (!resp.ok) return null
    const data = await resp.json()
    if (typeof data?.isTradingDay === 'boolean') {
      return data.isTradingDay
    }
  } catch {
    // bridge 不可达
  }
  return null
}

function queryCalendarForDate(date: Date): boolean {
  const key = dateKey(date)

  // 缓存命中直接返回
  const cached = dateCalendarCache.get(key)
  if (cached !== undefined) return cached

  // 发起异步请求（不阻塞同步返回）
  if (!pendingFetches.has(key)) {
    const promise = fetchCalendarForDate(key).then((result) => {
      pendingFetches.delete(key)
      if (result !== null) {
        dateCalendarCache.set(key, result)
      }
      return result
    })
    pendingFetches.set(key, promise)
  }

  // 回退：周末 + 硬编码假期列表（仅桥不可达时）
  const day = date.getDay()
  if (day === 0 || day === 6) return false
  if (isFallbackHoliday(date)) return false
  return true
}

/** 判断指定日期是否为 A 股交易日（优先桥日历，回退周末检查） */
export const isAshareTradingDay = (date: Date = new Date()): boolean => {
  const key = dateKey(date)
  const cached = dateCalendarCache.get(key)
  if (cached !== undefined) return cached

  return queryCalendarForDate(date)
}

/** 判断当前是否在 A 股交易时段内（含集合竞价和盘后） */
export const isTradingTime = (date: Date = new Date()): boolean => {
  if (!isAshareTradingDay(date)) return false

  const minutes = date.getHours() * 60 + date.getMinutes()
  // 早盘：9:15–11:30（含集合竞价）
  if (minutes >= 9 * 60 + 15 && minutes <= 11 * 60 + 30) return true
  // 下午：13:00–15:30（含盘后固定价格交易）
  if (minutes >= 13 * 60 && minutes <= 15 * 60 + 30) return true

  return false
}

/** 手动刷新交易日历缓存（bridge 重连后调用） */
export const refreshCalendar = async (): Promise<void> => {
  dateCalendarCache.clear()
  const key = dateKey(new Date())
  const result = await fetchCalendarForDate(key)
  if (result !== null) {
    dateCalendarCache.set(key, result)
  }
}

export type TradingStatus =
  | 'non_trading_day'
  | 'pre_market'
  | 'call_auction'
  | 'trading'
  | 'lunch_break'
  | 'after_hours'
  | 'closed'

export const TRADING_STATUS_LABEL: Record<TradingStatus, string> = {
  non_trading_day: '非交易日',
  pre_market: '未开盘',
  call_auction: '集合竞价',
  trading: '交易中',
  lunch_break: '午间休市',
  after_hours: '盘后交易',
  closed: '已收盘',
}

export const getTradingStatus = (date: Date = new Date()): TradingStatus => {
  if (!isAshareTradingDay(date)) return 'non_trading_day'

  const minutes = date.getHours() * 60 + date.getMinutes()

  if (minutes < 9 * 60 + 15) return 'pre_market'
  if (minutes >= 9 * 60 + 15 && minutes <= 9 * 60 + 25) return 'call_auction'
  if (minutes > 9 * 60 + 25 && minutes <= 11 * 60 + 30) return 'trading'
  if (minutes > 11 * 60 + 30 && minutes < 13 * 60) return 'lunch_break'
  if (minutes >= 13 * 60 && minutes <= 15 * 60) return 'trading'
  if (minutes > 15 * 60 && minutes <= 15 * 60 + 30) return 'after_hours'
  return 'closed'
}

/** 早盘集合竞价时间 9:15–9:25 */
export const isOpeningAuction = (): boolean => {
  const now = new Date()
  const time = now.getHours() * 100 + now.getMinutes()
  return time >= 915 && time <= 925
}

/** 收盘集合竞价时间 14:57–15:00 */
export const isClosingAuction = (): boolean => {
  const now = new Date()
  const time = now.getHours() * 100 + now.getMinutes()
  return time >= 1457 && time <= 1500
}

/** 盘后固定价格交易 15:00–15:30 */
export const isAfterHoursFixedPrice = (): boolean => {
  const now = new Date()
  const time = now.getHours() * 100 + now.getMinutes()
  return time >= 1500 && time <= 1530
}

// 启动时预拉日历
queryCalendarForDate(new Date())
