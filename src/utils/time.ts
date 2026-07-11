// src/utils/time.ts
import { Lunar } from 'lunar-javascript'

const A_SHARE_MARKET_HOLIDAY_RANGES = [
  // 2026 年 A 股休市安排按上交所 2025-12-22 公告维护。
  ['2026-01-01', '2026-01-03'],
  ['2026-02-15', '2026-02-23'],
  ['2026-04-04', '2026-04-06'],
  ['2026-05-01', '2026-05-05'],
  ['2026-06-19', '2026-06-21'],
  ['2026-09-25', '2026-09-27'],
  ['2026-10-01', '2026-10-07'],
] as const

function toLocalDateKey(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function isAshareMarketHoliday(date: Date): boolean {
  const key = toLocalDateKey(date)
  return A_SHARE_MARKET_HOLIDAY_RANGES.some(([start, end]) => key >= start && key <= end)
}

export const isAshareTradingDay = (date: Date = new Date()): boolean => {
  const day = date.getDay()
  if (day === 0 || day === 6) return false
  if (isAshareMarketHoliday(date)) return false
  if (isHoliday(date)) return false
  return true
}

export const isTradingTime = (date: Date = new Date()): boolean => {
  const minutes = date.getHours() * 60 + date.getMinutes()

  if (!isAshareTradingDay(date)) return false

  // A 股交易时段，含集合竞价、连续竞价和盘后固定价格交易。
  if (minutes >= 9 * 60 + 15 && minutes <= 11 * 60 + 30) return true
  if (minutes >= 13 * 60 && minutes <= 15 * 60 + 30) return true

  return false
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

  // 未开盘：交易日 9:15 之前
  if (minutes < 9 * 60 + 15) return 'pre_market'

  // 早盘集合竞价：9:15-9:25
  if (minutes >= 9 * 60 + 15 && minutes <= 9 * 60 + 25) return 'call_auction'

  // 早盘连续竞价 / 开盘匹配期：9:25-11:30
  if (minutes > 9 * 60 + 25 && minutes <= 11 * 60 + 30) return 'trading'

  // 午间休市：11:30-13:00
  if (minutes > 11 * 60 + 30 && minutes < 13 * 60) return 'lunch_break'

  // 下午连续竞价（含 14:57-15:00 收盘集合竞价）：13:00-15:00
  if (minutes >= 13 * 60 && minutes <= 15 * 60) return 'trading'

  // 盘后固定价格交易（科创板/创业板）：15:00-15:30
  if (minutes > 15 * 60 && minutes <= 15 * 60 + 30) return 'after_hours'

  // 已收盘：交易日 15:30 之后
  return 'closed'
}

/**
 * 判断是否为法定节假日
 */
function isHoliday(date: Date): boolean {
  const lunar = Lunar.fromDate(date)
  const year = date.getFullYear()
  const month = date.getMonth() + 1
  const day = date.getDate()

  // 元旦 1月1日
  if (month === 1 && day === 1) return true

  // 劳动节 5月1日
  if (month === 5 && day === 1) return true

  // 清明节（4月4日或5日）
  if (month === 4 && (day === 4 || day === 5)) return true

  // 端午节（农历五月初五）
  if (lunar.getMonth() === 5 && lunar.getDay() === 5) return true

  // 中秋节（农历八月十五）
  if (lunar.getMonth() === 8 && lunar.getDay() === 15) return true

  // 春节（农历正月初一，放假7天）
  if (lunar.getMonth() === 1 && lunar.getDay() === 1) {
    const chunjieDate = lunar.getSolarDate()
    const diffDays = Math.floor((date.getTime() - chunjieDate.getTime()) / (1000 * 60 * 60 * 24))
    // 除夕到初六
    if (diffDays >= -1 && diffDays <= 6) return true
  }

  // 国庆节 10月1日-7日
  if (month === 10 && day >= 1 && day <= 7) return true

  return false
}

/**
 * 判断是否为早盘集合竞价时间（9:15–9:25）
 * 上交所/深交所/北交所开盘集合竞价，可申报不可撤单（9:20 后不可撤单）
 */
export const isOpeningAuction = (): boolean => {
  const now = new Date()
  const time = now.getHours() * 100 + now.getMinutes()
  return time >= 915 && time <= 925
}

/**
 * 判断是否为收盘集合竞价时间（14:57–15:00）
 * 深市/沪市收盘集合竞价，仅可申报不可撤单
 */
export const isClosingAuction = (): boolean => {
  const now = new Date()
  const time = now.getHours() * 100 + now.getMinutes()
  return time >= 1457 && time <= 1500
}

/**
 * 判断是否为盘后固定价格交易时间（15:00–15:30）
 * 仅科创板（STAR Market）和创业板（ChiNext）有效，主板不适用
 */
export const isAfterHoursFixedPrice = (): boolean => {
  const now = new Date()
  const time = now.getHours() * 100 + now.getMinutes()
  return time >= 1500 && time <= 1530
}
