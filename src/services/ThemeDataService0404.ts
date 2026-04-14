// src/services/ThemeDataService.ts
/**
 * 题材数据服务 - 提供静态基础数据 + API更新能力 + IndexedDB持久化
 */

import { apiService } from './apiService'
import { dataLayer } from './DataLayer'

declare global {
  interface Window {
    KPL_THEME_DATA?: Array<{
      ID: string
      Name: string
      ZSCode?: string
      LimitUpCount?: number
      ChangePercent?: number
    }>
  }
}

export interface ThemeBase {
  id: string
  name: string
  zsCode?: string
}

export interface ThemeMapping {
  id: string
  name: string
  stocks: string[]
  zsCode?: string
}

export interface ThemeMappingData {
  version: string
  lastUpdate: string
  totalThemes: number
  themes: ThemeMapping[]
}

export interface KPLThemeItem {
  id: string
  name: string
  zsCode?: string
}

class ThemeDataService {
  private static instance: ThemeDataService

  private themes: Map<string, ThemeBase> = new Map()
  private themeStocks: Map<string, string[]> = new Map()
  private stockThemes: Map<string, string[]> = new Map()

  private loaded: boolean = false
  private loadingPromise: Promise<boolean> | null = null
  private lastUpdateTime: string | null = null
  private kplThemes: KPLThemeItem[] = []

  // IndexedDB 配置
  private readonly DB_NAME = 'ThemeDataDB'
  private readonly DB_VERSION = 1
  private readonly STORE_NAME = 'theme_mapping'
  private db: IDBDatabase | null = null

  private updateTimer: ReturnType<typeof setInterval> | null = null

  private readonly UPDATE_INTERVAL = 2 * 60 * 60 * 1000 // 2小时

  private constructor() {}

  static getInstance(): ThemeDataService {
    if (!ThemeDataService.instance) {
      ThemeDataService.instance = new ThemeDataService()
    }
    return ThemeDataService.instance
  }

  /**
   * 初始化 IndexedDB
   */
  private async initDB(): Promise<IDBDatabase> {
    if (this.db) return this.db

    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.DB_NAME, this.DB_VERSION)

      request.onerror = () => {
        console.error('[ThemeDataService] IndexedDB 打开失败:', request.error)
        reject(request.error)
      }

