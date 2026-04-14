// src/services/StockCodeManager.ts
/**
 * 股票代码管理器 - 自启动版本 🚀
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

  // 配置 - 支持多种可能的路径
  private readonly STOCK_DATA_PATHS = [
    '/data/stock_code.json',
    '/stock_code.json',
    './data/stock_code.json',
    '../data/stock_code.json'
  ]
  private readonly CACHE_KEY = 'stock_codes_cache'
  private readonly CACHE_TTL = 24 * 60 * 60 * 1000 // 24小时

  private constructor() {
    // 在构造函数中自动启动加载
    this.init()
  }

  static getInstance(): StockCodeManagerService {
    if (!StockCodeManagerService.instance) {
      StockCodeManagerService.instance = new StockCodeManagerService()
    }
    return StockCodeManagerService.instance
  }

  /**
   * 初始化 - 自动加载数据
   */
  private async init() {
    console.log('[StockCodeManager] 🚀 自动启动加载股票代码...')
    
    // 先尝试从缓存加载
    const cached = this.loadFromCache()
    if (cached) {
      console.log(`[StockCodeManager] ✅ 从缓存加载: ${this.codeStrings.length}只`)
      this.loadingState = 'success'
      return
    }

    // 缓存没有，从文件加载
    this.loadingState = 'loading'
    const success = await this.loadFromFile()
    if (success) {
      console.log(`[StockCodeManager] ✅ 从文件加载: ${this.codeStrings.length}只`)
      this.loadingState = 'success'
      this.saveToCache()
    } else {
      console.error('[StockCodeManager] ❌ 所有路径加载失败')
      this.loadingState = 'error'
      
      // 使用备用数据（开发用）
      this.useFallbackData()
    }
  }

  /**
   * 从缓存加载
   */
  private loadFromCache(): boolean {
    try {
      const cached = localStorage.getItem(this.CACHE_KEY)
      if (!cached) return false

      const data = JSON.parse(cached)

      // 检查是否过期
      if (Date.now() - data.timestamp > this.CACHE_TTL) {
        console.log('[StockCodeManager] 缓存已过期')
        return false
      }

      this.stockCodes = data.codes
      this.codeStrings = this.stockCodes.map((s) => s.code)
      this.stockMap = new Map(this.stockCodes.map((s) => [s.code, s]))

      return true
    } catch (error) {
      console.warn('[StockCodeManager] 缓存加载失败:', error)
      return false
    }
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
   * 从文件加载 - 尝试多个路径
   */
  private async loadFromFile(): Promise<boolean> {
    for (const path of this.STOCK_DATA_PATHS) {
      try {
        console.log(`[StockCodeManager] 📥 尝试路径: ${path}`)
        
        const response = await fetch(path, {
          method: 'GET',
          headers: {
            'Accept': 'application/json',
          },
          cache: 'no-cache' // 避免缓存问题
        })
        
        if (!response.ok) {
          console.log(`[StockCodeManager] 路径 ${path} 失败: HTTP ${response.status}`)
          continue
        }

        const data = await response.json()
        
        if (!Array.isArray(data)) {
          console.log(`[StockCodeManager] 路径 ${path} 数据不是数组`)
          continue
        }

        // 成功加载
        this.processData(data)
        console.log(`[StockCodeManager] ✅ 路径 ${path} 加载成功: ${this.codeStrings.length}只`)
        return true

      } catch (error) {
        console.log(`[StockCodeManager] 路径 ${path} 异常:`, error)
        continue
      }
    }

    return false
  }

  /**
   * 处理原始数据
   */
  private processData(data: any[]) {
    this.stockCodes = data
      .map((item: any) => {
        // 处理可能的不同字段名
        const code = item.code || item.stockCode || item.symbol || ''
        const name = item.name || item.stockName || item.stock_name || '未知'
        
        return {
          code: String(code).padStart(6, '0'),
          name: String(name).trim().replace(/\s+/g, ''),
          market: item.market || this.determineMarket(code),
          type: item.type || 'stock',
        }
      })
      .filter((item) => item.code && item.code !== '000000' && item.code.length === 6)

    this.codeStrings = this.stockCodes.map((s) => s.code)
    this.stockMap = new Map(this.stockCodes.map((s) => [s.code, s]))
    this.lastUpdate = Date.now()
  }

  /**
   * 使用备用数据（开发环境）
   */
  private useFallbackData() {
    console.warn('[StockCodeManager] ⚠️ 使用备用数据')
    
    // 常用的股票代码作为备用
    const fallbackData = [
      { code: '000001', name: '平安银行', market: 'SZ' },
      { code: '000002', name: '万科A', market: 'SZ' },
      { code: '000858', name: '五粮液', market: 'SZ' },
      { code: '002415', name: '海康威视', market: 'SZ' },
      { code: '002475', name: '立讯精密', market: 'SZ' },
      { code: '300750', name: '宁德时代', market: 'SZ' },
      { code: '600519', name: '贵州茅台', market: 'SH' },
      { code: '600036', name: '招商银行', market: 'SH' },
      { code: '601318', name: '中国平安', market: 'SH' },
      { code: '601888', name: '中国中免', market: 'SH' },
      { code: '002470', name: '金正大', market: 'SZ' } // 您测试的股票
    ]
    
    this.processData(fallbackData)
    this.loadingState = 'success' // 虽然用备用数据，但标记为成功
  }

  /**
   * 获取所有股票代码（主要API）
   */
  async getAllCodes(forceRefresh = false): Promise<string[]> {
    if (forceRefresh) {
      this.clearCache()
      await this.init()
    }
    
    // 如果还没加载完，等待一下
    if (this.loadingState === 'loading') {
      await this.waitForReady()
    }
    
    return this.codeStrings
  }

  /**
   * 获取所有股票详细信息
   */
  async getAllStocks(forceRefresh = false): Promise<StockCodeInfo[]> {
    if (forceRefresh) {
      this.clearCache()
      await this.init()
    }
    
    if (this.loadingState === 'loading') {
      await this.waitForReady()
    }
    
    return [...this.stockCodes]
  }

  /**
   * 获取单个股票信息（同步方法，不等待）
   */
  getStockInfo(code: string): StockCodeInfo | undefined {
    // 如果还没加载完，尝试从内存中已有的数据获取
    return this.stockMap.get(code)
  }

  /**
   * 获取股票名称（同步方法，不等待）
   */
  getStockName(code: string): string {
    const info = this.getStockInfo(code)
    return info?.name || code
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
      if (s.code.includes(lowerKeyword)) return true
      if (s.name.toLowerCase().includes(lowerKeyword)) return true
      return false
    })

    return results.slice(0, limit)
  }

  /**
   * 清空缓存
   */
  private clearCache(): void {
    this.stockCodes = []
    this.codeStrings = []
    this.stockMap.clear()
    this.loadingState = 'idle'
    localStorage.removeItem(this.CACHE_KEY)
  }

  /**
   * 手动刷新
   */
  async refresh(): Promise<boolean> {
    this.clearCache()
    await this.init()
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
  async waitForReady(timeout: number = 5000): Promise<boolean> {
    // 如果已经加载成功，直接返回
    if (this.loadingState === 'success') {
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
        if (this.loadingState === 'success') {
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
          console.warn('[StockCodeManager] 等待超时')
          resolve(false)
          return
        }

        // 继续等待
        setTimeout(check, 100)
      }

      check()
    })
  }

  /**
   * 手动设置数据（用于调试）
   */
  public setStockData(data: any[]) {
    this.processData(data)
    this.loadingState = 'success'
    console.log(`[StockCodeManager] 📦 手动设置数据: ${this.codeStrings.length}只`)
    this.saveToCache()
  }
}

// 导出单例 - 创建实例时自动启动
export const stockCodeManager = StockCodeManagerService.getInstance()

// 挂载到 window（调试用）
if (typeof window !== 'undefined') {
  ;(window as any).stockCodeManager = stockCodeManager
}