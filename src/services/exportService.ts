import { debugLog } from '@/utils/logger'
// src/services/exportService.ts
// 优化版：添加防抖、错误处理和事件清理

import { useStockStore } from '@/stores/stock'
import { dragonAnalyzer } from './DragonAnalyzer'
import { themeFacade } from './theme/ThemeFacade'
import { dragonBreathAnalyzer } from './DragonBreathAnalyzer'
import { dataLayer } from './DataLayer'
import { EventManager } from '@/utils/eventManager'
import type { Stock } from '@/types'

interface ExportOptions {
  filename?: string
  format: 'csv' | 'json' | 'excel'
  includeHeaders?: boolean
  delimiter?: string
}

type ExportOptionsInput = Partial<ExportOptions>
type ExportStock = Stock & {
  updateTime?: number | string | Date
  leaderReasons?: string[]
}

interface ExportData {
  stocks?: Stock[]
  leaders?: Stock[]
  sectors?: any[]
  market?: any
  timestamp: number
}

interface ExportResult {
  success: boolean
  filename: string
  size: number
  timestamp: number
  error?: string
}

class ExportService {
  private readonly DEFAULT_OPTIONS: ExportOptions = {
    format: 'csv',
    includeHeaders: true,
    delimiter: ',',
  }

  // 防抖控制
  private exportTimer: ReturnType<typeof setTimeout> | null = null
  private lastExportTime = 0
  private readonly EXPORT_DEBOUNCE = 1000 // 1秒内不重复导出
  private readonly EXPORT_MAX_RETRIES = 3
  private exportQueue: Map<string, Promise<any>> = new Map()

  // ========== 导出股票数据 ==========

  async exportStocks(options: ExportOptionsInput = {}): Promise<ExportResult> {
    return this.debouncedExport('stocks', options, async () => {
      const data: ExportData = {
        stocks: this.getCurrentStocks(),
        timestamp: Date.now(),
      }

      return this.export(data, {
        ...this.DEFAULT_OPTIONS,
        ...options,
        filename: options.filename || `股票数据_${this.getDateString()}`,
      })
    })
  }

  async exportLeaders(options: ExportOptionsInput = {}): Promise<ExportResult> {
    return this.debouncedExport('leaders', options, async () => {
      const data: ExportData = {
        leaders: this.getCurrentLeaders(),
        timestamp: Date.now(),
      }

      return this.export(data, {
        ...this.DEFAULT_OPTIONS,
        ...options,
        filename: options.filename || `龙头数据_${this.getDateString()}`,
      })
    })
  }

  async exportSectors(options: ExportOptionsInput = {}): Promise<ExportResult> {
    return this.debouncedExport('sectors', options, async () => {
      const data: ExportData = {
        sectors: themeFacade.getHotThemesCompat(50),
        timestamp: Date.now(),
      }

      return this.export(data, {
        ...this.DEFAULT_OPTIONS,
        ...options,
        filename: options.filename || `题材数据_${this.getDateString()}`,
      })
    })
  }

  async exportMarket(options: ExportOptionsInput = {}): Promise<ExportResult> {
    return this.debouncedExport('market', options, async () => {
      const data: ExportData = {
        market: {
          sentiment: dragonBreathAnalyzer.getMarketSentiment(),
          marketData: dragonBreathAnalyzer.getMarketData(),
          leaders: dragonAnalyzer.getStats(),
        },
        timestamp: Date.now(),
      }

      return this.export(data, {
        ...this.DEFAULT_OPTIONS,
        ...options,
        filename: options.filename || `市场情绪_${this.getDateString()}`,
      })
    })
  }

  async exportAll(options: ExportOptionsInput = {}): Promise<ExportResult> {
    return this.debouncedExport('all', options, async () => {
      const data: ExportData = {
        stocks: this.getCurrentStocks(),
        leaders: this.getCurrentLeaders(),
        sectors: themeFacade.getHotThemesCompat(50),
        market: {
          sentiment: dragonBreathAnalyzer.getMarketSentiment(),
          marketData: dragonBreathAnalyzer.getMarketData(),
          leaders: dragonAnalyzer.getStats(),
        },
        timestamp: Date.now(),
      }

      return this.export(data, {
        ...this.DEFAULT_OPTIONS,
        ...options,
        filename: options.filename || `完整数据_${this.getDateString()}`,
      })
    })
  }

