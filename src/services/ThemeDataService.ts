import { debugLog } from '@/utils/logger'
// src/services/ThemeDataService.ts
/**
 * 题材数据服务 - 提供静态基础数据 + API更新能力 + IndexedDB持久化
 */

import { apiService } from './apiService'
import { dataLayer } from './DataLayer'
import type { ThemeBase, ThemeMapping, ThemeMappingData } from '../types/sector'

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

// ========== IndexedDB 存储的数据结构（增强版）==========
interface StoredThemeData {
  key: string
  data: ThemeMappingData
  lastUpdate: string
  savedAt: string
  version: string
  totalThemes: number
  totalStocks: number
  stats: {
    themeCount: number
    stockCount: number
    avgStocksPerTheme: number
  }
}

class ThemeDataService {
  private static instance: ThemeDataService

  private themes: Map<string, ThemeBase> = new Map()
  private themeStocks: Map<string, string[]> = new Map()
  private stockThemes: Map<string, string[]> = new Map()

  private stockTagsMap: Map<string, Array<{ Name: string; Reason?: string }>> = new Map()
  private stockReasonsMap: Map<string, string> = new Map()

  private loaded: boolean = false
  private loadingPromise: Promise<boolean> | null = null
  private lastUpdateTime: string | null = null
  private kplThemes: ThemeBase[] = []
  private currentMappingData: ThemeMappingData | null = null

  // IndexedDB 配置
  private readonly DB_NAME = 'ThemeDataDB'
  private readonly DB_VERSION = 3 // ✅ 升级版本号
  private readonly STORE_NAME = 'theme_mapping'
  private db: IDBDatabase | null = null

  private updateTimer: ReturnType<typeof setInterval> | null = null

