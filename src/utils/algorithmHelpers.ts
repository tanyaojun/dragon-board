// src/utils/algorithmHelpers.ts
// 算法工具函数

import type { Stock } from '@/types'

/**
 * 生成版本化的缓存键
 */
export function createCacheKey(
  prefix: string,
  code: string,
  versions: {
    algoVersion: number
    stocks: number
    themes: number
  },
): string {
  return `${prefix}:${code}:${versions.algoVersion}:${versions.stocks}:${versions.themes}`
}

/**
 * 解析缓存键
 */
export function parseCacheKey(key: string): {
  prefix: string
  code: string
  algoVersion: number
  stocksVersion: number
  themesVersion: number
} | null {
  const parts = key.split(':')
  if (parts.length !== 5) return null

  return {
    prefix: parts[0],
    code: parts[1],
    algoVersion: parseInt(parts[2]),
    stocksVersion: parseInt(parts[3]),
    themesVersion: parseInt(parts[4]),
  }
}

/**
 * 计算P95
 */
export function calculateP95(values: number[]): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const index = Math.floor(sorted.length * 0.95)
  return sorted[index] || 0
}

/**
 * 计算稳定性分数
 */
export function calculateStability(errorRate: number, avgTime: number): number {
  // 稳定性 = 100 - 错误率*100 - 时间惩罚
  const errorPenalty = errorRate * 100
  const timePenalty = Math.min(50, avgTime / 10)
  return Math.max(0, 100 - errorPenalty - timePenalty)
}

/**
 * 哈希函数（用于AB测试流量分割）
 */
export function hashCode(str: string): number {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i)
    hash |= 0
  }
  return Math.abs(hash)
}

/**
 * 分块数组
 */
export function chunkArray<T>(array: T[], size: number): T[][] {
  const chunks: T[][] = []
  for (let i = 0; i < array.length; i += size) {
    chunks.push(array.slice(i, i + size))
  }
  return chunks
}

/**
 * 安全执行函数（带错误处理）
 */
export async function safeExecute<T>(
  fn: () => Promise<T>,
  defaultValue: T,
  onError?: (error: Error) => void,
): Promise<T> {
  try {
    return await fn()
  } catch (error) {
    onError?.(error as Error)
    return defaultValue
  }
}

/**
 * 计算置信度（简化版）
 */
export function calculateConfidence(
  controlSuccess: number,
  testSuccess: number,
  sampleSize: number,
): number {
  if (sampleSize < 30) return 0 // 样本太小

  const controlRate = controlSuccess / sampleSize
  const testRate = testSuccess / sampleSize
  const diff = Math.abs(testRate - controlRate)

  // 简单的置信度计算
  return Math.min(100, (diff * 100 * Math.sqrt(sampleSize)) / 10)
}

/**
 * 获取预热目标股票（安全版）
 */
export async function getWarmupTargets(
  type: string,
  themeFacade?: any,
  dragonAnalyzer?: any,
  dataLayer?: any,
): Promise<Stock[]> {
  // 确保数据层存在
  const stocks = dataLayer?.getStocks?.() || []
  if (!Array.isArray(stocks)) {
    console.warn('[algorithmHelpers] stocks 不是数组')
    return []
  }

  try {
    switch (type) {
      case 'hotThemes': {
        const hotThemes = themeFacade?.getHotThemesCompat?.(5) || []
        if (!Array.isArray(hotThemes)) {
          console.warn('[algorithmHelpers] hotThemes 不是数组:', hotThemes)
          return []
        }

        const codes = new Set<string>()

        for (const theme of hotThemes) {
          if (!theme?.id) continue

          try {
            const themeStocks = themeFacade?.getThemeStocksCompat?.(theme.id, 10)

            // 安全地获取股票数组
            let stocksArray: any[] = []
            if (themeStocks) {
              if (Array.isArray(themeStocks)) {
                stocksArray = themeStocks
              } else if (themeStocks.stocks && Array.isArray(themeStocks.stocks)) {
                stocksArray = themeStocks.stocks
              }
            }

            stocksArray.forEach((s: any) => {
              if (s?.code) codes.add(s.code)
            })
          } catch (err) {
            console.warn(`[algorithmHelpers] 处理题材 ${theme.name} 失败:`, err)
          }
        }

        return stocks.filter((s) => codes.has(s.code))
      }

      case 'leaders': {
        const leaders = dragonAnalyzer?.getAllLeaders?.() || []
        if (!Array.isArray(leaders)) {
          console.warn('[algorithmHelpers] leaders 不是数组:', leaders)
          return []
        }

        const leaderCodes = new Set(leaders.map((l: any) => l?.code).filter(Boolean))
        return stocks.filter((s) => leaderCodes.has(s.code))
      }

      case 'popularStocks':
        return stocks.filter((s) => s.compRank && s.compRank <= 100).slice(0, 200)

      default:
        return []
    }
  } catch (error) {
    console.error(`[algorithmHelpers] 获取预热目标失败: ${type}`, error)
    return []
  }
}

/**
 * 节流函数
 */
export function throttle<T extends (...args: any[]) => any>(func: T, limit: number): T {
  let inThrottle: boolean
  let lastResult: ReturnType<T>

  return function (this: any, ...args: any[]) {
    if (!inThrottle) {
      inThrottle = true
      lastResult = func.apply(this, args)
      setTimeout(() => (inThrottle = false), limit)
    }
    return lastResult
  } as T
}

/**
 * 防抖函数
 */
export function debounce<T extends (...args: any[]) => any>(func: T, delay: number): T {
  let timeout: NodeJS.Timeout

  return function (this: any, ...args: any[]) {
    clearTimeout(timeout)
    timeout = setTimeout(() => func.apply(this, args), delay)
  } as T
}
