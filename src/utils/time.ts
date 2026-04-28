// src/utils/time.ts
import { Lunar } from 'lunar-javascript'

export const isTradingTime = (date: Date = new Date()): boolean => {
  const day = date.getDay()
  const time = date.getHours() * 100 + date.getMinutes()

  // 周末
  if (day === 0 || day === 6) return false

  // 法定节假日
  if (isHoliday(date)) return false

  // 上午盘 9:30 - 11:30
  if (time >= 930 && time < 1200) return true

  // 下午盘 13:00 - 15:00
  if (time >= 1300 && time <= 1500) return true

  return false
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
 * 判断是否为集合竞价时间
 */
export const isOpeningAuction = (): boolean => {
  const now = new Date()
  const time = now.getHours() * 100 + now.getMinutes()
  return time >= 925 && time <= 930
}

/**
 * 判断是否为收盘集合竞价
 */
export const isClosingAuction = (): boolean => {
  const now = new Date()
  const time = now.getHours() * 100 + now.getMinutes()
  return time >= 1457 && time <= 1500
}
