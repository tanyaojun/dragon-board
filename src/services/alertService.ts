// src/services/alertService.ts

import { dataLayer } from './DataLayer'
import {
  ALERT_CONFIG,
  ALERT_TYPES,
  ALERT_LEVELS,
  ALERT_THRESHOLDS,
  ALERT_THRESHOLDS_EXTENDED,
  BATCH_LIMIT_UP_CONFIG,
  ALERT_EMOTION_MULTIPLIERS,
  LIMIT_UP_CONFIG,
  STOCK_ALERT_CONFIG,
  SECTOR_ALERT_CONFIG,
} from '@/config/constants'
import type { StockAlert, AlertType, AlertLevel } from '@/types/core'
import { v4 as uuidv4 } from 'uuid'
import { themeFacade } from './theme/ThemeFacade'
import type { ThemeEvent } from './theme/types'

// ========== 股票工具类（增强版） ==========
class StockTools {
  /**
   * 判断股票类型
   */
  static getStockType(code: string): 'main' | 'gem' | 'star' | 'north' | 'st' | 'unknown' {
    if (code.startsWith('60') || code.startsWith('00')) return 'main'
    if (code.startsWith('30')) return 'gem'
    if (code.startsWith('688')) return 'star'
    if (code.startsWith('8')) return 'north'
    return 'unknown'
  }

  /**
   * 判断是否ST股
   */
  static isST(name: string): boolean {
    return name?.includes('ST') || name?.includes('*ST') || false
  }

  /**
   * 判断是否新股
   */
  static isNewStock(listDate?: string): boolean {
    if (!listDate) return false
    const days = (Date.now() - new Date(listDate).getTime()) / (24 * 60 * 60 * 1000)
    return days < LIMIT_UP_CONFIG.RULES.NEW_STOCK_PROTECTION_DAYS
  }

  /**
   * 获取涨停阈值
   */
  static getLimitUpThreshold(code: string, name: string): number {
    if (this.isST(name)) return LIMIT_UP_CONFIG.THRESHOLDS.ST
    const type = this.getStockType(code)
    const map: Record<string, number> = {
      main: LIMIT_UP_CONFIG.THRESHOLDS.MAIN,
      gem: LIMIT_UP_CONFIG.THRESHOLDS.GEM,
      star: LIMIT_UP_CONFIG.THRESHOLDS.STAR,
      north: LIMIT_UP_CONFIG.THRESHOLDS.NORTH,
    }
    return map[type] || LIMIT_UP_CONFIG.THRESHOLDS.MAIN
  }

  /**
   * 判断是否真实涨停（考虑封单、板块效应等）
   */
  static isGenuineLimitUp(
    code: string,
    name: string,
    change: number,
    fengdan?: number,
    sectorZtCount?: number,
    listDate?: string,
  ): boolean {
    // 新股不判断
    if (this.isNewStock(listDate)) return false

    // 基础涨幅判断
    const threshold = this.getLimitUpThreshold(code, name)
    const isLimitByPrice =
      change >= threshold && change <= threshold + LIMIT_UP_CONFIG.RULES.CHANGE_TOLERANCE
    if (!isLimitByPrice) return false

    // 如果有封单要求，检查封单
    if (LIMIT_UP_CONFIG.RULES.REQUIRE_FENGDAN && fengdan !== undefined) {
      if (fengdan < LIMIT_UP_CONFIG.RULES.MIN_FENGDAN) return false
    }

    // 如果考虑板块效应
    if (LIMIT_UP_CONFIG.RULES.CONSIDER_SECTOR_EFFECT && sectorZtCount !== undefined) {
      // 板块内有多个涨停才算强势
      if (sectorZtCount < 2) return false
    }

    return true
  }

  /**
   * 判断是否跌停
   */
  static isLimitDown(code: string, name: string, change: number): boolean {
    if (this.isNewStock(name)) return false
    const threshold = -this.getLimitUpThreshold(code, name)
    return change <= threshold && change >= threshold - LIMIT_UP_CONFIG.RULES.CHANGE_TOLERANCE
  }
}

