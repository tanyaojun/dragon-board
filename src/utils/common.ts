// src/utils/common.ts

import { LIMIT_UP_CONFIG } from '@/config/constants'
/**
 * 防抖函数
 * @param fn 要执行的函数
 * @param delay 延迟时间（毫秒）
 * @returns 防抖后的函数
 */
export function debounce<T extends (...args: any[]) => any>(
  fn: T,
  delay: number,
): (...args: Parameters<T>) => void {
  let timer: ReturnType<typeof setTimeout> | null = null

  return function (this: any, ...args: Parameters<T>) {
    if (timer) {
      clearTimeout(timer)
    }

    timer = setTimeout(() => {
      fn.apply(this, args)
      timer = null
    }, delay)
  }
}

/**
 * 节流函数
 * @param fn 要执行的函数
 * @param delay 延迟时间（毫秒）
 * @returns 节流后的函数
 */
export function throttle<T extends (...args: any[]) => any>(
  fn: T,
  delay: number,
): (...args: Parameters<T>) => void {
  let lastTime = 0

  return function (this: any, ...args: Parameters<T>) {
    const now = Date.now()

    if (now - lastTime >= delay) {
      fn.apply(this, args)
      lastTime = now
    }
  }
}

/**
 * 深拷贝
 * @param obj 要拷贝的对象
 * @returns 拷贝后的对象
 */
export function deepClone<T>(obj: T): T {
  if (obj === null || typeof obj !== 'object') {
    return obj
  }

  if (obj instanceof Date) {
    return new Date(obj.getTime()) as any
  }

  if (obj instanceof Array) {
    return obj.map((item) => deepClone(item)) as any
  }

  if (obj instanceof Object) {
    return Object.fromEntries(
      Object.entries(obj).map(([key, value]) => [key, deepClone(value)]),
    ) as any
  }

  return obj
}

/**
 * 格式化数字（带单位）
 * @param num 数字
 * @param digits 小数位数
 * @returns 格式化后的字符串
 */
export function formatNumber(num: number, digits: number = 2): string {
  if (num === null || num === undefined || isNaN(num)) {
    return '0'
  }

  if (num >= 1e8) {
    return (num / 1e8).toFixed(digits) + '亿'
  }

  if (num >= 1e4) {
    return (num / 1e4).toFixed(digits) + '万'
  }

  return num.toFixed(digits)
}

/**
 * 格式化时间
 * @param timestamp 时间戳
 * @param format 格式（默认：YYYY-MM-DD HH:mm:ss）
 * @returns 格式化后的时间字符串
 */
export function formatDate(
  timestamp: number | string | Date,
  format: string = 'YYYY-MM-DD HH:mm:ss',
): string {
  const date = new Date(timestamp)

  if (isNaN(date.getTime())) {
    return 'Invalid Date'
  }

  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')

  return format
    .replace('YYYY', String(year))
    .replace('MM', month)
    .replace('DD', day)
    .replace('HH', hours)
    .replace('mm', minutes)
    .replace('ss', seconds)
}

/**
 * 生成唯一ID
 * @returns 唯一ID
 */
export function uniqueId(): string {
  return Date.now().toString(36) + Math.random().toString(36).substr(2)
}

/**
 * 检查对象是否为空
 * @param obj 要检查的对象
 * @returns 是否为空
 */
export function isEmpty(obj: any): boolean {
  if (obj === null || obj === undefined) {
    return true
  }

  if (typeof obj === 'string') {
    return obj.trim() === ''
  }

  if (Array.isArray(obj)) {
    return obj.length === 0
  }

  if (typeof obj === 'object') {
    return Object.keys(obj).length === 0
  }

  return false
}

/**
 * 安全解析JSON
 * @param str JSON字符串
 * @param defaultValue 默认值
 * @returns 解析后的对象
 */
export function safeJSONParse<T>(str: string, defaultValue: T): T {
  try {
    return JSON.parse(str)
  } catch {
    return defaultValue
  }
}

/**
 * 休眠函数
 * @param ms 毫秒数
 * @returns Promise
 */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * 重试函数
 * @param fn 要执行的函数
 * @param retries 重试次数
 * @param delay 延迟时间
 * @returns 函数执行结果
 */
