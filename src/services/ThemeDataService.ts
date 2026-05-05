import { debugLog } from '@/utils/logger'
// src/services/ThemeDataService.ts
/**
 * 题材数据服务 - 只从 QuantBoard SQLite 题材主库读取运行时基础映射
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
  private lastError: string | null = null
  private kplThemes: ThemeBase[] = []
  private currentMappingData: ThemeMappingData | null = null

  private constructor() {}

  static getInstance(): ThemeDataService {
    if (!ThemeDataService.instance) {
      ThemeDataService.instance = new ThemeDataService()
    }
    return ThemeDataService.instance
  }

  private normalizeTags(tags: Array<{ Name?: string; Reason?: string }> = []) {
    return tags
      .map((tag) => ({
        Name: String(tag?.Name || '').trim(),
        Reason: tag?.Reason ? String(tag.Reason).trim() : undefined,
      }))
      .filter((tag) => tag.Name)
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
   * 从 QuantBoard SQLite 题材主库读取正式映射。
   */
  private async loadFromSQLiteAPI(): Promise<ThemeMappingData | null> {
    try {
      debugLog('[ThemeDataService] 从 QuantBoard SQLite 读取题材映射...')
      const response = await apiService.getSqliteThemeMapping()
      const mapping = response?.mapping
      if (!mapping?.themes?.length) {
        this.lastError = 'SQLite 题材映射为空或结构异常'
        console.warn('[ThemeDataService] SQLite 题材映射为空或结构异常:', response)
        return null
      }
      this.lastError = null
      return {
        version: String(mapping.version || 'unknown'),
        lastUpdate: String(mapping.lastUpdate || new Date().toISOString()),
        totalThemes: Number(mapping.totalThemes || mapping.themes.length || 0),
        themes: mapping.themes,
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      this.lastError = `SQLite 题材映射读取失败: ${message}`
      console.warn('[ThemeDataService] SQLite 题材映射读取失败:', error)
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
          const incomingReason = String(reason || '').trim()
          if (!incomingReason) return

          const reasonParts = new Set(
            (this.stockReasonsMap.get(code) || '')
              .split('；')
              .map((item) => item.trim())
              .filter(Boolean),
          )
          incomingReason
            .split('；')
            .map((item) => item.trim())
            .filter(Boolean)
            .forEach((item) => reasonParts.add(item))

          const nextReason = Array.from(reasonParts).join('；')
          if (nextReason) {
            this.stockReasonsMap.set(code, nextReason)
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
   * 加载数据：只读取 QuantBoard SQLite 题材主库。
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

      const mappingData = await this.loadFromSQLiteAPI()

      if (mappingData) {
        debugLog(`[ThemeDataService] 从 SQLite 加载: ${mappingData.themes.length}个题材`)
        this.buildMapping(mappingData)
        this.syncToDataLayer()
        this.loaded = true
        this.lastError = null
      } else {
        this.loaded = false
        if (!this.lastError) this.lastError = 'SQLite 题材映射读取失败'
        return false
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
   * 强制刷新（从 QuantBoard SQLite 题材主库重新读取）
   */
  async forceRefresh(): Promise<boolean> {
    debugLog('[ThemeDataService] 🔄 从 SQLite 强制刷新题材映射...')
    const sqliteData = await this.loadFromSQLiteAPI()
    if (!sqliteData) return false
    this.buildMapping(sqliteData)
    this.syncToDataLayer()
    this.syncTagsAndReasonsToDataLayer()
    this.loaded = true
    return true
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
      autoUpdateRunning: false,
    }
  }

  getLoadStatus(): {
    source: 'sqlite'
    loaded: boolean
    lastUpdate: string | null
    lastError: string | null
    themeCount: number
    mappingCount: number
  } {
    const mappingCount = Array.from(this.themeStocks.values()).reduce(
      (total, stocks) => total + stocks.length,
      0,
    )
    return {
      source: 'sqlite',
      loaded: this.loaded,
      lastUpdate: this.lastUpdateTime,
      lastError: this.lastError,
      themeCount: this.themes.size,
      mappingCount,
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
    this.lastError = null
    this.kplThemes = []
    this.currentMappingData = null
    debugLog('[ThemeDataService] 🧹 缓存已清除')
  }

  setData(data: ThemeMappingData): void {
    this.buildMapping(data)
    this.syncToDataLayer()
  }
}

export const themeMapping = ThemeDataService.getInstance()

// V4 口径：themeMapping 长期只作为静态题材映射 repository 兼容导出。
// 运行态题材强度、轮动、事件和个股暴露统一通过 src/services/theme/ThemeFacade。
// 自动加载并启动定时更新；Node/Vitest 环境没有浏览器 fetch 语义。
if (typeof window !== 'undefined' && typeof fetch !== 'undefined') {
  themeMapping
    .load()
    .catch((err) => {
      console.warn('[ThemeDataService] 自动加载失败:', err)
    })
}

export default themeMapping