// ========== 板块工具类 ==========
class SectorTools {
  /**
   * 获取板块规模
   */
  static getSectorSize(totalStocks: number): 'SMALL' | 'MEDIUM' | 'LARGE' {
    if (totalStocks < 20) return 'SMALL'
    if (totalStocks < 50) return 'MEDIUM'
    return 'LARGE'
  }

  /**
   * 判断是否批量涨停（使用 BATCH_LIMIT_UP_CONFIG）
   */
  static isBatchLimitUp(
    ztCount: number,
    totalStocks: number,
  ): { isBatch: boolean; level: AlertLevel; desc: string } | null {
    if (ztCount === 0 || totalStocks === 0) return null

    const ztRatio = ztCount / totalStocks
    const size = this.getSectorSize(totalStocks)
    const rules = BATCH_LIMIT_UP_CONFIG.BY_SECTOR_SIZE[size]

    // 判断是否严重级别
    if (
      (BATCH_LIMIT_UP_CONFIG.USE_RATIO && ztRatio >= rules.CRITICAL.RATIO) ||
      (BATCH_LIMIT_UP_CONFIG.USE_COUNT && ztCount >= rules.CRITICAL.COUNT)
    ) {
      return {
        isBatch: true,
        level: ALERT_LEVELS.CRITICAL,
        desc: `批量涨停 ${ztCount}只 (占比${(ztRatio * 100).toFixed(1)}%)`,
      }
    }

    // 判断是否普通警告
    if (
      (BATCH_LIMIT_UP_CONFIG.USE_RATIO && ztRatio >= rules.WARNING.RATIO) ||
      (BATCH_LIMIT_UP_CONFIG.USE_COUNT && ztCount >= rules.WARNING.COUNT)
    ) {
      return {
        isBatch: true,
        level: ALERT_LEVELS.WARNING,
        desc: `批量涨停 ${ztCount}只`,
      }
    }

    return null
  }

  /**
   * 判断资金流向级别
   */
  static getMoneyFlowLevel(
    netInflow: number,
  ): { level: AlertLevel; type: 'inflow' | 'outflow' } | null {
    const inflowInWan = netInflow / 10000 // 转为万元

    if (inflowInWan >= ALERT_THRESHOLDS.MONEY_FLOW.STRONG_INFLOW) {
      return { level: ALERT_LEVELS.WARNING, type: 'inflow' }
    }
    if (inflowInWan <= ALERT_THRESHOLDS.MONEY_FLOW.STRONG_OUTFLOW) {
      return { level: ALERT_LEVELS.WARNING, type: 'outflow' }
    }
    return null
  }

  /**
   * 判断量比级别
   */
  static getVolumeRatioLevel(volumeRatio: number): AlertLevel | null {
    if (volumeRatio >= ALERT_THRESHOLDS.VOLUME_SURGE.CRITICAL) return ALERT_LEVELS.CRITICAL
    if (volumeRatio >= ALERT_THRESHOLDS.VOLUME_SURGE.WARNING) return ALERT_LEVELS.WARNING
    return null
  }
}

class AlertService {
  private static instance: AlertService
  private alertHistory: Map<string, StockAlert> = new Map()
  private lastCheck: number = 0
  private checkTimer: ReturnType<typeof setInterval> | null = null
  private cooldownMap: Map<string, number> = new Map()

  // 快照（只保留最近的数据用于对比）
  private blocksSnapshot: Map<string, any> = new Map()
  private stocksSnapshot: Map<string, any> = new Map()
  private themeEventFrameKeys: Set<string> = new Set()

  private constructor() {
    this.startAutoCheck()
  }

  static getInstance(): AlertService {
    if (!AlertService.instance) {
      AlertService.instance = new AlertService()
    }
    return AlertService.instance
  }

  /**
   * 启动自动检查
   */
  private startAutoCheck() {
    if (!ALERT_CONFIG.ENABLED) return
    this.checkTimer = setInterval(() => this.checkAll(), ALERT_CONFIG.CHECK_INTERVAL)
  }

  /**
   * 停止自动检查
   */
  stopAutoCheck() {
    if (this.checkTimer) {
      clearInterval(this.checkTimer)
      this.checkTimer = null
    }
  }

  /**
   * 获取 dataLayer 状态
   */
  private getState() {
    return (dataLayer as any).state
  }

