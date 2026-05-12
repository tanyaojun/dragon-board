import { debugLog } from '@/utils/logger'
import { apiService } from './apiService'
// src/services/StockCodeManager.ts
/**
 * 股票代码管理器
 * 负责从 QuantBoard stock_names API 加载全市场股票代码
 */

export interface StockCodeInfo {
  code: string // 股票代码：000001
  name: string // 股票名称：平安银行
  market: 'SH' | 'SZ' | 'BJ' // 市场
  type: 'stock' | 'index' | 'etf' | 'bond' // 类型
  pinyin?: string // 拼音首字母（可选，用于搜索）
  pinyinInitials?: string
  pinyinFull?: string
  active?: boolean
}

// 加载状态
type LoadingState = 'idle' | 'loading' | 'success' | 'error'
type StockCodeCacheSource = 'mongodb'
type StockCodeDataSource = 'api' | 'cache' | 'manual' | null

interface StockCodeCachePayload {
  version: string
  source: StockCodeCacheSource
  stale: boolean
  timestamp: number
  codes: StockCodeInfo[]
}

interface StockNamesApiResponse {
  ok?: boolean
  source?: string
  version?: string
  stocks?: unknown
}

export class StockCodeManagerService {
  private static instance: StockCodeManagerService
  private stockCodes: StockCodeInfo[] = []
  private codeStrings: string[] = []
  private stockMap: Map<string, StockCodeInfo> = new Map()

  private loadingState: LoadingState = 'idle'
  private loadingPromise: Promise<boolean> | null = null
  private lastUpdate: number = 0
  private error: Error | null = null
  private dataSource: StockCodeDataSource = null
  private stale = false
  private version = ''

  // 配置
  private readonly CACHE_KEY = 'stock_codes_cache'
  private readonly CACHE_VERSION = 'stock_names.v1'
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
    const results = this.stockCodes
      .map((stock) => ({ stock, rank: this.getSearchRank(stock, lowerKeyword) }))
      .filter((item): item is { stock: StockCodeInfo; rank: number } => item.rank !== null)
      .sort((a, b) => a.rank - b.rank || a.stock.code.localeCompare(b.stock.code))

    return results.slice(0, limit).map((item) => item.stock)
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
    this.loadingPromise = this.loadFromApi()
      .then((success) => {
        if (!success) {
          return this.loadFromCache(true)
        }
        return true
      })
      .then((success) => {
        if (success) {
          this.loadingState = 'success'
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
  private async loadFromCache(markStale: boolean): Promise<boolean> {
    try {
      const cached = localStorage.getItem(this.CACHE_KEY)
      if (!cached) return false

      const data = JSON.parse(cached) as Partial<StockCodeCachePayload>
      if (data.source !== 'mongodb' || data.version !== this.CACHE_VERSION) {
        return false
      }
      if (!Array.isArray(data.codes)) {
        return false
      }

      // 检查是否过期
      if (Date.now() - Number(data.timestamp || 0) > this.CACHE_TTL) {
        debugLog('[StockCodeManager] 缓存已过期')
        return false
      }

      this.applyStockData(data.codes)
      this.dataSource = 'cache'
      this.stale = markStale || Boolean(data.stale)
      this.version = data.version
      this.lastUpdate = Number(data.timestamp || Date.now())
      if (this.stale) {
        this.saveToCache(true)
      }

      debugLog(`[StockCodeManager] 从缓存加载: ${this.codeStrings.length}只`)
      return true
    } catch (error) {
      console.warn('[StockCodeManager] 缓存加载失败:', error)
      return false
    }
  }

  private async loadFromApi(): Promise<boolean> {
    debugLog('[StockCodeManager] 从 QuantBoard API 加载股票代码...')

    try {
      const response = (await apiService.listStockNames()) as StockNamesApiResponse

      if (!Array.isArray(response.stocks)) {
        throw new Error('stock_names API 返回数据不是数组')
      }

      this.applyStockData(response.stocks)
      this.lastUpdate = Date.now()
      this.loadingState = 'success'
      this.dataSource = 'api'
      this.stale = false
      this.version = response.version || this.CACHE_VERSION
      this.error = null
      this.saveToCache(false)

      debugLog(`[StockCodeManager] 加载成功: ${this.codeStrings.length}只`)
      return true
    } catch (error) {
      console.error('[StockCodeManager] 加载失败:', error)
      this.error = error instanceof Error ? error : new Error(String(error))
      return false
    }
  }

  // 添加一个手动设置数据的方法（用于调试）
  public setStockData(data: any[]) {
    this.applyStockData(data)
    this.lastUpdate = Date.now()
    this.loadingState = 'success'
    this.dataSource = 'manual'
    this.stale = false
    this.version = this.CACHE_VERSION
    debugLog(`[StockCodeManager] 手动设置数据: ${this.codeStrings.length}只`)
  }

  /**
   * 保存到缓存
   */
  private saveToCache(stale: boolean): void {
    try {
      const cacheData: StockCodeCachePayload = {
        version: this.version || this.CACHE_VERSION,
        source: 'mongodb',
        stale,
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
    this.dataSource = null
    this.stale = false
    this.version = ''
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

  private applyStockData(data: unknown[]): void {
    this.stockCodes = data
      .map((item: any) => this.normalizeStockInfo(item))
      .filter((item): item is StockCodeInfo => Boolean(item && item.code && item.code !== '000000'))
    this.codeStrings = this.stockCodes.map((s) => s.code)
    this.stockMap = new Map(this.stockCodes.map((s) => [s.code, s]))
  }

  private normalizeStockInfo(item: any): StockCodeInfo | null {
    const code = this.normalizeCode(item?.code)
    if (!code) return null
    const pinyinInitials = String(item?.pinyinInitials || item?.pinyin || '').trim().toLowerCase()
    const pinyinFull = String(item?.pinyinFull || '').trim().toLowerCase()
    return {
      code,
      name: String(item?.name || '未知').trim().replace(/\s+/g, ''),
      market: item?.market || this.determineMarket(code),
      type: item?.type || 'stock',
      pinyin: pinyinInitials,
      pinyinInitials,
      pinyinFull,
      active: item?.active !== false,
    }
  }

  private normalizeCode(code: unknown): string {
    const value = String(code || '').trim()
    if (!value) return ''
    return /^\d+$/.test(value) ? value.padStart(6, '0') : value
  }

  private getSearchRank(stock: StockCodeInfo, keyword: string): number | null {
    const code = stock.code.toLowerCase()
    const name = stock.name.toLowerCase()
    const nameNormalized = name.replace(/\s+/g, '')
    const pinyinInitials = (stock.pinyinInitials || stock.pinyin || '').toLowerCase()
    const pinyinFull = (stock.pinyinFull || '').toLowerCase()

    if (code === keyword) return 0
    if (code.startsWith(keyword)) return 1
    if (name.startsWith(keyword) || nameNormalized.startsWith(keyword)) return 2
    if (name.includes(keyword) || nameNormalized.includes(keyword)) return 3
    if (pinyinInitials.startsWith(keyword)) return 4
    if (pinyinFull.startsWith(keyword)) return 5
    return null
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
   * 获取加载状态
   */
  getStatus() {
    return {
      state: this.loadingState,
      count: this.codeStrings.length,
      lastUpdate: this.lastUpdate,
      source: this.dataSource,
      stale: this.stale,
      version: this.version || undefined,
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
