import type { MergedStock } from '@/types'
import { DEFAULT_RANK } from '@/types/config'
import { stockCodeManager } from '../StockCodeManager'
import { getRankField, rankMergedStocks } from './ComprehensiveRankEngine'

export interface StockMergeCoordinatorInput {
  platformData: Record<string, any[]>
  latestQuotes?: Map<string, any>
  volumeHistoryMap: Map<string, number[]>
  intradayVolumeHistoryMap?: Map<string, number[]>
  existingMap: Map<string, any>
}

export class StockMergeCoordinator {
  async merge(input: StockMergeCoordinatorInput): Promise<any[]> {
    const stockMap = await this.buildStockMap(input)
    this.applyStockNameFallbacks(stockMap)
    return rankMergedStocks(stockMap, input.platformData)
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

      if (Number.isFinite(nextNumber) && nextNumber !== 0) return nextNumber
      if (Number.isFinite(currentNumber)) return currentNumber
      if (Number.isFinite(nextNumber)) return nextNumber
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
      zlje: pickFundFlowValue(quote.zlje, stock.zlje),
      zljzb: pickFundFlowValue(quote.zljzb, stock.zljzb),
      cddje: pickFundFlowValue(quote.cddje, stock.cddje),
      cddjzb: pickFundFlowValue(quote.cddjzb, stock.cddjzb),
      moneyFlowSource: quote.moneyFlowSource ?? stock.moneyFlowSource,
      moneyFlowEstimated: quote.moneyFlowEstimated ?? stock.moneyFlowEstimated,
      capitalFlowSource: quote.capitalFlowSource ?? stock.capitalFlowSource,
      capitalFlowConfidence: quote.capitalFlowConfidence ?? stock.capitalFlowConfidence,
      tdxBuyVolume: quote.tdxBuyVolume ?? stock.tdxBuyVolume,
      tdxSellVolume: quote.tdxSellVolume ?? stock.tdxSellVolume,
      tdxCurrentVolume: quote.tdxCurrentVolume ?? stock.tdxCurrentVolume,
    })

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
    let defaultName = ''
    const codeInfo = stockCodeManager.getStockInfo(code)
    if (codeInfo && this.isValidName(codeInfo.name)) {
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

  private isValidName(name: string): boolean {
    return !!(name && name !== '-' && name !== 'null' && name !== 'undefined' && name.trim() !== '')
  }
}

export const stockMergeCoordinator = new StockMergeCoordinator()