  /**
   * 获取当前情绪阶段
   */
  private getCurrentPhase(): string {
    try {
      const breath = this.getState()?.analysis?.breath
      return breath?.sentiment?.phaseName || '启动'
    } catch {
      return '启动'
    }
  }

  /**
   * 获取情绪乘数
   */
  private getEmotionMultiplier(alertType?: AlertType): number {
    try {
      const phase = this.getCurrentPhase()

      // 先检查是否有针对该预警类型的独立乘数
      const byAlertType = ALERT_EMOTION_MULTIPLIERS.BY_ALERT_TYPE as Partial<
        Record<AlertType, Record<string, number>>
      >
      if (alertType && byAlertType[alertType]) {
        const typeMultiplier = byAlertType[alertType]?.[phase]
        if (typeMultiplier !== undefined) {
          return typeMultiplier
        }
      }

      // 否则使用通用乘数
      return (ALERT_EMOTION_MULTIPLIERS.BY_PHASE as Record<string, number>)[phase] || 1.0
    } catch {
      return 1.0
    }
  }

  /**
   * 获取动态阈值
   */
  private getDynamicThreshold(baseThreshold: number, alertType?: AlertType): number {
    const multiplier = this.getEmotionMultiplier(alertType)
    return baseThreshold * multiplier
  }

  /**
   * 检查所有预警
   */
  async checkAll() {
    try {
      this.themeEventFrameKeys.clear()
      await Promise.all([this.checkThemeEvents(), this.updateBlockSnapshot(), this.checkStocks()])
      this.cleanExpiredAlerts()
      this.lastCheck = Date.now()
    } catch (error) {
      console.error('[AlertService] 检查预警失败:', error)
    }
  }

  private checkThemeEvents = async () => {
    const result = await themeFacade.refreshRuntime({ source: 'alertService', emitAlerts: true })
    for (const event of result.events) {
      await this.ingestThemeEvent(event)
    }
  }

  private alertTypeForThemeEvent(event: ThemeEvent): AlertType {
    if (event.alertType) return event.alertType
    if (event.type === 'theme_fund_inflow') return ALERT_TYPES.MONEY_FLOW
    if (event.type === 'theme_crowding_high') return 'volume_surge'
    if (event.type === 'theme_cooling') return 'strength_plunge'
    if (event.type === 'theme_leader_fall') return ALERT_TYPES.LEADER_FALL
    if (event.type === 'theme_mapping_quality_warning') return ALERT_TYPES.DATA_ANOMALY
    return 'strength_surge'
  }

  private themeAlertDedupeKey(type: AlertType, themeId?: string, themeName?: string): string {
    return `${type}:${themeId || themeName || ''}`
  }

  private async ingestThemeEvent(event: ThemeEvent) {
    const titleByType: Record<ThemeEvent['type'], string> = {
      theme_mainline_started: `${event.themeName} 进入主线`,
      theme_strength_surge: `${event.themeName} 强度上升`,
      theme_fund_inflow: `${event.themeName} 资金流入`,
      theme_crowding_high: `${event.themeName} 拥挤度偏高`,
      theme_cooling: `${event.themeName} 题材降温`,
      theme_leader_fall: `${event.themeName} 龙头转弱`,
      theme_mapping_quality_warning: `${event.themeName} 题材数据质量提示`,
    }
    this.themeEventFrameKeys.add(
      this.themeAlertDedupeKey(this.alertTypeForThemeEvent(event), event.themeId, event.themeName),
    )
    return this.createAlert({
      type: this.alertTypeForThemeEvent(event),
      level: event.level,
      title: titleByType[event.type],
      message: event.reasons.join('；') || event.type,
      themeId: event.themeId,
      themeName: event.themeName,
      snapshot: {
        themeEvent: event,
        metrics: event.metrics,
        riskFlags: event.riskFlags,
        stockCodes: event.stockCodes,
      },
    })
  }