export async function retry<T>(
  fn: () => Promise<T>,
  retries: number = 3,
  delay: number = 1000,
): Promise<T> {
  try {
    return await fn()
  } catch (error) {
    if (retries <= 0) {
      throw error
    }

    await sleep(delay)
    return retry(fn, retries - 1, delay * 2)
  }
}

/**
 * 分组函数
 * @param array 数组
 * @param key 分组键
 * @returns 分组后的对象
 */
export function groupBy<T>(array: T[], key: keyof T): Record<string, T[]> {
  return array.reduce(
    (result, item) => {
      const groupKey = String(item[key])

      if (!result[groupKey]) {
        result[groupKey] = []
      }

      result[groupKey].push(item)
      return result
    },
    {} as Record<string, T[]>,
  )
}

/**
 * 排序函数
 * @param array 数组
 * @param key 排序键
 * @param order 排序顺序（asc/desc）
 * @returns 排序后的数组
 */
export function sortBy<T>(array: T[], key: keyof T, order: 'asc' | 'desc' = 'asc'): T[] {
  return [...array].sort((a, b) => {
    const aVal = a[key]
    const bVal = b[key]

    if (aVal < bVal) {
      return order === 'asc' ? -1 : 1
    }

    if (aVal > bVal) {
      return order === 'asc' ? 1 : -1
    }

    return 0
  })
}

/**
 * 内存缓存
 */
export class MemoryCache<T = any> {
  private cache: Map<string, { value: T; expire: number }> = new Map()

  constructor(private defaultTTL: number = 5 * 60 * 1000) {} // 默认5分钟

  set(key: string, value: T, ttl: number = this.defaultTTL): void {
    this.cache.set(key, {
      value,
      expire: Date.now() + ttl,
    })
  }

  get(key: string): T | null {
    const item = this.cache.get(key)

    if (!item) {
      return null
    }

    if (item.expire < Date.now()) {
      this.cache.delete(key)
      return null
    }

    return item.value
  }

  has(key: string): boolean {
    return this.get(key) !== null
  }

  delete(key: string): void {
    this.cache.delete(key)
  }

  clear(): void {
    this.cache.clear()
  }

  keys(): string[] {
    return Array.from(this.cache.keys())
  }

  size(): number {
    return this.cache.size
  }
}

// ========== 股票工具类 ==========
/**
 * 检查股票代码是否有效
 * @param code 股票代码
 * @returns 是否为有效的6位数字代码
 */
export function isValidStockCode(code: any): boolean {
  if (!code) return false

  // 转成字符串并去除空格
  const strCode = String(code).trim()

  // 必须是6位数字
  if (!/^\d{6}$/.test(strCode)) return false

  return true
}

/**
 * 过滤出有效的股票代码
 * @param codes 股票代码数组
 * @returns 有效的股票代码数组
 */
export function filterValidStockCodes(codes: any[]): string[] {
  return codes.map((code) => String(code).trim()).filter((code) => /^\d{6}$/.test(code))
}

/** 规范化股票代码：去除非数字字符，补齐 6 位 */
export function normalizeStockCode(code: string): string {
  if (!code) return ''
  return String(code).replace(/[^0-9]/g, '').padStart(6, '0')
}

/**
 * 涨跌停阈值配置
 */
export interface LimitThreshold {
  up: number // 涨停阈值
  down: number // 跌停阈值
}

/**
 * 涨停判断结果
 */
export interface LimitCheckResult {
  isLimitUp: boolean // 是否涨停
  isLimitDown: boolean // 是否跌停
  isAlmostLimitUp: boolean // 是否接近涨停（比如9%以上）
  isAlmostLimitDown: boolean // 是否接近跌停
  threshold: LimitThreshold // 阈值
  change: number // 实际涨跌幅
  diff: number // 与涨停价的差值
}

/**
 * 股票工具类 - 用于判断涨跌停等
 */
