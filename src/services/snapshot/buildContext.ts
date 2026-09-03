import { dataLayer } from '../DataLayer'
import { themeHeatFeed } from '../theme/ThemeHeatFeed'
import { getBackendRotationSummaryRaw } from '../theme/ThemeRuntimeCoordinator'
import type { SnapshotBuildContext } from './builders'

export type StartupSnapshotContext = Omit<
  SnapshotBuildContext,
  'stocks' | 'depth10ByCode' | 'recentTicksByCode' | 'l2SummaryByCode'
>

export function getCurrentSnapshotBuildContext(): SnapshotBuildContext {
  const themeHeatSnapshot = themeHeatFeed.getSnapshot()
  const quoteSource = (themeHeatSnapshot?.sources?.quotes as any)?.source
  const fundSource = (themeHeatSnapshot?.sources?.funds as any)?.source
  // B9（2026-09 design §4.2 残留歧义修正）：context 行每帧重建、不会随 collector 行累积
  // 消亡，必须携带口径标记供消费端按 design §4.2 分支回退；快照缺失 factorVersion 时
  // 按当前 v2 口径兜底标记。hotThemes 行 heatLevel 从字符串档位标签数值化（来源
  // heatLevelScore，无值不写 key），字符串标签不再进入落库 sector row。
  const heatFactorVersion = themeHeatSnapshot?.factorVersion || 'theme-market-v2'

  return {
    stocks: dataLayer.getStocks() || [],
    depth10ByCode: dataLayer.getDepth10Map(),
    recentTicksByCode: dataLayer.getRecentTicksMap(),
    l2SummaryByCode: dataLayer.getL2SummaryMap(),
    breathData: dataLayer.getBreathData(),
    marketData: dataLayer.getBreathMarketData(),
    hotThemes: (dataLayer.getHotThemes() || []).map((theme: any) => {
      // 旧字符串档位标签（'热门'/'冰' 等）必须剔除：无数值 heatLevelScore 时不写
      // heatLevel key（tri-state），有值时写数值——字符串标签不再进入落库 sector row。
      const { heatLevel: _legacyHeatLevel, ...themeRest } = theme || {}
      return {
        ...themeRest,
        ...(typeof theme?.heatLevelScore === 'number' && Number.isFinite(theme.heatLevelScore)
          ? { heatLevel: theme.heatLevelScore }
          : {}),
        metadata: {
          ...(theme?.metadata || {}),
          factorVersion: heatFactorVersion,
        },
      }
    }),
    themeHeatFactors: (themeHeatSnapshot?.factors || []).map((factor) => ({
      ...factor,
      metadata: {
        ...factor.metadata,
        quoteSource,
        fundSource,
        factorVersion: heatFactorVersion,
      },
    })),
    rotationAnalysis: dataLayer.getCurrentRotation(),
    // 原始后端引擎 rotationSummary（camelCase 全字段）；快照构建原样透传，不重序列化
    backendRotationSummary: getBackendRotationSummaryRaw(),
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