  /**
   * 维护 legacy 板块快照。题材/板块预警统一由 ThemeRuntimeCoordinator 生成。
   */
  private updateBlockSnapshot = async () => {
    const blocks = themeFacade.getJxbkBlocks()
    const timestamp = Date.now()

    for (const block of blocks) {
      this.blocksSnapshot.set(block.code, {
        strength: block.strength,
        timestamp,
      })
    }

    const oneHourAgo = Date.now() - 60 * 60 * 1000
    for (const [code, data] of this.blocksSnapshot) {
      if (data.timestamp < oneHourAgo) {
        this.blocksSnapshot.delete(code)
      }
    }
  }

  /**
   * 检查个股预警
   */
  private checkStocks = async () => {
    const stockMap = themeFacade.getThemeStockMap()
    const stocks = Object.values(stockMap) as any[]

    for (const stock of stocks) {
      try {
        const prevStock = this.stocksSnapshot.get(stock.code)

        // 1. 涨速预警（火箭发射/瀑布跳水）
        if (stock.speed && !isNaN(stock.speed) && isFinite(stock.speed)) {
          const rocketThreshold = this.getDynamicThreshold(
            STOCK_ALERT_CONFIG.ROCKET_LAUNCH.MIN_SPEED,
            'rocket_launch',
          )
          const diveThreshold = this.getDynamicThreshold(
            Math.abs(STOCK_ALERT_CONFIG.WATERFALL_DIVE.MAX_SPEED),
            'waterfall_dive',
          )

          // 火箭发射
          if (
            stock.speed > rocketThreshold &&
            stock.speed < STOCK_ALERT_CONFIG.ROCKET_LAUNCH.MAX_CHANGE &&
            (!STOCK_ALERT_CONFIG.ROCKET_LAUNCH.REQUIRE_VOLUME ||
              stock.volumeRatio >= STOCK_ALERT_CONFIG.ROCKET_LAUNCH.MIN_VOLUME_RATIO)
          ) {
            await this.createAlert({
              type: 'rocket_launch',
              level: ALERT_LEVELS.INFO,
              title: `🚀 ${stock.name} 火箭发射`,
              message: `涨速 ${stock.speed.toFixed(2)}%`,
              code: stock.code,
              name: stock.name,
              snapshot: { price: stock.price, change: stock.change },
            })
          }
          // 瀑布跳水
          else if (
            stock.speed < -diveThreshold &&
            stock.speed > STOCK_ALERT_CONFIG.WATERFALL_DIVE.MIN_CHANGE &&
            (!STOCK_ALERT_CONFIG.WATERFALL_DIVE.REQUIRE_VOLUME ||
              stock.volumeRatio >= STOCK_ALERT_CONFIG.WATERFALL_DIVE.MIN_VOLUME_RATIO)
          ) {
            await this.createAlert({
              type: 'waterfall_dive',
              level: ALERT_LEVELS.WARNING,
              title: `💧 ${stock.name} 瀑布跳水`,
              message: `跌速 ${Math.abs(stock.speed).toFixed(2)}%`,
              code: stock.code,
              name: stock.name,
              snapshot: { price: stock.price, change: stock.change },
            })
          }
        }

        // 2. 龙头相关预警
        if (stock.leadStatus?.includes('龙')) {
          // 龙头涨停
          if (
            StockTools.isGenuineLimitUp(
              stock.code,
              stock.name,
              stock.change,
              stock.fengdan,
              undefined, // 板块涨停数暂时未知
              stock.listDate,
            )
          ) {
            await this.createAlert({
              type: ALERT_TYPES.LEADER_EMERGE,
              level: ALERT_LEVELS.INFO,
              title: `👑 ${stock.name} 龙头涨停`,
              message: `${stock.leadStatus} 涨停 ${stock.change.toFixed(2)}%`,
              code: stock.code,
              name: stock.name,
              snapshot: { change: stock.change, lianban: stock.lianban },
            })
          }

          // 龙头倒下
          if (StockTools.isLimitDown(stock.code, stock.name, stock.change)) {
            const fallWarning = this.getDynamicThreshold(
              Math.abs(ALERT_THRESHOLDS.LEADER_FALL.WARNING),
              'leader_fall',
            )
            const fallCritical = this.getDynamicThreshold(
              Math.abs(ALERT_THRESHOLDS.LEADER_FALL.CRITICAL),
              'leader_fall',
            )

            let level: AlertLevel = ALERT_LEVELS.WARNING
            if (stock.change <= -fallCritical) {
              level = ALERT_LEVELS.CRITICAL
            } else if (stock.change <= -fallWarning) {
              level = ALERT_LEVELS.WARNING
            }

            await this.createAlert({
              type: ALERT_TYPES.LEADER_FALL,
              level,
              title: `💔 ${stock.name} 龙头倒下`,
              message: `${stock.leadStatus} 跌停 ${stock.change.toFixed(2)}%`,
              code: stock.code,
              name: stock.name,
              snapshot: { change: stock.change },
            })
          }
        }

        // 3. 封单变化预警（需要对比历史）
        if (
          prevStock &&
          stock.fengdan &&
          prevStock.fengdan >= STOCK_ALERT_CONFIG.FENGDAN_DROP.MIN_ORIGINAL_FENGDAN
        ) {
          const dropPercent = ((prevStock.fengdan - stock.fengdan) / prevStock.fengdan) * 100
          const dropThreshold = this.getDynamicThreshold(
            STOCK_ALERT_CONFIG.FENGDAN_DROP.MIN_DROP_PERCENT,
            'fengdan_drop',
          )

          if (dropPercent > dropThreshold) {
            await this.createAlert({
              type: 'fengdan_drop',
              level: ALERT_LEVELS.WARNING,
              title: `📉 ${stock.name} 封单剧减`,
              message: `封单减少 ${dropPercent.toFixed(1)}%`,
              code: stock.code,
              name: stock.name,
              snapshot: { fengdan: stock.fengdan },
            })
          }
        }

        // 保存快照
        this.stocksSnapshot.set(stock.code, {
          fengdan: stock.fengdan,
          timestamp: Date.now(),
        })
      } catch (e) {
        console.error(`[AlertService] 处理个股 ${stock.code} 失败:`, e)
      }
    }

    // 清理过旧的快照
    const fiveMinutesAgo = Date.now() - STOCK_ALERT_CONFIG.FENGDAN_DROP.CHECK_WINDOW
    for (const [code, data] of this.stocksSnapshot) {
      if (data.timestamp < fiveMinutesAgo) {
        this.stocksSnapshot.delete(code)
      }
    }
  }

