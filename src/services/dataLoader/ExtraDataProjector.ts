import { dataLayer } from '../DataLayer'
import { resolvePrimaryStockTheme } from '../theme/stockThemeMeta'

export class ExtraDataProjector {
  project(stocks: any[]): any[] {
    return stocks.map((stock) => this.projectStock(stock))
  }

  projectRuntimeFields(stock: any) {
    const themes = dataLayer.getStockThemes(stock.code)
    stock.themes = themes
    const primaryTheme = resolvePrimaryStockTheme(themes || [])
    stock.mainTheme = primaryTheme.mainTheme
    stock.themeHeat = primaryTheme.themeHeat
    stock.themeLevel = primaryTheme.themeLevel

    const hotness = dataLayer.getStockHotness?.(stock.code)
    if (hotness !== undefined) stock.hotness = hotness

    const tags = dataLayer.getStockTags?.(stock.code)
    if (tags) stock.tags = tags

    const reason = dataLayer.getStockReason?.(stock.code)
    if (reason) stock.reason = reason

    const isNew = dataLayer.getStockIsNew?.(stock.code)
    if (isNew !== undefined) stock.isNew = isNew

    const limitUp = dataLayer.getLimitUpData?.(stock.code)
    if (limitUp) {
      stock.firstZtTime = limitUp.firstZtTime
      stock.lastZtTime = limitUp.lastZtTime
      stock.boardHeight = limitUp.boardHeight
      stock.highDays = limitUp.highDays
    }
  }

  private projectStock(stock: any): any {
    const {
      reviewAuthority: _reviewAuthority,
      reviewRole: _reviewRole,
      tradeability: _tradeability,
      chaseRisk: _chaseRisk,
      ...merged
    } = stock

    const themes = dataLayer.getStockThemes(stock.code) || []
    merged.themes = themes
    const primaryTheme = resolvePrimaryStockTheme(themes)
    merged.mainTheme = primaryTheme.mainTheme
    merged.themeHeat = primaryTheme.themeHeat
    merged.themeLevel = primaryTheme.themeLevel

    const realtimeQuote = dataLayer.getQuote(stock.code)
    const realtimeSpeed = Number(realtimeQuote?.speed)
    const hasRealtimeSpeed = Number.isFinite(realtimeSpeed)
    if (hasRealtimeSpeed) {
      merged.speed = realtimeSpeed
    }

    const jxbkStock = dataLayer.getJxbkStock(stock.code)
    if (jxbkStock) {
      if (!hasRealtimeSpeed) {
        merged.speed = jxbkStock.speed
      }
      merged.leadTimes = jxbkStock.leadTimes
      merged.leadStatus = jxbkStock.leadStatus
      merged.lianbanStr = jxbkStock.lianban
      merged.bigMoney300 = jxbkStock.bigMoney300
      merged.popularity = jxbkStock.popularity
      merged.popularityChange = jxbkStock.popularityChange
      merged.institutionBuy = jxbkStock.institutionBuy
      merged.mainBuy = jxbkStock.mainBuy
      merged.mainSell = jxbkStock.mainSell
      merged.fengdan = jxbkStock.fengdan
      merged.maxFengdan = jxbkStock.maxFengdan
      merged.cirMV = jxbkStock.cirMV
    }

    const leaderRecord = dataLayer.getLeaderByCode(stock.code)
    if (leaderRecord) {
      merged.reviewAuthority = leaderRecord.authority
      merged.reviewRole = leaderRecord.primaryRole
      merged.tradeability = leaderRecord.tradeability
      merged.chaseRisk = leaderRecord.chaseRisk
    }

    const stockTags = dataLayer.getStockTags?.(stock.code)
    if (stockTags) merged.tags = stockTags

    const stockReason = dataLayer.getStockReason?.(stock.code)
    if (stockReason) merged.reason = stockReason

    const limitUpData = dataLayer.getLimitUpData(stock.code)
    if (limitUpData) {
      merged.fengdan = limitUpData.fengdan ?? merged.fengdan
      merged.maxFengdan = limitUpData.maxFengdan ?? merged.maxFengdan
      merged.leadStatus = limitUpData.leadStatus ?? merged.leadStatus
      merged.leadTimes = limitUpData.leadTimes ?? merged.leadTimes
      merged.lianbanStr = limitUpData.lianbanStr ?? merged.lianbanStr
      merged.firstZtTime = limitUpData.firstZtTime ?? merged.firstZtTime
      merged.lastZtTime = limitUpData.lastZtTime ?? merged.lastZtTime
      merged.reason = limitUpData.reason ?? merged.reason
      merged.tags = limitUpData.tags ?? merged.tags
      merged.isNew = limitUpData.isNew ?? merged.isNew
    }

    merged.continuousDays = this.resolveContinuousDays(merged, jxbkStock, limitUpData, leaderRecord)
    return merged
  }

  private parseContinuousDays(value?: string | number | null): number | null {
    if (typeof value === 'number' && Number.isFinite(value) && value > 0) return value
    if (!value) return null

    const text = String(value)
    if (text.includes('首板')) return 1

    const match = text.match(/(\d+)/)
    if (!match) return null

    const parsed = Number(match[1])
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null
  }

  private resolveContinuousDays(
    stock: any,
    jxbkStock: any,
    limitUpData: any,
    leaderRecord: ReturnType<typeof dataLayer.getLeaderByCode>,
  ): number {
    const candidates = [
      leaderRecord?.continuousDays,
      limitUpData?.highDays,
      this.parseContinuousDays(limitUpData?.lianbanStr),
      this.parseContinuousDays(stock.lianbanStr),
      this.parseContinuousDays(jxbkStock?.lianban),
      this.parseContinuousDays(stock.highDays),
      this.parseContinuousDays(stock.continuousDays),
    ]

    const resolved = candidates.find(
      (value) => typeof value === 'number' && Number.isFinite(value) && value > 0,
    )

    return resolved ?? 1
  }
}

export const extraDataProjector = new ExtraDataProjector()
