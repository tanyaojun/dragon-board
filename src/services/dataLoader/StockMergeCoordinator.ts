import type { MergedStock } from '@/types'
import { DEFAULT_RANK } from '@/types/config'
import { stockCodeManager } from '../StockCodeManager'
import { shouldApplyMoneyFlowUpdate } from '../moneyFlowSourcePriority'

// 8 平台 rank 字段映射（原 ComprehensiveRankEngine 导出，2026-09-21 口径唯一化后仅剩
// 展示合并这一处消费方，收编为模块私有）。平台 rank 是原始平台数据展示字段，非计算输入。
const RANK_FIELD_MAP: Record<string, string> = {
  eastmoney: 'emRank',
  ths: 'thsRank',
  kpl: 'kplRank',
  tdx: 'tdxRank',
  xueqiu: 'xqRank',
  cls: 'clsRank',
  tgb: 'tgbRank',
  dzh: 'dzhRank',
}

function getRankField(platform: string): string | null {
  return RANK_FIELD_MAP[platform] || null
}

function isValidStockName(name: string): boolean {
  return !!(name && name !== '-' && name !== 'null' && name !== 'undefined' && name.trim() !== '')
}

/**
 * 构建 MergedStock 全字段空壳（含各平台 DEFAULT_RANK 占位）。
 * 供合并链与帧池种子行共用，保证种子行结构与普通合并行同形。
 */
export function createEmptyMergedStock(code: string): MergedStock {
  let defaultName = ''
  const codeInfo = stockCodeManager.getStockInfo(code)
  if (codeInfo && isValidStockName(codeInfo.name)) {
    defaultName = codeInfo.name
  }

  return {
    code,
    name: defaultName,
    price: 0,
    change: 0,
    volume: 0,
    turnover: 0,
    turnoverRate: 0,
    pe: 0,
    pb: 0,
    totalMV: 0,
    cirMV: 0,
    zlje: 0,
    zljzb: 0,
    cddje: 0,
    cddjzb: 0,
    emRank: DEFAULT_RANK,
    thsRank: DEFAULT_RANK,
    kplRank: DEFAULT_RANK,
    tdxRank: DEFAULT_RANK,
    xqRank: DEFAULT_RANK,
    clsRank: DEFAULT_RANK,
    tgbRank: DEFAULT_RANK,
    dzhRank: DEFAULT_RANK,
    platforms: 0,
    avgRankNum: DEFAULT_RANK,
    avgRank: DEFAULT_RANK.toString(),
    compRank: undefined,
    compScore: 0,
    updatedAt: Date.now(),
    continuousDays: 1,
    themes: [],
    hotness: 0,
    tags: [],
    reason: '',
    isNew: false,
    firstZtTime: '',
    lastZtTime: '',
    boardHeight: 0,
    highDays: 0,
    platformName: '',
    fundPenetration: 0,
    firstSeen: undefined,
    lastSeen: undefined,
    mainTheme: undefined,
    themeHeat: 0,
    themeLevel: '冷',
  }
}

export interface StockMergeCoordinatorInput {
  platformData: Record<string, any[]>
  latestQuotes?: Map<string, any>
  volumeHistoryMap?: Map<string, number[]>
  intradayVolumeHistoryMap?: Map<string, number[]>
  existingMap: Map<string, any>
}

export class StockMergeCoordinator {
  async merge(input: StockMergeCoordinatorInput): Promise<any[]> {
    const stockMap = await this.buildStockMap(input)
    this.applyStockNameFallbacks(stockMap)
    // 2026-09-21 口径唯一化（spec: 2026-09-21-comprehensive-rank-golden-convergence-design.md）：
    // 删除本地综合排名/均榜计算（2026-08-24 回滚口径作废），compScore/compRank/avgRankNum
    // 一律消费后端 golden（帧池种子行透传，framePoolSource.buildFrameSeedStock）；
    // 降级链行无排名，如实缺省并由 poolSource provenance 打标（fail-visible，不伪造）。
    const merged = Array.from(stockMap.values())
    return merged.sort(
      (a, b) =>
        (a.compRank ?? DEFAULT_RANK) - (b.compRank ?? DEFAULT_RANK) ||
        String(a.code).localeCompare(String(b.code)),
    )
  }

  private async buildStockMap(input: StockMergeCoordinatorInput): Promise<Map<string, any>> {
    const quoteMap = input.latestQuotes ?? new Map()
    const stockMap = new Map<string, any>()
    const quoteProcessedCodes = new Set<string>()

    for (const [platform, items] of Object.entries(input.platformData || {})) {
      for (const item of items) {
        const code = item.code
        if (!code) continue

        let stock = stockMap.get(code)
        if (!stock) {
          const existing = input.existingMap.get(code)
          stock = existing ? { ...existing } : this.createEmptyStock(code)
          stockMap.set(code, stock)
        }

        const rankField = getRankField(platform)
        if (rankField) {
          stock[rankField] = item.rank
        }

        if (this.isValidName(item.name) && !stock.platformName) {
          stock.platformName = item.name
        }

        if (quoteMap.has(code) && !quoteProcessedCodes.has(code)) {
          this.mergeQuoteData(stock, code, quoteMap)
          quoteProcessedCodes.add(code)
        }
      }
    }

    for (const [code, existing] of input.existingMap.entries()) {
      if (!stockMap.has(code)) {
        const stock = { ...existing }
        if (quoteMap.has(code) && !quoteProcessedCodes.has(code)) {
          this.mergeQuoteData(stock, code, quoteMap)
          quoteProcessedCodes.add(code)
        }
        stockMap.set(code, stock)
      }
    }

    return stockMap
  }