  /**
   * 创建预警
   */
  private async createAlert(params: {
    type: AlertType
    level: AlertLevel
    title: string
    message: string
    code?: string
    name?: string
    themeId?: string
    themeName?: string
    snapshot?: any
  }) {
    const { type, level, title, message, code, name, themeId, themeName, snapshot } = params

    // 生成冷却key
    const keyParts: string[] = [type]
    if (code) keyParts.push(code)
    if (themeId) keyParts.push(themeId)
    const cooldownKey = keyParts.join('_')

    // 检查冷却
    const lastTime = this.cooldownMap.get(cooldownKey)
    const now = Date.now()

    if (lastTime && now - lastTime < ALERT_CONFIG.COOLDOWN) {
      return
    }

    const alert: StockAlert = {
      id: uuidv4(),
      type,
      level,
      title,
      message,
      timestamp: now,
      expireTime: now + ALERT_CONFIG.EXPIRE_TIME,
      status: 'pending',
      code,
      name,
      themeId,
      themeName,
      snapshot,
    }

    this.alertHistory.set(alert.id, alert)
    this.cooldownMap.set(cooldownKey, now)

    // 保存到 dataLayer
    this.saveToDataLayer(alert)

    return alert
  }

  /**
   * 保存预警到 dataLayer
   */
  private saveToDataLayer(alert: StockAlert) {
    try {
      const state = this.getState()
      if (!state?.analysis?.alerts) {
        if (!state.analysis) state.analysis = {}
        state.analysis.alerts = { items: [], stats: {} }
      }

      state.analysis.alerts.items.unshift(alert)
      if (state.analysis.alerts.items.length > ALERT_CONFIG.MAX_ALERTS) {
        state.analysis.alerts.items.pop()
      }
      this.updateAlertStats()
    } catch (e) {
      console.warn('[AlertService] 保存到 dataLayer 失败:', e)
    }
  }