export class StockUtils {
  /**
   * 获取股票的涨跌停阈值
   * @param code 股票代码
   * @param name 股票名称（用于判断ST）
   */
  static getLimitThreshold(code: string, name: string = ''): LimitThreshold {
    // ST股判断
    if (name.includes('ST') || name.includes('*ST')) {
      return {
        up: LIMIT_UP_CONFIG.THRESHOLDS.ST,
        down: -LIMIT_UP_CONFIG.THRESHOLDS.ST,
      }
    }

    // 根据代码前缀判断板块
    if (code.startsWith('60') || code.startsWith('00')) {
      return {
        up: LIMIT_UP_CONFIG.THRESHOLDS.MAIN,
        down: -LIMIT_UP_CONFIG.THRESHOLDS.MAIN,
      }
    }

    if (code.startsWith('30')) {
      return {
        up: LIMIT_UP_CONFIG.THRESHOLDS.GEM,
        down: -LIMIT_UP_CONFIG.THRESHOLDS.GEM,
      }
    }

    if (code.startsWith('688')) {
      return {
        up: LIMIT_UP_CONFIG.THRESHOLDS.STAR,
        down: -LIMIT_UP_CONFIG.THRESHOLDS.STAR,
      }
    }

    if (code.startsWith('8')) {
      return {
        up: LIMIT_UP_CONFIG.THRESHOLDS.NORTH,
        down: -LIMIT_UP_CONFIG.THRESHOLDS.NORTH,
      }
    }

    // 默认主板
    return {
      up: LIMIT_UP_CONFIG.THRESHOLDS.MAIN,
      down: -LIMIT_UP_CONFIG.THRESHOLDS.MAIN,
    }
  }

  /**
   * 判断是否涨停
   * @param change 涨跌幅
   * @param code 股票代码
   * @param name 股票名称
   * @param tolerance 容差（默认0.2%）
   */
  static isLimitUp(
    change: number,
    code: string,
    name: string = '',
    tolerance: number = LIMIT_UP_CONFIG.RULES.CHANGE_TOLERANCE,
  ): boolean {
    const threshold = this.getLimitThreshold(code, name)
    return change >= threshold.up - tolerance
  }

  /**
   * 判断是否跌停
   */
  static isLimitDown(
    change: number,
    code: string,
    name: string = '',
    tolerance: number = LIMIT_UP_CONFIG.RULES.CHANGE_TOLERANCE,
  ): boolean {
    const threshold = this.getLimitThreshold(code, name)
    return change <= threshold.down + tolerance
  }

  /**
   * 判断是否真实涨停（考虑封单等因素）
   */
  static isGenuineLimitUp(
    change: number,
    code: string,
    name: string = '',
    fengdan?: number,
    options?: {
      tolerance?: number
      minFengdan?: number
    },
  ): boolean {
    const tolerance = options?.tolerance ?? LIMIT_UP_CONFIG.RULES.CHANGE_TOLERANCE
    const minFengdan = options?.minFengdan ?? LIMIT_UP_CONFIG.RULES.MIN_FENGDAN

    // 基础涨停判断
    if (!this.isLimitUp(change, code, name, tolerance)) {
      return false
    }

    // 如果有封单要求，检查封单
    if (LIMIT_UP_CONFIG.RULES.REQUIRE_FENGDAN && fengdan !== undefined) {
      if (fengdan < minFengdan) {
        return false
      }
    }

    return true
  }

  /**
   * 获取涨停状态详情
   */
  static checkLimitStatus(
    change: number,
    code: string,
    name: string = '',
    tolerance: number = LIMIT_UP_CONFIG.RULES.CHANGE_TOLERANCE,
  ): LimitCheckResult {
    const threshold = this.getLimitThreshold(code, name)
    const isLimitUp = change >= threshold.up - tolerance
    const isLimitDown = change <= threshold.down + tolerance

    return {
      isLimitUp,
      isLimitDown,
      isAlmostLimitUp: change >= threshold.up - tolerance * 3,
      isAlmostLimitDown: change <= threshold.down + tolerance * 3,
      threshold,
      change,
      diff: isLimitUp ? change - threshold.up : change - threshold.down,
    }
  }

  /**
   * 批量检查多个股票的涨停状态
   */
  static batchCheckLimitStatus(
    stocks: Array<{ code: string; name: string; change: number }>,
  ): Map<string, LimitCheckResult> {
    const results = new Map<string, LimitCheckResult>()

    stocks.forEach((stock) => {
      const result = this.checkLimitStatus(stock.change, stock.code, stock.name)
      results.set(stock.code, result)
    })

    return results
  }
}


export const stockUtils = StockUtils