  private readonly UPDATE_INTERVAL = 2 * 60 * 60 * 1000 // 2小时
  private readonly MIN_SAFE_THEME_COUNT = 100
  private readonly MIN_SAFE_STOCK_COUNT = 1000

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
        debugLog('[ThemeDataService] IndexedDB 连接成功')
        resolve(this.db)
      }

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result
        if (!db.objectStoreNames.contains(this.STORE_NAME)) {
          const store = db.createObjectStore(this.STORE_NAME, { keyPath: 'key' })
          store.createIndex('lastUpdate', 'lastUpdate', { unique: false })
          store.createIndex('savedAt', 'savedAt', { unique: false })
          store.createIndex('version', 'version', { unique: false })
          debugLog('[ThemeDataService] IndexedDB 表创建成功')
        }
      }
    })
  }

  /**
   * 保存数据到 IndexedDB（增强版）
   */
  private async saveToIndexedDB(data: ThemeMappingData): Promise<void> {
    try {
      const db = await this.initDB()
      const transaction = db.transaction([this.STORE_NAME], 'readwrite')
      const store = transaction.objectStore(this.STORE_NAME)

      // ✅ 使用传入的 data 来计算统计，而不是依赖 this.themes
      const totalThemes = data.themes.length
      let totalStocks = 0
      data.themes.forEach((theme) => {
        totalStocks += theme.stocks.length
      })
      const avgStocksPerTheme = totalThemes > 0 ? totalStocks / totalThemes : 0

      const storedData: StoredThemeData = {
        key: 'theme_data',
        data: data,
        lastUpdate: data.lastUpdate,
        savedAt: new Date().toISOString(),
        version: data.version,
        totalThemes: totalThemes,
        totalStocks: totalStocks,
        stats: {
          themeCount: totalThemes,
          stockCount: totalStocks,
          avgStocksPerTheme: Math.round(avgStocksPerTheme * 10) / 10,
        },
      }

      store.put(storedData)

      return new Promise((resolve, reject) => {
        transaction.oncomplete = () => {
          debugLog('[ThemeDataService] ✅ 数据已保存到 IndexedDB:', {
            themes: storedData.totalThemes,
            stocks: storedData.totalStocks,
            version: storedData.version,
          })
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

  private getUniqueStockCount(data: ThemeMappingData | null): number {
    if (!data?.themes?.length) return 0

    const stockCodes = new Set<string>()
    data.themes.forEach((theme) => {
      ;(theme.stocks || []).forEach((code) => {
        const normalizedCode = this.normalizeCode(code)
        if (normalizedCode && normalizedCode !== '000000') {
          stockCodes.add(normalizedCode)
        }
      })
    })
    return stockCodes.size
  }

  private isSafeFullMapping(data: ThemeMappingData | null): boolean {
    if (!data?.themes?.length) return false
    return (
      data.themes.length >= this.MIN_SAFE_THEME_COUNT &&
      this.getUniqueStockCount(data) >= this.MIN_SAFE_STOCK_COUNT
    )
  }

  private normalizeTags(tags: Array<{ Name?: string; Reason?: string }> = []) {
    return tags
      .map((tag) => ({
        Name: String(tag?.Name || '').trim(),
        Reason: tag?.Reason ? String(tag.Reason).trim() : undefined,
      }))
      .filter((tag) => tag.Name)
  }

  private mergeTagAndReasonData(data: ThemeMappingData | null): number {
    if (!data?.themes?.length) return 0

    const currentThemesById = new Map<string, ThemeMapping>()
    this.currentMappingData?.themes?.forEach((theme) => {
      currentThemesById.set(theme.id, theme)
    })

    let mergedCount = 0

    data.themes.forEach((sourceTheme) => {
      const targetTheme = currentThemesById.get(sourceTheme.id)
      const targetStockTags = targetTheme
        ? ((targetTheme.stockTags ||= {}) as Record<string, Array<{ Name: string; Reason?: string }>>)
        : undefined
      const targetStockReasons = targetTheme
        ? ((targetTheme.stockReasons ||= {}) as Record<string, string>)
        : undefined

      Object.entries(sourceTheme.stockTags || {}).forEach(([rawCode, rawTags]) => {
        const code = this.normalizeCode(rawCode)
        const incomingTags = this.normalizeTags(rawTags)
        if (!code || incomingTags.length === 0) return

        const existingTags = this.stockTagsMap.get(code) || []
        const nextTags = [...existingTags]

        incomingTags.forEach((tag) => {
          const existing = nextTags.find((item) => item.Name === tag.Name)
          if (!existing) {
            nextTags.push(tag)
            mergedCount++
          } else if (!existing.Reason && tag.Reason) {
            existing.Reason = tag.Reason
            mergedCount++
          }
        })

        this.stockTagsMap.set(code, nextTags)
        if (targetStockTags) {
          targetStockTags[code] = nextTags
        }
      })

      Object.entries(sourceTheme.stockReasons || {}).forEach(([rawCode, reason]) => {
        const code = this.normalizeCode(rawCode)
        const incomingReason = String(reason || '').trim()
        if (!code || !incomingReason) return

        const existingReason = this.stockReasonsMap.get(code) || ''
        const reasonParts = new Set(
          existingReason
            .split('；')
            .map((item) => item.trim())
            .filter(Boolean),
        )
        const beforeSize = reasonParts.size
        incomingReason
          .split('；')
          .map((item) => item.trim())
          .filter(Boolean)
          .forEach((item) => reasonParts.add(item))

        const nextReason = Array.from(reasonParts).join('；')
        if (nextReason && nextReason !== existingReason) {
          this.stockReasonsMap.set(code, nextReason)
          if (targetStockReasons) {
            targetStockReasons[code] = nextReason
          }
          mergedCount += Math.max(1, reasonParts.size - beforeSize)
        }
      })
    })

    return mergedCount
  }

  private syncTagsAndReasonsToDataLayer(): void {
    const stockTagsUpdates = Array.from(this.stockTagsMap.entries()).map(([code, tags]) => ({
      code,
      tags: tags.map((tag) => ({ Name: tag.Name })),
    }))

    const limitUpUpdates = Array.from(
      new Set([...this.stockTagsMap.keys(), ...this.stockReasonsMap.keys()]),
    ).map((code) => ({
      code,
      reason: this.stockReasonsMap.get(code),
      tags: this.stockTagsMap.get(code)?.map((tag) => ({ Name: tag.Name })),
    }))

    if (stockTagsUpdates.length > 0) {
      dataLayer.updateStockTags(stockTagsUpdates)
    }

    if (limitUpUpdates.length > 0) {
      dataLayer.updateLimitUpData(limitUpUpdates)
    }

    const stocks = dataLayer.getStocks()
    if (stocks.length > 0 && (stockTagsUpdates.length > 0 || limitUpUpdates.length > 0)) {
      dataLayer.setMergedStocks(
        stocks.map((stock) => ({
          ...stock,
          tags: this.stockTagsMap.get(stock.code) || stock.tags || [],
          reason: this.stockReasonsMap.get(stock.code) || stock.reason || '',
        })),
      )
    }
  }

  /**
   * 从 IndexedDB 加载数据（增强版）
   */
  private async loadFromIndexedDB(): Promise<ThemeMappingData | null> {
    try {
      const db = await this.initDB()

      return new Promise((resolve, reject) => {
        const transaction = db.transaction([this.STORE_NAME], 'readonly')
        const store = transaction.objectStore(this.STORE_NAME)
        const request = store.get('theme_data')

        request.onsuccess = () => {
          const result = request.result as StoredThemeData | undefined
          if (result?.data) {
            debugLog(`[ThemeDataService] 📀 从 IndexedDB 读取数据:`, {
              version: result.data.version,
              lastUpdate: result.data.lastUpdate,
              savedAt: result.savedAt,
              themes: result.totalThemes,
              stocks: result.totalStocks,
            })
            resolve(result.data)
          } else {
            debugLog('[ThemeDataService] IndexedDB 无缓存数据')
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
      debugLog('[ThemeDataService] 🌐 从 API 获取题材数据...')

      let allThemeIds: string[] = []

      allThemeIds = Array.from(this.themes.keys())

      if (allThemeIds.length === 0 && this.kplThemes.length > 0) {
        allThemeIds = this.kplThemes.map((t) => t.id)
      }

      if (allThemeIds.length === 0) {
        console.warn('[ThemeDataService] 没有题材 ID，无法更新')
        return null
      }

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
              const stockCodes: string[] = []
              const stockTagsMap: Record<string, Array<{ Name: string; Reason?: string }>> = {}
              const stockReasonsMap: Record<string, string> = {}

              result.data.StockList.forEach((stock: any) => {
                const code = this.normalizeCode(stock.StockID)
                if (code && code.length === 6) {
                  stockCodes.push(code)

                  // ✅ 提取标签和原因
                  if (stock.Tag && stock.Tag.length > 0) {
                    const tags: Array<{ Name: string; Reason?: string }> = []
                    const reasons: string[] = []

                    stock.Tag.forEach((tag: any) => {
                      tags.push({ Name: tag.Name })
                      if (tag.Reason) {
                        reasons.push(tag.Reason)
                      }
                    })

                    stockTagsMap[code] = tags
                    if (reasons.length > 0) {
                      stockReasonsMap[code] = reasons.join('；')
                    }
                  }
                }
              })

              if (stockCodes.length > 0) {
                const themeId = result.data.ID

                if (!themesMap.has(themeId)) {
                  themesMap.set(themeId, {
                    id: themeId,
                    name: result.data.Name,
                    stocks: stockCodes,
                    zsCode: result.data.ZSCode || '',
                    stockTags: stockTagsMap, // ✅ 保存标签
                    stockReasons: stockReasonsMap, // ✅ 保存原因
                  })
                  validCount++
                } else {
                  duplicateCount++
                  console.warn(`[ThemeDataService] 发现重复题材 ID: ${themeId}`)
                }
              }
            }
          })
        }

        await this.delay(300)
      }

      const allThemes = Array.from(themesMap.values())
      debugLog(
        `[ThemeDataService] ✅ API 获取完成: 有效题材=${validCount}, 最终=${allThemes.length}`,
      )

      return {
        version: new Date().toISOString(),
        lastUpdate: new Date().toISOString(),
        totalThemes: allThemes.length,
        themes: allThemes,
      }
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
      debugLog(`[ThemeDataService] 📁 从本地文件加载: ${data.themes?.length || 0}个题材`)
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
      debugLog(`[ThemeDataService] 📋 从 KPL_THEME_DATA 加载: ${this.kplThemes.length}个题材`)
    }
  }

  /**
   * 构建内存映射
   */
  private buildMapping(mappingData: ThemeMappingData): void {
    this.themes.clear()
    this.themeStocks.clear()
    this.stockThemes.clear()
    this.stockTagsMap.clear() // ✅ 新增
    this.stockReasonsMap.clear() // ✅ 新增

    const uniqueThemes = new Map<string, ThemeMapping>()

    mappingData.themes.forEach((theme) => {
      if (!uniqueThemes.has(theme.id)) {
        uniqueThemes.set(theme.id, {
          ...theme,
          stocks: [...(theme.stocks || [])],
          stockTags: theme.stockTags ? { ...theme.stockTags } : undefined,
          stockReasons: theme.stockReasons ? { ...theme.stockReasons } : undefined,
        })
      }
    })

    this.currentMappingData = {
      ...mappingData,
      totalThemes: uniqueThemes.size,
      themes: Array.from(uniqueThemes.values()),
    }

    this.currentMappingData.themes.forEach((theme) => {
      this.themes.set(theme.id, {
        id: theme.id,
        name: theme.name,
        zsCode: theme.zsCode || '',
      })
      this.themeStocks.set(theme.id, theme.stocks || [])

      // ✅ 提取标签和原因
      if (theme.stockTags) {
        Object.entries(theme.stockTags).forEach(([code, tags]) => {
          if (!this.stockTagsMap.has(code)) {
            this.stockTagsMap.set(code, [])
          }
          const existing = this.stockTagsMap.get(code)!
          tags.forEach((tag) => {
            if (!existing.find((t) => t.Name === tag.Name)) {
              existing.push(tag)
            }
          })
        })
      }

      if (theme.stockReasons) {
        Object.entries(theme.stockReasons).forEach(([code, reason]) => {
          if (!this.stockReasonsMap.has(code) && reason) {
            this.stockReasonsMap.set(code, reason)
          }
        })
      }

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
    debugLog(`[ThemeDataService] 构建映射完成: ${uniqueThemes.size} 个唯一题材`)
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
      debugLog('[ThemeDataService] 开始加载题材映射...')

      // 加载 KPL 题材列表
      this.loadKPLThemes()

      // 1. 优先从 IndexedDB 读取
      let mappingData = await this.loadFromIndexedDB()

      if (mappingData) {
        if (!this.isSafeFullMapping(mappingData)) {
          console.warn('[ThemeDataService] IndexedDB 题材缓存异常，尝试使用本地完整映射修复:', {
            themes: mappingData.themes.length,
            stocks: this.getUniqueStockCount(mappingData),
          })

          const localData = await this.fetchFromLocal()
          if (localData && this.isSafeFullMapping(localData)) {
            mappingData = localData
            await this.saveToIndexedDB(localData)
            console.warn('[ThemeDataService] 已用本地完整映射修复题材缓存:', {
              themes: localData.themes.length,
              stocks: this.getUniqueStockCount(localData),
            })
          }
        }

        debugLog(`[ThemeDataService] 📀 从 IndexedDB 加载: ${mappingData.themes.length}个题材`)
        this.buildMapping(mappingData)
        this.syncToDataLayer()
        this.loaded = true

        debugLog('[ThemeDataService] 数据加载完成，定时任务将每2小时检查一次更新')
      } else {
        // 2. IndexedDB 没有数据，从本地文件加载（首次加载）
        const localData = await this.fetchFromLocal()
        if (localData) {
          debugLog(`[ThemeDataService] 📁 从本地文件加载: ${localData.themes.length}个题材`)
          this.buildMapping(localData)
          this.syncToDataLayer()
          this.loaded = true
          if (this.isSafeFullMapping(localData)) {
            await this.saveToIndexedDB(localData)
          }

          // 首次加载后，从 API 获取最新数据（异步，不阻塞）
          debugLog('[ThemeDataService] 首次加载完成，正在后台同步最新数据...')
          this.checkAndUpdateFromAPI().then((updated) => {
            if (updated) {
              debugLog('[ThemeDataService] 首次同步完成')
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
      if (this.lastUpdateTime) {
        const lastUpdateTime = new Date(this.lastUpdateTime).getTime()
        const twoHours = this.UPDATE_INTERVAL
        const now = Date.now()
        const hoursSinceUpdate = (now - lastUpdateTime) / (60 * 60 * 1000)

        if (now - lastUpdateTime < twoHours) {
          debugLog(
            `[ThemeDataService] 数据新鲜 (${hoursSinceUpdate.toFixed(1)}小时前)，跳过更新`,
          )
          return false
        } else {
          debugLog(
            `[ThemeDataService] 数据已过时 (${hoursSinceUpdate.toFixed(1)}小时前)，开始更新...`,
          )
        }
      }

      const apiData = await this.fetchFromAPI()
      if (!apiData) return false
      if (!this.isSafeFullMapping(apiData)) {
        const mergedTagReasonCount = this.mergeTagAndReasonData(apiData)
        if (mergedTagReasonCount > 0) {
          if (this.currentMappingData) {
            await this.saveToIndexedDB(this.currentMappingData)
          }
          this.syncTagsAndReasonsToDataLayer()
        }
        console.warn('[ThemeDataService] API 返回的题材映射规模异常，跳过覆盖缓存:', {
          apiThemes: apiData.themes.length,
          apiStocks: this.getUniqueStockCount(apiData),
          currentThemes: this.themes.size,
          currentStocks: this.stockThemes.size,
          mergedTagReasons: mergedTagReasonCount,
        })
        return false
      }

      if (this.themes.size > 0 && apiData.themes.length < this.themes.size * 0.8) {
        const mergedTagReasonCount = this.mergeTagAndReasonData(apiData)
        if (mergedTagReasonCount > 0) {
          if (this.currentMappingData) {
            await this.saveToIndexedDB(this.currentMappingData)
          }
          this.syncTagsAndReasonsToDataLayer()
        }
        console.warn('[ThemeDataService] API 返回题材数量明显少于当前映射，跳过覆盖缓存:', {
          apiThemes: apiData.themes.length,
          currentThemes: this.themes.size,
          mergedTagReasons: mergedTagReasonCount,
        })
        return false
      }

      const needUpdate =
        !this.lastUpdateTime ||
        apiData.themes.length !== this.themes.size ||
        apiData.lastUpdate > this.lastUpdateTime

      if (needUpdate) {
        debugLog('[ThemeDataService] 🔄 检测到新数据，更新中...')
        debugLog(`  旧数据: ${this.themes.size}个题材, 更新于 ${this.lastUpdateTime || '无'}`)
        debugLog(`  新数据: ${apiData.themes.length}个题材, 更新于 ${apiData.lastUpdate}`)

        this.buildMapping(apiData)
        await this.saveToIndexedDB(apiData)
        this.syncToDataLayer()
        this.syncTagsAndReasonsToDataLayer()
        debugLog(`[ThemeDataService] ✅ 更新完成`)
        return true
      }

      debugLog('[ThemeDataService] 数据无变化，跳过更新')
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

    debugLog('[ThemeDataService] 🚀 启动定时更新 (间隔: 2小时)')
    this.updateTimer = setInterval(() => {
      debugLog('[ThemeDataService] 定时任务触发，检查更新...')
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
      debugLog('[ThemeDataService] 🛑 停止定时更新')
    }
  }

  /**
   * 强制刷新（从 API 获取并保存）
   */
  async forceRefresh(): Promise<boolean> {
    debugLog('[ThemeDataService] 🔄 强制刷新题材映射...')
    const apiData = await this.fetchFromAPI()
    if (apiData) {
      if (!this.isSafeFullMapping(apiData)) {
        const mergedTagReasonCount = this.mergeTagAndReasonData(apiData)
        if (mergedTagReasonCount > 0) {
          if (this.currentMappingData) {
            await this.saveToIndexedDB(this.currentMappingData)
          }
          this.syncTagsAndReasonsToDataLayer()
        }
        console.warn('[ThemeDataService] 强制刷新返回的题材映射规模异常，已拒绝覆盖:', {
          apiThemes: apiData.themes.length,
          apiStocks: this.getUniqueStockCount(apiData),
          mergedTagReasons: mergedTagReasonCount,
        })
        return false
      }
      this.buildMapping(apiData)
      await this.saveToIndexedDB(apiData)
      this.syncToDataLayer()
      this.syncTagsAndReasonsToDataLayer()
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
  getThemeList(): ThemeBase[] {
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

  // 获取股票标签
  getStockTagsWithReason(code: string): Array<{ Name: string; Reason?: string }> {
    return this.stockTagsMap.get(code) || []
  }

  // 获取股票原因
  getStockReason(code: string): string {
    return this.stockReasonsMap.get(code) || ''
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
    this.stockTagsMap.clear()
    this.stockReasonsMap.clear()
    this.loaded = false
    this.loadingPromise = null
    this.lastUpdateTime = null
    this.kplThemes = []
    this.currentMappingData = null
    debugLog('[ThemeDataService] 🧹 缓存已清除')
  }

  setData(data: ThemeMappingData): void {
    this.buildMapping(data)
    this.saveToIndexedDB(data)
    this.syncToDataLayer()
  }
}

export const themeMapping = ThemeDataService.getInstance()

// 自动加载并启动定时更新；Node/Vitest 环境没有 IndexedDB 和相对 fetch 语义。
if (typeof window !== 'undefined' && typeof indexedDB !== 'undefined') {
  themeMapping
    .load()
    .then(() => {
      themeMapping.startAutoUpdate()
    })
    .catch((err) => {
      console.warn('[ThemeDataService] 自动加载失败:', err)
    })
}

export default themeMapping