  // ========== 防抖核心逻辑 ==========

  private async debouncedExport(
    type: string,
    options: ExportOptionsInput,
    exportFn: () => Promise<ExportResult>,
  ): Promise<ExportResult> {
    const key = `${type}_${options.format}_${options.filename || 'default'}`

    // 检查是否有相同导出进行中
    if (this.exportQueue.has(key)) {
      debugLog(`[ExportService] 相同导出进行中，等待结果...`)
      return this.exportQueue.get(key)!
    }

    // 清除之前的定时器
    if (this.exportTimer) {
      clearTimeout(this.exportTimer)
      this.exportTimer = null
    }

    // 检查导出频率
    const now = Date.now()
    if (now - this.lastExportTime < this.EXPORT_DEBOUNCE) {
      debugLog(`[ExportService] 导出过于频繁，延迟执行`)

      return new Promise((resolve, reject) => {
        this.exportTimer = setTimeout(async () => {
          try {
            this.exportTimer = null
            const result = await this.executeWithRetry(exportFn)
            resolve(result)
          } catch (error) {
            reject(error)
          }
        }, this.EXPORT_DEBOUNCE)
      })
    }

    return this.executeWithRetry(exportFn)
  }

  private async executeWithRetry(
    exportFn: () => Promise<ExportResult>,
    retryCount = 0,
  ): Promise<ExportResult> {
    const key = `export_${Date.now()}`

    try {
      const promise = exportFn()
      this.exportQueue.set(key, promise)

      const result = await promise

      this.lastExportTime = Date.now()
      this.exportQueue.delete(key)

      // 触发导出成功事件
      EventManager.emit('export:success', {
        type: 'export',
        filename: result.filename,
        size: result.size,
        timestamp: result.timestamp,
      })

      return result
    } catch (error: any) {
      this.exportQueue.delete(key)

      if (retryCount < this.EXPORT_MAX_RETRIES) {
        debugLog(`[ExportService] 导出失败，重试 ${retryCount + 1}/${this.EXPORT_MAX_RETRIES}`)
        await this.delay(1000 * (retryCount + 1))
        return this.executeWithRetry(exportFn, retryCount + 1)
      }

      // 触发导出失败事件
      EventManager.emit('export:error', {
        type: 'export',
        error: error.message,
        timestamp: Date.now(),
      })

      throw error
    }
  }

  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }

  // ========== 核心导出逻辑 ==========

  private async export(data: ExportData, options: ExportOptions): Promise<ExportResult> {
    const startTime = Date.now()
    let blob: Blob

    try {
      switch (options.format) {
        case 'csv':
          blob = this.exportToCSV(data, options)
          break
        case 'json':
          blob = this.exportToJSON(data, options)
          break
        case 'excel':
          blob = this.exportToExcel(data, options)
          break
        default:
          throw new Error(`不支持的导出格式: ${options.format}`)
      }

      const filename = `${options.filename}.${this.getFileExtension(options.format)}`
      this.download(blob, filename)

      const result: ExportResult = {
        success: true,
        filename,
        size: blob.size,
        timestamp: Date.now(),
      }

      const duration = Date.now() - startTime
      debugLog(
        `[ExportService] ✅ 导出成功: ${filename} (${(blob.size / 1024).toFixed(1)}KB, ${duration}ms)`,
      )

      return result
    } catch (error: any) {
      console.error('[ExportService] ❌ 导出失败:', error)
      throw error
    }
  }

  private exportToCSV(data: ExportData, options: ExportOptions): Blob {
    let csv = ''

    if (data.stocks) {
      csv += this.stocksToCSV(data.stocks, options)
    } else if (data.leaders) {
      csv += this.leadersToCSV(data.leaders, options)
    } else if (data.sectors) {
      csv += this.sectorsToCSV(data.sectors, options)
    } else if (data.market) {
      csv += this.marketToCSV(data.market, options)
    }

    return new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' })
  }

  private exportToJSON(data: ExportData, options: ExportOptions): Blob {
    const json = JSON.stringify(data, null, 2)
    return new Blob([json], { type: 'application/json' })
  }

  private exportToExcel(data: ExportData, options: ExportOptions): Blob {
    const csvBlob = this.exportToCSV(data, options)
    return new Blob([csvBlob], { type: 'application/vnd.ms-excel;charset=utf-8' })
  }

  private getCurrentStocks(): Stock[] {
    const stocks = dataLayer.getStocks?.() || []
    if (stocks.length > 0) return stocks as Stock[]

    const stockStore = useStockStore()
    return stockStore.stocks || []
  }

  private getCurrentLeaders(): Stock[] {
    const stocks = this.getCurrentStocks()
    const leaders = stocks.filter((stock) => this.isLeaderStock(stock))
    if (leaders.length > 0) return leaders

    const stockStore = useStockStore()
    return stockStore.leaders || []
  }

  private isLeaderStock(stock: Stock): boolean {
    if (stock.isSectorLeader) return true

    const leaders = dragonAnalyzer.getAllLeaders?.() || []
    return leaders.some((leader: any) => leader.code === stock.code)
  }

  private getFileExtension(format: ExportOptions['format']): string {
    return format === 'excel' ? 'xls' : format
  }

  // ========== 数据转换方法保持不变 ==========
  private stocksToCSV(stocks: Stock[], options: ExportOptions): string {
    const headers = [
      '代码',
      '名称',
      '最新价',
      '涨幅%',
      '成交额',
      '换手率%',
      '主力净额',
      '主力占比%',
      '超大单',
      '超大占比%',
      '东财排名',
      '同花顺排名',
      '开盘啦排名',
      '通达信排名',
      '雪球排名',
      '财联社排名',
      '淘股吧排名',
      '大智慧排名',
      '均榜',
      '综合排名',
      '排名变化',
      '是否龙头',
      '龙头级别',
      '龙头评分',
      '连板天数',
      '题材',
      '更新时间',
    ]

    const rows = stocks.map((stock) => {
      const exportStock = stock as ExportStock
      return [
      stock.code,
      stock.name,
      stock.price?.toFixed(2) || '',
      stock.change?.toFixed(2) || '',
      this.formatNumber(stock.turnover),
      stock.turnoverRate?.toFixed(2) || '',
      this.formatNumber(stock.zlje),
      stock.zljzb?.toFixed(2) || '',
      this.formatNumber(stock.cddje),
      stock.cddjzb?.toFixed(2) || '',
      stock.emRank || '',
      stock.thsRank || '',
      stock.kplRank || '',
      stock.tdxRank || '',
      stock.xqRank || '',
      stock.clsRank || '',
      stock.tgbRank || '',
      stock.dzhRank || '',
      stock.avgRank || '',
      stock.compRank || '',
      stock.rankChange || '',
      stock.isSectorLeader ? '是' : '否',
      stock.leaderLevel || '',
      stock.leaderScore?.toFixed(0) || '',
      stock.continuousDays || '',
      (stock.themes || []).join(';'),
      exportStock.updateTime ? new Date(exportStock.updateTime).toLocaleString() : '',
    ]
    })

    return this.arrayToCSV(headers, rows, options)
  }

  private leadersToCSV(leaders: Stock[], options: ExportOptions): string {
    const headers = [
      '代码',
      '名称',
      '龙头级别',
      '龙头评分',
      '涨幅%',
      '最新价',
      '成交额',
      '主力净额',
      '连板天数',
      '题材',
      '识别理由',
    ]

    const rows = leaders.map((leader) => [
      leader.code,
      leader.name,
      leader.leaderLevel,
      leader.leaderScore?.toFixed(0) || '',
      leader.change?.toFixed(2) || '',
      leader.price?.toFixed(2) || '',
      this.formatNumber(leader.turnover),
      this.formatNumber(leader.zlje),
      leader.continuousDays || '',
      (leader.themes || []).join(';'),
      ((leader as ExportStock).leaderReasons || []).join(';'),
    ])

    return this.arrayToCSV(headers, rows, options)
  }

  private sectorsToCSV(sectors: any[], options: ExportOptions): string {
    const headers = ['题材名称', '股票数量', '涨停数量', '龙头数量', '热度评分', '动量', '热门股票']

    const rows = sectors.map((sector) => [
      sector.name,
      sector.stockCount || 0,
      sector.ztCount || 0,
      sector.leaderCount || 0,
      sector.heatScore || 0,
      sector.momentum || 0,
      (sector.leaders || []).map((l: any) => l.name).join(';'),
    ])

    return this.arrayToCSV(headers, rows, options)
  }

  private marketToCSV(market: any, options: ExportOptions): string {
    const lines: string[] = []

    lines.push('=== 市场情绪 ===')
    lines.push(`情绪阶段,${market.sentiment.phaseName || market.sentiment.phase || ''}`)
    lines.push(`风险等级,${market.sentiment.riskLevel}`)
    lines.push(`操作建议,${market.sentiment.suggestion}`)
    lines.push('')

    lines.push('=== 市场数据 ===')
    lines.push(`上涨家数,${market.marketData.upCount}`)
    lines.push(`下跌家数,${market.marketData.downCount}`)
    lines.push(`涨停家数,${market.marketData.ztCount}`)
    lines.push(`跌停家数,${market.marketData.dtCount}`)
    lines.push(`成交额,${this.formatNumber(market.marketData.totalAmo)}`)
    lines.push(`情绪值,${market.marketData.emotionValue.toFixed(2)}`)
    lines.push('')

    lines.push('=== 连板统计 ===')
    lines.push(`一板,${market.marketData.limitData.yiban}`)
    lines.push(`二板,${market.marketData.limitData.erban}`)
    lines.push(`三板,${market.marketData.limitData.sanban}`)
    lines.push(`四板以上,${market.marketData.limitData.sibanPlus}`)
    lines.push('')

    lines.push('=== 龙头统计 ===')
    lines.push(`总龙头,${market.leaders.totalLeadersCount}`)
    lines.push(`板块龙头,${market.leaders.sectorLeaders}`)
    lines.push(`连板龙头,${market.leaders.continuousLeaders}`)
    lines.push(`中军龙头,${market.leaders.middleLeaders}`)
    lines.push(`情绪龙头,${market.leaders.emotionLeaders}`)
    lines.push(`龙头总数,${market.leaders.totalLeaders}`)

    return lines.join('\n')
  }

  private arrayToCSV(headers: string[], rows: any[][], options: ExportOptions): string {
    const delimiter = options.delimiter || ','
    const lines: string[] = []

    if (options.includeHeaders) {
      lines.push(headers.join(delimiter))
    }

    rows.forEach((row) => {
      const escapedRow = row.map((cell) => {
        if (cell === null || cell === undefined) return ''
        const str = String(cell)
        if (str.includes(delimiter) || str.includes('"') || str.includes('\n')) {
          return `"${str.replace(/"/g, '""')}"`
        }
        return str
      })
      lines.push(escapedRow.join(delimiter))
    })

    return lines.join('\n')
  }

  private formatNumber(num?: number): string {
    if (!num && num !== 0) return ''
    if (Math.abs(num) >= 1e8) return (num / 1e8).toFixed(2) + '亿'
    if (Math.abs(num) >= 1e4) return (num / 1e4).toFixed(2) + '万'
    return num.toString()
  }

  private getDateString(): string {
    const date = new Date()
    return `${date.getFullYear()}${String(date.getMonth() + 1).padStart(2, '0')}${String(date.getDate()).padStart(2, '0')}_${String(date.getHours()).padStart(2, '0')}${String(date.getMinutes()).padStart(2, '0')}`
  }

  private download(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    a.remove()

    // 延迟释放 URL 对象，确保下载完成
    setTimeout(() => {
      URL.revokeObjectURL(url)
    }, 1000)
  }

  // ========== 公共方法 ==========

  /**
   * 取消所有进行中的导出
   */
  cancelAll() {
    if (this.exportTimer) {
      clearTimeout(this.exportTimer)
      this.exportTimer = null
    }
    this.exportQueue.clear()
    debugLog('[ExportService] 已取消所有导出任务')
  }

  /**
   * 获取导出状态
   */
  getStatus() {
    return {
      queueSize: this.exportQueue.size,
      lastExportTime: this.lastExportTime,
      isExporting: this.exportQueue.size > 0 || this.exportTimer !== null,
    }
  }
}

export const exportService = new ExportService()