      request.onsuccess = () => {
        this.db = request.result
        console.log('[ThemeDataService] IndexedDB 连接成功')
        resolve(this.db)
      }

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result
        if (!db.objectStoreNames.contains(this.STORE_NAME)) {
          const store = db.createObjectStore(this.STORE_NAME, { keyPath: 'key' })
          store.createIndex('lastUpdate', 'lastUpdate', { unique: false })
          console.log('[ThemeDataService] IndexedDB 表创建成功')
        }
      }
    })
  }

  private async saveToIndexedDB(data: ThemeMappingData): Promise<void> {
    try {
      const db = await this.initDB()
      const transaction = db.transaction([this.STORE_NAME], 'readwrite')
      const store = transaction.objectStore(this.STORE_NAME)

      store.put({
        key: 'theme_data', // ✅ 修改为 theme_data
        data: data,
        lastUpdate: data.lastUpdate,
        savedAt: new Date().toISOString(),
      })

      return new Promise((resolve, reject) => {
        transaction.oncomplete = () => {
          console.log('[ThemeDataService] ✅ 数据已保存到 IndexedDB')
          resolve()
        }
        transaction.onerror = () => {
          reject(transaction.error)
        }
      })
    } catch (error) {
      console.error('[ThemeDataService] 保存到 IndexedDB 失败:', error)
    }
  }

  private async loadFromIndexedDB(): Promise<ThemeMappingData | null> {
    try {
      const db = await this.initDB()

      return new Promise((resolve, reject) => {
        const transaction = db.transaction([this.STORE_NAME], 'readonly')
        const store = transaction.objectStore(this.STORE_NAME)
        const request = store.get('theme_data') // ✅ 修改为 theme_data

        request.onsuccess = () => {
          const result = request.result
          if (result?.data) {
            console.log(
              `[ThemeDataService] 📀 从 IndexedDB 读取数据: 版本=${result.data.version}, 更新于=${result.data.lastUpdate}`,
            )
            resolve(result.data)
          } else {
            resolve(null)
          }
        }

        request.onerror = () => {
          reject(request.error)
        }
      })
    } catch (error) {
      console.error('[ThemeDataService] 从 IndexedDB 读取失败:', error)
      return null
    }
  }

  /**
   * 从 API 获取最新数据（通过批量接口）
   */
  private async fetchFromAPI(): Promise<ThemeMappingData | null> {
    try {
      console.log('[ThemeDataService] 🌐 从 API 获取题材数据...')

      let allThemeIds: string[] = []

      if (this.kplThemes.length > 0) {
        allThemeIds = this.kplThemes.map((t) => t.id)
      } else {
        allThemeIds = Array.from(this.themes.keys())
      }

      if (allThemeIds.length === 0) {
        console.warn('[ThemeDataService] 没有题材 ID，无法更新')
        return null
      }

      // ✅ 使用 Map 去重，key 为题材 ID
      const themesMap = new Map<string, ThemeMapping>()
      const batchSize = 20
      let validCount = 0
      let duplicateCount = 0

      for (let i = 0; i < allThemeIds.length; i += batchSize) {
        const batchIds = allThemeIds.slice(i, i + batchSize)

        const response = await fetch('/api/themes/batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: batchIds }),
        })

        const data = await response.json()

        if (data.results) {
          data.results.forEach((result: any) => {
            if (
              result.data &&
              result.data.ID &&
              result.data.StockList &&
              result.data.StockList.length > 0
            ) {
              const stockCodes = result.data.StockList.map((stock: any) =>
                this.normalizeCode(stock.StockID),
              ).filter((code) => code && code.length === 6)

              if (stockCodes.length > 0) {
                const themeId = result.data.ID

                // ✅ 如果已经存在，可以选择保留其中一个
                if (!themesMap.has(themeId)) {
                  themesMap.set(themeId, {
                    id: themeId,
                    name: result.data.Name,
                    stocks: stockCodes,
                    zsCode: result.data.ZSCode || '',
                  })
                  validCount++
                } else {
                  duplicateCount++
                  console.warn(
                    `[ThemeDataService] 发现重复题材 ID: ${themeId}, 名称: ${result.data.Name} (已存在: ${themesMap.get(themeId)?.name})`,
                  )
                }
              } else {
                console.warn(`[ThemeDataService] 题材 ${result.data.ID} 无有效股票代码，跳过`)
              }
            } else {
              console.warn(`[ThemeDataService] 题材 ${result.id} 无股票数据，跳过`)
            }
          })
        }

        console.log(
          `[ThemeDataService] 进度: ${Math.min(i + batchSize, allThemeIds.length)}/${allThemeIds.length}, 有效: ${validCount}, 重复: ${duplicateCount}`,
        )

        await this.delay(300)
      }

      const allThemes = Array.from(themesMap.values())

      console.log(
        `[ThemeDataService] ✅ API 获取完成: 有效题材=${validCount}, 重复题材=${duplicateCount}, 最终=${allThemes.length}`,
      )

      const mappingData: ThemeMappingData = {
        version: new Date().toISOString(),
        lastUpdate: new Date().toISOString(),
        totalThemes: allThemes.length,
        themes: allThemes,
      }

      return mappingData
    } catch (error) {
      console.error('[ThemeDataService] API 获取失败:', error)
      return null
    }
  }
  /**
   * 规范化股票代码
   */
  private normalizeCode(code: string): string {
    if (!code) return ''
    return String(code).replace(/[^\d]/g, '').padStart(6, '0')
  }

  /**
   * 延迟函数
   */
  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }

  /**
   * 从本地 JSON 文件加载（最终 fallback）
   */
  private async fetchFromLocal(): Promise<ThemeMappingData | null> {
    try {
      const response = await fetch('/data/theme_base_mapping.json')
      if (!response.ok) return null
      const data = await response.json()
      console.log(`[ThemeDataService] 📁 从本地文件加载: ${data.themes?.length || 0}个题材`)
      return data
    } catch (error) {
      console.warn('[ThemeDataService] 本地文件加载失败:', error)
      return null
    }
  }

  /**
   * 从 window.KPL_THEME_DATA 获取题材列表
   */
  private loadKPLThemes(): void {
    if (typeof window !== 'undefined' && window.KPL_THEME_DATA) {
      this.kplThemes = window.KPL_THEME_DATA.map((item) => ({
        id: String(item.ID),
        name: item.Name,
        zsCode: item.ZSCode || '',
      }))
      console.log(`[ThemeDataService] 📋 从 KPL_THEME_DATA 加载: ${this.kplThemes.length}个题材`)
    }
  }

  /**
   * 构建内存映射
   */
  private buildMapping(mappingData: ThemeMappingData): void {
    // 清空现有数据
    this.themes.clear()
    this.themeStocks.clear()
    this.stockThemes.clear()

    // ✅ 使用 Map 去重
    const uniqueThemes = new Map<string, ThemeMapping>()

    mappingData.themes.forEach((theme) => {
      if (!uniqueThemes.has(theme.id)) {
        uniqueThemes.set(theme.id, theme)
      } else {
        console.warn(`[ThemeDataService] 构建映射时发现重复题材: ${theme.id}, 名称: ${theme.name}`)
      }
    })

    // 构建映射
    uniqueThemes.forEach((theme) => {
      this.themes.set(theme.id, {
        id: theme.id,
        name: theme.name,
        zsCode: theme.zsCode || '',
      })
      this.themeStocks.set(theme.id, theme.stocks || [])
      ;(theme.stocks || []).forEach((code) => {
        if (!this.stockThemes.has(code)) {
          this.stockThemes.set(code, [])
        }
        const themes = this.stockThemes.get(code)!
        if (!themes.includes(theme.id)) {
          themes.push(theme.id)
        }
      })
    })

    this.lastUpdateTime = mappingData.lastUpdate

    console.log(`[ThemeDataService] 构建映射完成: ${uniqueThemes.size} 个唯一题材`)
  }

  /**
   * 同步到 DataLayer
   */
  private syncToDataLayer(): void {
    const byCode = new Map<string, any[]>()
    const byId = new Map<string, any>()

    this.getAllThemes().forEach((theme) => {
      byId.set(theme.id, {
        id: theme.id,
        name: theme.name,
        zsCode: theme.zsCode || '',
        aliases: [],
      })

      const stocks = this.getThemeStocks(theme.id)
      stocks.forEach((code) => {
        if (!byCode.has(code)) {
          byCode.set(code, [])
        }
        byCode.get(code)!.push({
          id: theme.id,
          name: theme.name,
          zsCode: theme.zsCode || '',
        })
      })
    })

    dataLayer.updateThemeBase({
      byCode,
      byId,
      lastUpdate: this.lastUpdateTime || new Date().toISOString(),
    })
  }

  /**
   * 加载数据：优先 IndexedDB → API 更新 → 本地文件 fallback
   */
  async load(): Promise<boolean> {
    if (this.loaded) return true
    if (this.loadingPromise) return this.loadingPromise

    this.loadingPromise = this._load()
    return this.loadingPromise
  }

  private async _load(): Promise<boolean> {
    try {
      console.log('[ThemeDataService] 开始加载题材映射...')

      // 加载 KPL 题材列表
      this.loadKPLThemes()

      // 1. 优先从 IndexedDB 读取
      let mappingData = await this.loadFromIndexedDB()

      if (mappingData) {
        console.log(`[ThemeDataService] 📀 从 IndexedDB 加载: ${mappingData.themes.length}个题材`)
        this.buildMapping(mappingData)
        this.syncToDataLayer()
        this.loaded = true

        // ✅ 不再在加载时检查更新，让定时任务负责
        console.log('[ThemeDataService] 数据加载完成，定时任务将每2小时检查一次更新')
      } else {
        // 2. IndexedDB 没有数据，从本地文件加载（首次加载）
        const localData = await this.fetchFromLocal()
        if (localData) {
          console.log(`[ThemeDataService] 📁 从本地文件加载: ${localData.themes.length}个题材`)
          this.buildMapping(localData)
          this.syncToDataLayer()
          this.loaded = true

          // ✅ 首次加载后，从 API 获取最新数据（异步，不阻塞）
          console.log('[ThemeDataService] 首次加载完成，正在后台同步最新数据...')
          this.checkAndUpdateFromAPI().then((updated) => {
            if (updated) {
              console.log('[ThemeDataService] 首次同步完成')
            }
          })
        } else {
          throw new Error('无法加载题材数据')
        }
      }

      return true
    } catch (error) {
      console.error('[ThemeDataService] 加载失败:', error)
      return false
    } finally {
      this.loadingPromise = null
    }
  }

  /**
   * 检查并更新数据
   */
  async checkAndUpdateFromAPI(): Promise<boolean> {
    try {
      // ✅ 检查数据是否已加载且新鲜（例如 2 小时内）
      if (this.lastUpdateTime) {
        const lastUpdateTime = new Date(this.lastUpdateTime).getTime()
        const twoHours = this.UPDATE_INTERVAL
        const now = Date.now()
        const hoursSinceUpdate = (now - lastUpdateTime) / (60 * 60 * 1000)

        if (now - lastUpdateTime < twoHours) {
          console.log(
            `[ThemeDataService] 数据新鲜 (${hoursSinceUpdate.toFixed(1)}小时前)，跳过更新`,
          )
          return false
        } else {
          console.log(
            `[ThemeDataService] 数据已过时 (${hoursSinceUpdate.toFixed(1)}小时前)，开始更新...`,
          )
        }
      }

      const apiData = await this.fetchFromAPI()
      if (!apiData) return false

      // ✅ 修复：增加首次加载的判断
      const needUpdate =
        !this.lastUpdateTime || // 首次加载，没有更新时间
        apiData.themes.length !== this.themes.size ||
        apiData.lastUpdate > this.lastUpdateTime

      if (needUpdate) {
        console.log('[ThemeDataService] 🔄 检测到新数据，更新中...')
        console.log(`  旧数据: ${this.themes.size}个题材, 更新于 ${this.lastUpdateTime || '无'}`)
        console.log(`  新数据: ${apiData.themes.length}个题材, 更新于 ${apiData.lastUpdate}`)

        this.buildMapping(apiData)
        await this.saveToIndexedDB(apiData)
        this.syncToDataLayer()
        console.log(`[ThemeDataService] ✅ 更新完成`)
        return true
      }

      console.log('[ThemeDataService] 数据无变化，跳过更新')
      return false
    } catch (error) {
      console.warn('[ThemeDataService] 后台更新失败:', error)
      return false
    }
  }

  /**
   * 启动定时更新
   */
  startAutoUpdate(): void {
    if (this.updateTimer) return

    console.log('[ThemeDataService] 🚀 启动定时更新 (间隔: 2小时)')
    this.updateTimer = setInterval(() => {
      console.log('[ThemeDataService] 定时任务触发，检查更新...')
      this.checkAndUpdateFromAPI()
    }, this.UPDATE_INTERVAL)
  }

  /**
   * 停止定时更新
   */
  stopAutoUpdate(): void {
    if (this.updateTimer) {
      clearInterval(this.updateTimer)
      this.updateTimer = null
      console.log('[ThemeDataService] 🛑 停止定时更新')
    }
  }

  /**
   * 强制刷新（从 API 获取并保存）
   */
  async forceRefresh(): Promise<boolean> {
    console.log('[ThemeDataService] 🔄 强制刷新题材映射...')
    const apiData = await this.fetchFromAPI()
    if (apiData) {
      this.buildMapping(apiData)
      await this.saveToIndexedDB(apiData)
      this.syncToDataLayer()
      return true
    }
    return false
  }

  /**
   * 获取当前版本号
   */
  getCurrentVersion(): string {
    return this.lastUpdateTime || 'unknown'
  }

  /**
   * 获取题材列表
   */
  getThemeList(): Array<{ id: string; name: string }> {
    if (this.kplThemes.length > 0) {
      return this.kplThemes
    }
    return this.getAllThemes()
  }

  /**
   * 获取映射统计信息
   */
  getMappingStats(): {
    themeCount: number
    stockCount: number
    topThemes: Array<{ id: string; name: string; stockCount: number }>
  } {
    const topThemes = Array.from(this.themeStocks.entries())
      .map(([id, stocks]) => ({
        id,
        name: this.getThemeName(id),
        stockCount: stocks.length,
      }))
      .sort((a, b) => b.stockCount - a.stockCount)
      .slice(0, 10)

    return {
      themeCount: this.themes.size,
      stockCount: this.stockThemes.size,
      topThemes,
    }
  }

  // Getter 方法
  getTheme(themeId: string): ThemeBase | undefined {
    return this.themes.get(themeId)
  }

  getThemeName(themeId: string): string {
    return this.themes.get(themeId)?.name || themeId
  }

  getThemeStocks(themeId: string): string[] {
    return this.themeStocks.get(themeId) || []
  }

  getStockThemes(stockCode: string): string[] {
    return this.stockThemes.get(stockCode) || []
  }

  getStockThemeNames(stockCode: string): string[] {
    const themeIds = this.getStockThemes(stockCode)
    return themeIds.map((id) => this.getThemeName(id))
  }

  getAllThemes(): ThemeBase[] {
    return Array.from(this.themes.values())
  }

  getAllMappings(): ThemeMapping[] {
    return Array.from(this.themeStocks.entries()).map(([id, stocks]) => ({
      id,
      name: this.getThemeName(id),
      stocks,
      zsCode: this.themes.get(id)?.zsCode || '',
    }))
  }

  isLoaded(): boolean {
    return this.loaded
  }

  getLastUpdateTime(): string | null {
    return this.lastUpdateTime
  }

  async waitForLoaded(timeout: number = 5000): Promise<boolean> {
    if (this.loaded) return true
    const startTime = Date.now()
    while (!this.loaded && Date.now() - startTime < timeout) {
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
    return this.loaded
  }

  getStats(): {
    themeCount: number
    stockCount: number
    loaded: boolean
    lastUpdate: string | null
    autoUpdateRunning: boolean
  } {
    return {
      themeCount: this.themes.size,
      stockCount: this.stockThemes.size,
      loaded: this.loaded,
      lastUpdate: this.lastUpdateTime,
      autoUpdateRunning: this.updateTimer !== null,
    }
  }

  clearCache(): void {
    this.themes.clear()
    this.themeStocks.clear()
    this.stockThemes.clear()
    this.loaded = false
    this.loadingPromise = null
    this.lastUpdateTime = null
    this.kplThemes = []
    console.log('[ThemeDataService] 🧹 缓存已清除')
  }

  setData(data: ThemeMappingData): void {
    this.buildMapping(data)
    this.saveToIndexedDB(data)
    this.syncToDataLayer()
  }
}

export const themeMapping = ThemeDataService.getInstance()

// 自动加载并启动定时更新
themeMapping
  .load()
  .then(() => {
    themeMapping.startAutoUpdate()
  })
  .catch((err) => {
    console.warn('[ThemeDataService] 自动加载失败:', err)
  })

export default themeMapping
