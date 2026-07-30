import { dataLayer } from '../DataLayer'
import { themeHeatFeed } from '../theme/ThemeHeatFeed'
import type { SnapshotBuildContext } from './builders'

export type StartupSnapshotContext = Omit<
  SnapshotBuildContext,
  'stocks' | 'depth10ByCode' | 'recentTicksByCode' | 'l2SummaryByCode'
>

export function getCurrentSnapshotBuildContext(): SnapshotBuildContext {
  const themeHeatSnapshot = themeHeatFeed.getSnapshot()
  const quoteSource = (themeHeatSnapshot?.sources?.quotes as any)?.source
  const fundSource = (themeHeatSnapshot?.sources?.funds as any)?.source

  return {
    stocks: dataLayer.getStocks() || [],
    depth10ByCode: dataLayer.getDepth10Map(),
    recentTicksByCode: dataLayer.getRecentTicksMap(),
    l2SummaryByCode: dataLayer.getL2SummaryMap(),
    breathData: dataLayer.getBreathData(),
    marketData: dataLayer.getBreathMarketData(),
    hotThemes: dataLayer.getHotThemes() || [],
    themeHeatFactors: (themeHeatSnapshot?.factors || []).map((factor) => ({
      ...factor,
      metadata: {
        ...factor.metadata,
        quoteSource,
        fundSource,
      },
    })),
    rotationAnalysis: dataLayer.getCurrentRotation(),
    breathHistory: dataLayer.getBreathHistory(),
    breathFactors: dataLayer.getBreathFactors(),
    marketMode: dataLayer.getMarketMode(),
    stocksVersion: dataLayer.getVersion().stocks,
  }
}

export function getCurrentStartupSnapshotContext(): StartupSnapshotContext {
  const {
    stocks: _stocks,
    depth10ByCode: _depth,
    recentTicksByCode: _ticks,
    l2SummaryByCode: _l2,
    ...context
  } = getCurrentSnapshotBuildContext()
  return context
}
