import { debugLog } from '@/utils/logger'
// src/services/StockCodeManager.ts
/**
 * 股票代码管理器 - 龙王号航海图 🗺️
 * 负责从 public/data/stock_code.json 加载全市场股票代码
 */

export interface StockCodeInfo {
  code: string // 股票代码：000001
  name: string // 股票名称：平安银行
  market: 'SH' | 'SZ' | 'BJ' // 市场
  type: 'stock' | 'index' | 'etf' | 'bond' // 类型
  pinyin?: string // 拼音首字母（可选，用于搜索）
}

// 加载状态
type LoadingState = 'idle' | 'loading' | 'success' | 'error'

export class StockCodeManagerService {
  private static instance: StockCodeManagerService
  private stockCodes: StockCodeInfo[] = []
  private codeStrings: string[] = []
  private stockMap: Map<string, StockCodeInfo> = new Map()

  private loadingState: LoadingState = 'idle'
  private loadingPromise: Promise<boolean> | null = null
  private lastUpdate: number = 0
  private error: Error | null = null

  // 配置
  private readonly STOCK_DATA_PATH = '/data/stock_code.json'
  private readonly CACHE_KEY = 'stock_codes_cache'
  private readonly CACHE_TTL = 24 * 60 * 60 * 1000 // 24小时

  private constructor() {}

  static getInstance(): StockCodeManagerService {
    if (!StockCodeManagerService.instance) {
      StockCodeManagerService.instance = new StockCodeManagerService()
    }
    return StockCodeManagerService.instance
  }

  /**
   * 获取所有股票代码（主要API）
   */
  async getAllCodes(forceRefresh = false): Promise<string[]> {
    if (forceRefresh) {
      this.clearCache()
    }

    await this.ensureLoaded()
    return this.codeStrings
  }

  /**
   * 获取所有股票详细信息
   */
  async getAllStocks(forceRefresh = false): Promise<StockCodeInfo[]> {
    if (forceRefresh) {
      this.clearCache()
    }

    await this.ensureLoaded()
    return [...this.stockCodes]
  }

  /**
   * 获取单个股票信息
   */
  getStockInfo(code: string): StockCodeInfo | undefined {
    return this.stockMap.get(code)
  }

  /**
   * 获取股票名称
   */
  getStockName(code: string): string {
    return this.stockMap.get(code)?.name || code
  }

  /**
   * 获取股票总数
   */
  getCount(): number {
    return this.codeStrings.length
  }

  /**
   * 按市场分类获取代码
   */
  getCodesByMarket(market: 'SH' | 'SZ' | 'BJ'): string[] {
    return this.stockCodes.filter((s) => s.market === market).map((s) => s.code)
  }

  /**
   * 搜索股票（支持代码、名称、拼音）
   */
  search(keyword: string, limit: number = 50): StockCodeInfo[] {
    if (!keyword || !this.stockCodes.length) return []

    const lowerKeyword = keyword.toLowerCase().trim()

    // 如果是纯数字，优先按代码匹配
    if (/^\d+$/.test(lowerKeyword)) {
      const exactMatches = this.stockCodes.filter((s) => s.code.startsWith(lowerKeyword))
      if (exactMatches.length > 0) {
        return exactMatches.slice(0, limit)
      }
    }

    // 按名称匹配
    const results = this.stockCodes.filter((s) => {
      // 代码匹配
      if (s.code.includes(lowerKeyword)) return true

      // 名称匹配
      if (s.name.toLowerCase().includes(lowerKeyword)) return true

      // 拼音匹配（如果有）
      if (s.pinyin && s.pinyin.includes(lowerKeyword)) return true

      return false
    })

    return results.slice(0, limit)
  }

  /**
   * 确保数据已加载
   */
  private async ensureLoaded(): Promise<void> {
    // 如果已经加载成功，直接返回
    if (this.loadingState === 'success' && this.stockCodes.length > 0) {
      return
    }

    // 如果正在加载，返回已有的Promise
    if (this.loadingPromise) {
      await this.loadingPromise
      return
    }

    // 开始加载
    this.loadingState = 'loading'
    this.loadingPromise = this.loadFromCache()
      .then((success) => {
        if (!success) {
          return this.loadFromFile()
        }
        return true
      })
      .then((success) => {
        if (success) {
          this.loadingState = 'success'
          this.buildSearchIndex()
        } else {
          this.loadingState = 'error'
          this.error = new Error('所有数据源都加载失败')
        }
        return success
      })
      .finally(() => {
        this.loadingPromise = null
      })

    await this.loadingPromise
  }

  /**
   * 从缓存加载
   */
  private async loadFromCache(): Promise<boolean> {
    try {
      const cached = localStorage.getItem(this.CACHE_KEY)
      if (!cached) return false

      const data = JSON.parse(cached)

      // 检查是否过期
      if (Date.now() - data.timestamp > this.CACHE_TTL) {
        debugLog('[StockCodeManager] 缓存已过期')
        return false
      }

      this.stockCodes = data.codes
      this.codeStrings = this.stockCodes.map((s) => s.code)
      this.stockMap = new Map(this.stockCodes.map((s) => [s.code, s]))

      debugLog(`[StockCodeManager] ✅ 从缓存加载: ${this.codeStrings.length}只`)
      return true
    } catch (error) {
      console.warn('[StockCodeManager] 缓存加载失败:', error)
      return false
    }
  }