  /**
   * 更新预警统计
   */
  private updateAlertStats() {
    try {
      const state = this.getState()
      const items = state?.analysis?.alerts?.items || []

      const stats = {
        total: items.length,
        critical: items.filter((a: StockAlert) => a.level === 'critical').length,
        warning: items.filter((a: StockAlert) => a.level === 'warning').length,
        info: items.filter((a: StockAlert) => a.level === 'info').length,
        byType: {} as Record<string, number>,
        lastUpdate: Date.now(),
      }

      items.forEach((alert: StockAlert) => {
        stats.byType[alert.type] = (stats.byType[alert.type] || 0) + 1
      })

      if (state?.analysis?.alerts) {
        state.analysis.alerts.stats = stats
      }
    } catch (e) {
      // 忽略
    }
  }

  /**
   * 清理过期预警
   */
  private cleanExpiredAlerts() {
    try {
      const state = this.getState()
      const items = state?.analysis?.alerts?.items || []
      const now = Date.now()

      const newItems = items.filter((alert: StockAlert) => alert.expireTime > now)

      if (newItems.length !== items.length) {
        state.analysis.alerts.items = newItems
        this.updateAlertStats()
      }

      // 清理内存中的过期预警
      for (const [id, alert] of this.alertHistory) {
        if (alert.expireTime <= now) {
          this.alertHistory.delete(id)
        }
      }
    } catch (e) {
      // 忽略
    }
  }

  /**
   * 格式化金额
   */
  private formatMoney(value: number): string {
    if (!value && value !== 0) return '-'
    const absValue = Math.abs(value)
    if (absValue >= 100000000) return (value / 100000000).toFixed(2) + '亿'
    if (absValue >= 10000) return (value / 10000).toFixed(2) + '万'
    return value.toString()
  }

  // ========== 公共API ==========

  getAlerts(limit?: number): StockAlert[] {
    try {
      const state = this.getState()
      const items = state?.analysis?.alerts?.items || []
      return limit ? items.slice(0, limit) : [...items]
    } catch {
      return []
    }
  }

  getUnreadAlerts(): StockAlert[] {
    try {
      const state = this.getState()
      return state?.analysis?.alerts?.items?.filter((a: StockAlert) => a.status === 'pending') || []
    } catch {
      return []
    }
  }

  markAsRead(alertId: string) {
    try {
      const state = this.getState()
      const alert = state?.analysis?.alerts?.items?.find((a: StockAlert) => a.id === alertId)
      if (alert && alert.status === 'pending') {
        alert.status = 'read'
        alert.readTime = Date.now()
        this.updateAlertStats()
      }
    } catch (e) {
      // 忽略
    }
  }

  markAllAsRead() {
    try {
      const state = this.getState()
      state?.analysis?.alerts?.items?.forEach((alert: StockAlert) => {
        if (alert.status === 'pending') {
          alert.status = 'read'
          alert.readTime = Date.now()
        }
      })
      this.updateAlertStats()
    } catch (e) {
      // 忽略
    }
  }

  getAlertStats() {
    try {
      const state = this.getState()
      return (
        state?.analysis?.alerts?.stats || {
          total: 0,
          critical: 0,
          warning: 0,
          info: 0,
          byType: {},
          lastUpdate: Date.now(),
        }
      )
    } catch {
      return {
        total: 0,
        critical: 0,
        warning: 0,
        info: 0,
        byType: {},
        lastUpdate: Date.now(),
      }
    }
  }

  /**
   * 发送预警（对外暴露）
   */
  public sendAlert(params: {
    type: AlertType
    level: AlertLevel
    title: string
    message: string
    code?: string
    name?: string
    themeId?: string
    themeName?: string
    snapshot?: any
  }) {
    return this.createAlert(params)
  }

  public acceptThemeEvent(event: ThemeEvent) {
    return this.ingestThemeEvent(event)
  }

  /**
   * 销毁服务
   */
  destroy() {
    this.stopAutoCheck()
    this.alertHistory.clear()
    this.cooldownMap.clear()
    this.blocksSnapshot.clear()
    this.stocksSnapshot.clear()
  }
}

// 导出单例
export const alertService = AlertService.getInstance()

if (typeof window !== 'undefined') {
  ;(window as any).alertService = alertService
}
