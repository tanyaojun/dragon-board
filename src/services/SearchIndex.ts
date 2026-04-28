// src/services/SearchIndex.ts

import { PinyinUtils } from '../utils/pinyin'
import { dataLayer } from './DataLayer'

interface IndexEntry {
  scores: Map<string, number> // code -> score
}

export interface SearchResult {
  stock: {
    code: string
    name: string
    price: number
    change: number
    themes?: any[]
    isSectorLeader?: boolean
    leaderLevel?: string
    _index?: number
  }
  score: number
  matchType: 'exact' | 'prefix' | 'contains'
}

export class SearchIndex {
  private static index = new Map<string, IndexEntry>()
  private static stockMap = new Map<string, any>()
  private static built = false
  private static version = 0 // 用于缓存失效

  /**
   * 构建索引 - 支持传入数据或从 store 获取
   */
  static build(stocks?: any[]): boolean {
    let stockData = stocks

    if (!stockData) {
      stockData = dataLayer.getStocks()
    }

    if (!stockData || stockData.length === 0) {
      return false
    }

    try {
      this.index.clear()
      this.stockMap.clear()

      stockData.forEach((stock, idx) => {
        const code = String(stock?.code || '').trim()
        const name = String(stock?.name || '').trim()
        if (!code) return

        // 只存储必要字段，减少内存
        this.stockMap.set(code, {
          code,
          name,
          price: stock.price,
          change: stock.change,
          themes: stock.themes?.slice(0, 3),
          isSectorLeader: stock.isSectorLeader,
          leaderLevel: stock.leaderLevel,
          _index: idx,
        })

        // 1. 代码索引（最高优先级）
        this.addToIndex(code.toUpperCase(), code, 100)

        if (name) {
          const upperName = name.toUpperCase()

          // 2. 名称全拼（第二优先级）
          this.addToIndex(upperName, code, 95)

          // 3. 拼音首字母（第三优先级）
          const pinyin = PinyinUtils.getPinyinInitials(name)
          if (pinyin) {
            this.addToIndex(pinyin.toUpperCase(), code, 90)
          }

          // 4. 名称前缀匹配（只存储长度为2和3的前缀，减少索引数量）
          if (upperName.length >= 2) {
            this.addToIndex(upperName.slice(0, 2), code, 85)
          }
          if (upperName.length >= 3) {
            this.addToIndex(upperName.slice(0, 3), code, 80)
          }
        }
      })

      this.built = true
      this.version++

      return true
    } catch (error) {
      console.error('[SearchIndex] 构建失败:', error)
      return false
    }
  }

  private static addToIndex(keyword: string, code: string, score: number): void {
    if (!keyword || keyword.length < 1) return

    let entry = this.index.get(keyword)
    if (!entry) {
      entry = { scores: new Map() }
      this.index.set(keyword, entry)
    }

    const existingScore = entry.scores.get(code)
    if (!existingScore || existingScore < score) {
      entry.scores.set(code, score)
    }
  }

  static search(keyword: string, limit: number = 50): SearchResult[] {
    if (!keyword) return []
    const currentStocks = dataLayer.getStocks()
    if ((!this.built || this.stockMap.size !== currentStocks.length) && !this.build(currentStocks)) {
      return []
    }

    try {
      const results: SearchResult[] = []
      const seen = new Set<string>()
      const upperKeyword = keyword.toUpperCase().trim()

      if (upperKeyword.length === 0) return []

      // 1. 精确匹配代码（最高优先级）
      const exactEntry = this.index.get(upperKeyword)
      if (exactEntry) {
        exactEntry.scores.forEach((score, code) => {
          if (!seen.has(code)) {
            seen.add(code)
            const stock = this.stockMap.get(code)
            if (stock) {
              results.push({ stock, score, matchType: 'exact' })
            }
          }
        })
      }

      // 2. 前缀匹配（只搜索长度 >= 2 的关键词）
      if (upperKeyword.length >= 2) {
        for (const [key, entry] of this.index.entries()) {
          if (key.startsWith(upperKeyword) && key !== upperKeyword) {
            entry.scores.forEach((score, code) => {
              if (!seen.has(code) && results.length < limit) {
                seen.add(code)
                const stock = this.stockMap.get(code)
                if (stock) {
                  results.push({ stock, score: score - 5, matchType: 'prefix' })
                }
              }
            })
          }
          if (results.length >= limit) break
        }
      }

      // 3. 包含匹配（限制数量）
      if (results.length < limit) {
        for (const [key, entry] of this.index.entries()) {
          if (key.includes(upperKeyword) && !key.startsWith(upperKeyword)) {
            entry.scores.forEach((score, code) => {
              if (!seen.has(code) && results.length < limit) {
                seen.add(code)
                const stock = this.stockMap.get(code)
                if (stock) {
                  results.push({ stock, score: score - 10, matchType: 'contains' })
                }
              }
            })
          }
          if (results.length >= limit) break
        }
      }

      // 按得分排序
      return results.sort((a, b) => b.score - a.score)
    } catch (error) {
      console.error('[SearchIndex] 搜索失败:', error)
      return []
    }
  }

  static rebuild(stocks?: any[]): boolean {
    this.built = false
    return this.build(stocks)
  }

  static getStock(code: string): any {
    return this.stockMap.get(code)
  }

  static getStats() {
    return {
      indexSize: this.index.size,
      stockCount: this.stockMap.size,
      built: this.built,
      version: this.version,
      memoryEstimate: this.estimateMemoryUsage(),
    }
  }

  private static estimateMemoryUsage(): string {
    const indexSize = this.index.size * 100
    const stockSize = this.stockMap.size * 200
    const total = indexSize + stockSize

    if (total < 1024) return total + 'B'
    if (total < 1024 * 1024) return (total / 1024).toFixed(1) + 'KB'
    return (total / (1024 * 1024)).toFixed(1) + 'MB'
  }

  static clear(): void {
    this.index.clear()
    this.stockMap.clear()
    this.built = false
    this.version = 0
  }
}