  private async loadFromFile(): Promise<boolean> {
    debugLog('[StockCodeManager] 📥 从文件加载股票代码...')

    try {
      // 设置一个内部超时
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 5000)

      const response = await fetch('/data/stock_code.json', {
        signal: controller.signal,
      }).finally(() => clearTimeout(timeoutId))

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data = await response.json()

      if (!Array.isArray(data)) {
        throw new Error('数据不是数组')
      }

      // 处理数据
      this.stockCodes = data
        .map((item: any) => ({
          code: String(item.code || '').padStart(6, '0'),
          name: (item.name || '未知').trim().replace(/\s+/g, ''),
          market: item.market || this.determineMarket(item.code),
          type: item.type || 'stock',
        }))
        .filter((item) => item.code && item.code !== '000000')

      this.codeStrings = this.stockCodes.map((s) => s.code)
      this.stockMap = new Map(this.stockCodes.map((s) => [s.code, s]))
      this.lastUpdate = Date.now()
      this.loadingState = 'success'

      debugLog(`[StockCodeManager] ✅ 加载成功: ${this.codeStrings.length}只`)
      return true
    } catch (error) {
      console.error('[StockCodeManager] 加载失败:', error)
      this.loadingState = 'error'
      this.error = error instanceof Error ? error : new Error(String(error))

      // 即使失败，也设置一些空数据，避免 undefined
      this.stockCodes = []
      this.codeStrings = []
      this.stockMap.clear()

      return false
    }
  }

  // 添加一个手动设置数据的方法（用于调试）
  public setStockData(data: any[]) {
    this.stockCodes = data.map((item: any) => ({
      code: String(item.code).padStart(6, '0'),
      name: item.name.trim(),
      market: item.market,
      type: item.type,
    }))
    this.codeStrings = this.stockCodes.map((s) => s.code)
    this.stockMap = new Map(this.stockCodes.map((s) => [s.code, s]))
    this.lastUpdate = Date.now()
    this.loadingState = 'success'
    debugLog(`[StockCodeManager] 📦 手动设置数据: ${this.codeStrings.length}只`)
  }

  /**
   * 保存到缓存
   */
  private saveToCache(): void {
    try {
      const cacheData = {
        codes: this.stockCodes,
        timestamp: Date.now(),
      }
      localStorage.setItem(this.CACHE_KEY, JSON.stringify(cacheData))
    } catch (error) {
      console.warn('[StockCodeManager] 缓存保存失败:', error)
    }
  }

  /**
   * 清空缓存
   */
  private clearCache(): void {
    this.stockCodes = []
    this.codeStrings = []
    this.stockMap.clear()
    this.loadingState = 'idle'
    this.loadingPromise = null
    localStorage.removeItem(this.CACHE_KEY)
  }

  /**
   * 手动刷新
   */
  async refresh(): Promise<boolean> {
    this.clearCache()
    await this.ensureLoaded()
    return this.loadingState === 'success'
  }

  /**
   * 判断市场
   */
  private determineMarket(code: string): 'SH' | 'SZ' | 'BJ' {
    const codeStr = String(code).padStart(6, '0')
    if (codeStr.startsWith('6')) return 'SH'
    if (codeStr.startsWith('0') || codeStr.startsWith('3')) return 'SZ'
    if (codeStr.startsWith('8') || codeStr.startsWith('4')) return 'BJ'
    return 'SH' // 默认
  }

  /**
   * 生成拼音首字母（可选，用于搜索）
   */
  private generatePinyin(name: string): string | undefined {
    // 如果有拼音库可以实现，否则返回undefined
    return undefined
  }

  /**
   * 构建搜索索引（可选）
   */
  private buildSearchIndex(): void {
    // 如果有需要，可以在这里构建拼音索引
  }

  /**
   * 获取加载状态
   */
  getStatus() {
    return {
      state: this.loadingState,
      count: this.codeStrings.length,
      lastUpdate: this.lastUpdate,
      error: this.error?.message,
    }
  }

  /**
   * 检查是否就绪
   */
  isReady(): boolean {
    return this.loadingState === 'success' && this.stockCodes.length > 0
  }

  /**
   * 等待就绪
   */
  async waitForReady(timeout: number = 3000): Promise<boolean> {
    // 如果已经加载成功，直接返回
    if (this.loadingState === 'success' && this.stockCodes.length > 0) {
      return true
    }

    // 如果已经失败，直接返回 false
    if (this.loadingState === 'error') {
      return false
    }

    const start = Date.now()

    return new Promise((resolve) => {
      const check = () => {
        // 成功
        if (this.loadingState === 'success' && this.stockCodes.length > 0) {
          resolve(true)
          return
        }

        // 失败
        if (this.loadingState === 'error') {
          resolve(false)
          return
        }

        // 超时
        if (Date.now() - start > timeout) {
          console.warn('[StockCodeManager] 等待超时，强制返回')
          // 即使超时也 resolve(false)，不要 reject
          resolve(false)
          return
        }

        // 继续等待
        setTimeout(check, 100)
      }

      check()
    })
  }
}

// 导出单例
export const stockCodeManager = StockCodeManagerService.getInstance()

// 挂载到 window（调试用）
if (typeof window !== 'undefined') {
  ;(window as any).stockCodeManager = stockCodeManager
}