  private mergeQuoteData(stock: any, code: string, quoteMap: Map<string, any>): void {
    const quote = quoteMap.get(code)
    if (!quote) return

    const pickFundFlowValue = (nextValue: unknown, currentValue: unknown) => {
      const nextNumber = Number(nextValue)
      const currentNumber = Number(currentValue)

      if (Number.isFinite(nextNumber)) return nextNumber
      if (Number.isFinite(currentNumber)) return currentNumber
      return 0
    }
    const pickPositiveValue = (nextValue: unknown, currentValue: unknown) => {
      const nextNumber = Number(nextValue)
      const currentNumber = Number(currentValue)

      if (Number.isFinite(nextNumber) && nextNumber > 0) return nextNumber
      if (Number.isFinite(currentNumber) && currentNumber > 0) return currentNumber
      if (Number.isFinite(nextNumber)) return nextNumber
      return 0
    }
    const shouldApplyMoneyFlow = shouldApplyMoneyFlowUpdate(stock, quote)

    Object.assign(stock, {
      price: pickPositiveValue(quote.price, stock.price),
      change: quote.change ?? stock.change,
      volume: pickPositiveValue(quote.volume, stock.volume),
      turnover: pickPositiveValue(quote.turnover, stock.turnover),
      turnoverRate: pickPositiveValue(quote.turnoverRate, stock.turnoverRate),
      pe: pickPositiveValue(quote.pe, stock.pe),
      pb: pickPositiveValue(quote.pb, stock.pb),
      totalMV: pickPositiveValue(quote.totalMV, stock.totalMV),
      cirMV: pickPositiveValue(quote.cirMV, stock.cirMV),
      zlje: shouldApplyMoneyFlow ? pickFundFlowValue(quote.zlje, stock.zlje) : stock.zlje,
      zljzb: shouldApplyMoneyFlow ? pickFundFlowValue(quote.zljzb, stock.zljzb) : stock.zljzb,
      cddje: shouldApplyMoneyFlow ? pickFundFlowValue(quote.cddje, stock.cddje) : stock.cddje,
      cddjzb: shouldApplyMoneyFlow ? pickFundFlowValue(quote.cddjzb, stock.cddjzb) : stock.cddjzb,
      moneyFlowSource: shouldApplyMoneyFlow
        ? quote.moneyFlowSource ?? stock.moneyFlowSource
        : stock.moneyFlowSource,
      moneyFlowEstimated: shouldApplyMoneyFlow
        ? quote.moneyFlowEstimated ?? stock.moneyFlowEstimated
        : stock.moneyFlowEstimated,
      capitalFlowSource: shouldApplyMoneyFlow
        ? quote.capitalFlowSource ?? stock.capitalFlowSource
        : stock.capitalFlowSource,
      capitalFlowConfidence: shouldApplyMoneyFlow
        ? quote.capitalFlowConfidence ?? stock.capitalFlowConfidence
        : stock.capitalFlowConfidence,
      tdxBuyVolume: quote.tdxBuyVolume ?? stock.tdxBuyVolume,
      tdxSellVolume: quote.tdxSellVolume ?? stock.tdxSellVolume,
      tdxCurrentVolume: quote.tdxCurrentVolume ?? stock.tdxCurrentVolume,
    })
    this.applyQuoteVolumeRatio(stock, quote)

    let stockName = ''

    if (quote.name && quote.name !== '-' && quote.name !== '') {
      stockName = quote.name
    } else if (stock.platformName && stock.platformName !== '-' && stock.platformName !== '') {
      stockName = stock.platformName
    }

    if (!stockName || stockName === '' || stockName === '-') {
      const codeInfo = stockCodeManager.getStockInfo(code)
      if (codeInfo && codeInfo.name && codeInfo.name !== '未知') {
        stockName = codeInfo.name
      }
    }

    if (stockName) {
      stock.name = stockName
    }
  }

  private applyQuoteVolumeRatio(stock: any, quote: any): void {
    // golden 3 日量比为主，腾讯 f10 仅在缺失/无效时兜底，不覆盖已有量比（口径一致）
    const existing = Number(stock?.volumeRatio)
    if (Number.isFinite(existing) && existing > 0) return

    const volumeRatio = Number(quote?.volumeRatio)
    if (!Number.isFinite(volumeRatio) || volumeRatio <= 0) return

    stock.volumeRatio = Number(volumeRatio.toFixed(2))
    stock.volumeRatioMeta = {
      status: 'fresh',
      source: 'daily_snapshot',
      calculatedAt: Date.now(),
      currentVolume: Number(stock.volume) || 0,
      rawRatio: stock.volumeRatio,
      capped: false,
      reason: 'quote_feed',
    }
  }

  private applyStockNameFallbacks(stockMap: Map<string, any>): void {
    for (const stock of stockMap.values()) {
      const hasValidName = this.isValidName(stock.name)

      if (!hasValidName && stock.platformName) {
        stock.name = stock.platformName
      }

      if (!this.isValidName(stock.name)) {
        const codeInfo = stockCodeManager.getStockInfo(stock.code)
        if (codeInfo && this.isValidName(codeInfo.name)) {
          stock.name = codeInfo.name
        }
      }

      if (!this.isValidName(stock.name)) {
        stock.name = '-'
      }

      delete stock._quoteProcessed
    }
  }

  private createEmptyStock(code: string): MergedStock {
    return createEmptyMergedStock(code)
  }

  private isValidName(name: string): boolean {
    return isValidStockName(name)
  }
}

export const stockMergeCoordinator = new StockMergeCoordinator()
