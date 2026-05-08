import type { MergedStock } from '@/types'
import { calculateStockHotnessUpdates, stockHotnessConfigService } from '../hotness'
import { dataLayer } from '../DataLayer'

export class StockHotnessService {
  updateStockHotness(stocks: MergedStock[], totalPlatforms = 8): void {
    const updates = calculateStockHotnessUpdates(
      stocks,
      totalPlatforms,
      stockHotnessConfigService.getConfig(),
    )

    const hotnessMap = new Map(updates.map((item) => [item.code, item.hotness]))
    stocks.forEach((stock) => {
      stock.hotness = hotnessMap.get(stock.code) ?? 0
    })

    dataLayer.updateStockHotness(updates)
  }

  recalculateStockHotness(totalPlatforms = 8): MergedStock[] {
    const stocks = dataLayer.getStocks().map((stock) => ({ ...stock }))
    if (!stocks.length) return []

    this.updateStockHotness(stocks, totalPlatforms)
    return stocks
  }
}

export const stockHotnessService = new StockHotnessService()
