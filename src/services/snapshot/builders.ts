import { getRankTrendAnalysis } from '../rankTrend/compat'
import { resolveSnapshotFeatureCoverage } from './snapshotQualityGate'
import { StockUtils } from '../../utils/common'
import {
  computeResonanceScore,
  normalizeResonanceIntensity,
} from '../candidate/TradingPoolAnalysisService'
import type { Depth10Book, DepthLevel, L2Summary, TickTrade } from '../../types'
import type {
  SnapshotFrameRow,
  SnapshotRecord,
  SnapshotSectorEntityType,
  SnapshotSectorRow,
  SnapshotStockRow,
  SnapshotType,
} from './types'

export interface SnapshotBuildContext {
  stocks: any[]
  depth10ByCode?: Map<string, Depth10Book>
  recentTicksByCode?: Map<string, TickTrade[]>
  l2SummaryByCode?: Map<string, L2Summary>
  breathData: any
  marketData: any
  hotThemes: any[]
  themeHeatFactors?: any[]
  rotationAnalysis: any
  breathHistory: any[]
  breathFactors: any[]
  marketMode: 'hot' | 'full'
  stocksVersion: number
}

export function getSnapshotRankChange(stock: any): number {
  return Math.round(stock?.rankTrend?.meta?.change ?? stock?.rankChange ?? 0)
}

export function getSnapshotMacdCross(stock: any): string {
  return (
    stock?.rankTrend?.technical?.macd?.cross ??
    stock?.technicalIndicators?.macdCross ??
    stock?.macdCross ??
    ''
  )
}

function getMergedStockRankTrendView(stock: any) {
  const rankTrend = getRankTrendAnalysis(stock)

  return {
    rankTrend,
    ma5: rankTrend?.technical.movingAverage.ma5 ?? 0,
    ma10: rankTrend?.technical.movingAverage.ma10 ?? 0,
    maTrend: rankTrend?.technical.movingAverage.trend ?? 'steady',
    macd: rankTrend?.technical.macd.dif ?? 0,
    macdSignal: rankTrend?.technical.macd.dea ?? 0,
    macdHistogram: rankTrend?.technical.macd.histogram ?? 0,
    macdCross: rankTrend?.technical.macd.cross ?? 'none',
    directionSignal: rankTrend?.technical.signals.direction.signal ?? 'none',
    directionConfidence: rankTrend?.technical.signals.direction.confidence ?? 0,
    accelerationSignal: rankTrend?.technical.signals.acceleration.signal ?? 'none',
    accelerationConfidence: rankTrend?.technical.signals.acceleration.confidence ?? 0,
    crossSignal: rankTrend?.technical.signals.zeroCross.signal ?? 'none',
    crossConfidence: rankTrend?.technical.signals.zeroCross.confidence ?? 0,
    finalSignal: rankTrend?.decision.final.signal ?? 'none',
    finalConfidence: rankTrend?.decision.final.confidence ?? 0,
    jumpDirection: rankTrend?.jump?.direction ?? 'none',
    jumpConfidence: rankTrend?.jump?.confidence ?? 0,
    rankChange: rankTrend ? Math.round(rankTrend.meta.change) : 0,
  }
}

function clonePlainObject<T extends Record<string, any> | null | undefined>(value: T): T {
  if (!value || typeof value !== 'object') return value
  return JSON.parse(JSON.stringify(value))
}

function buildLimitSummary(limitData: {
  continuousBoards?: Record<string, any> | null
  zhaban?: Record<string, any> | null
  yesterdayZt?: Record<string, any> | null
  thsPools?: Record<string, any> | null
}) {
  return {
    continuousBoards: clonePlainObject(limitData.continuousBoards || null),
    zhaban: clonePlainObject(limitData.zhaban || null),
    yesterdayZt: clonePlainObject(limitData.yesterdayZt || null),
    thsPools: clonePlainObject(limitData.thsPools || null),
  }
}

function toThemeRefs(themes: any): Array<{
  id?: string
  name?: string
  heatScore?: number
  role?: string
  exposureWeight?: number
  themeContribution?: number
  riskPenalty?: number
}> {
  return (Array.isArray(themes) ? themes : [])
    .slice(0, 10)
    .map((theme: any) => ({
      id: theme?.id,
      name: theme?.name,
      heatScore: theme?.heatScore,
      role: typeof theme?.role === 'string' ? theme.role : undefined,
      exposureWeight: Number.isFinite(Number(theme?.exposureWeight)) ? Number(theme.exposureWeight) : undefined,
      themeContribution: Number.isFinite(Number(theme?.themeContribution)) ? Number(theme.themeContribution) : undefined,
      riskPenalty: Number.isFinite(Number(theme?.riskPenalty)) ? Number(theme.riskPenalty) : undefined,
    }))
    .filter((theme) => Boolean(theme.name || theme.id))
}

type SnapshotThemeRef = ReturnType<typeof toThemeRefs>[number]

function themeRefScore(theme: SnapshotThemeRef): number {
  const contribution = finiteNumberOrUndefined(theme.themeContribution) ?? -1
  const heat = finiteNumberOrUndefined(theme.heatScore) ?? -1
  const exposure = finiteNumberOrUndefined(theme.exposureWeight) ?? -1
  return contribution * 10000 + heat * 100 + exposure
}

function primaryThemeRef(themes: SnapshotThemeRef[]): SnapshotThemeRef | undefined {
  return themes
    .map((theme, index) => ({ theme, score: themeRefScore(theme), index }))
    .sort((left, right) => right.score - left.score || left.index - right.index)[0]?.theme
}

function toThemeRiskFlags(theme: SnapshotThemeRef | undefined): string[] {
  if (!theme) return []
  const flags: string[] = []
  if (Number.isFinite(Number(theme.riskPenalty)) && Number(theme.riskPenalty) > 0) {
    flags.push(`riskPenalty:${Number(theme.riskPenalty)}`)
  }
  return flags
}

function finiteNumberOrUndefined(value: unknown): number | undefined {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : undefined
}

function finiteNumberOrNull(value: unknown): number | null | undefined {
  if (value === null) return null
  if (value === undefined) return undefined
  return finiteNumberOrUndefined(value)
}

function compactThemeFactorMetadata(
  payload: Record<string, any>,
  includesFormalFunds = true,
): Record<string, any> | undefined {
  const factorKeys = [
    'momentumScore',
    'breadthScore',
    ...(includesFormalFunds ? ['fundScore'] : []),
    'leadershipScore',
    'correlationScore',
    'crowdingRisk',
    'persistenceScore',
    'rotationState',
    'qualityFlags',
  ]
  const themeFactor = Object.fromEntries(
    factorKeys
      .filter((key) => payload[key] !== undefined)
      .map((key) => [key, clonePlainObject(payload[key])]),
  )
  return Object.keys(themeFactor).length > 0 ? { themeFactor } : undefined
}

function buildSectorMetadata(
  payload: Record<string, any>,
  includesFormalFunds = true,
): Record<string, any> | null {
  const sourceMetadata = clonePlainObject(payload.metadata as Record<string, any> | null) || {}
  if (!includesFormalFunds) {
    delete sourceMetadata.fundSource
    delete sourceMetadata.moneyFlowSource
    if (sourceMetadata.themeFactor && typeof sourceMetadata.themeFactor === 'object') {
      delete sourceMetadata.themeFactor.fundScore
      if (!Object.keys(sourceMetadata.themeFactor).length) delete sourceMetadata.themeFactor
    }
  }
  const metadata = {
    ...sourceMetadata,
    ...(compactThemeFactorMetadata(payload, includesFormalFunds) || {}),
  }
  return Object.keys(metadata).length > 0 ? metadata : null
}

function getThemeFactorPayload(payload: Record<string, any>): Record<string, any> {
  const metadata = payload.metadata
  const fromMetadata =
    metadata && typeof metadata === 'object' && (metadata as Record<string, any>).themeFactor
  return fromMetadata && typeof fromMetadata === 'object'
    ? { ...(fromMetadata as Record<string, any>), ...payload }
    : payload
}

function getHotlistSourceStock(sourceStocksByCode: Map<string, any> | undefined, code: string) {
  if (!sourceStocksByCode || !code) return null
  return sourceStocksByCode.get(code) || null
}

function getRawSignalValue(item: any, key: 'direction' | 'acceleration' | 'cross' | 'final') {
  const node = item?.signals?.[key]
  return {
    signal: typeof node?.signal === 'string' ? node.signal : 'none',
    confidence: Number(node?.confidence) || 0,
  }
}

function computeResonanceFromSignals(signals: {
  macdCross: string
  jumpDirection: string
  jumpConfidence: number
  directionSignal: string
  directionConfidence: number
  accelerationSignal: string
  accelerationConfidence: number
  crossSignal: string
  crossConfidence: number
}): number {
  const score = computeResonanceScore({
    macdCross: signals.macdCross as 'golden' | 'death' | null,
    jumpDirection: signals.jumpDirection as 'buy' | 'sell' | null,
    jumpConfidence: signals.jumpConfidence,
    directionSignal: signals.directionSignal as string | null,
    directionConfidence: signals.directionConfidence,
    accelerationSignal: signals.accelerationSignal as string | null,
    accelerationConfidence: signals.accelerationConfidence,
    zeroCrossSignal: signals.crossSignal as string | null,
    zeroCrossConfidence: signals.crossConfidence,
  })
  return normalizeResonanceIntensity(score.totalScore).pct
}

function getCompactSignalColumns(item: any, sourceStock?: any) {
  if (sourceStock) {
    const rankTrendView = getMergedStockRankTrendView(sourceStock)
    const signals = {
      rankChange: Number(rankTrendView.rankChange) || 0,
      directionSignal: rankTrendView.directionSignal || 'none',
      directionConfidence: Number(rankTrendView.directionConfidence) || 0,
      accelerationSignal: rankTrendView.accelerationSignal || 'none',
      accelerationConfidence: Number(rankTrendView.accelerationConfidence) || 0,
      crossSignal: rankTrendView.crossSignal || 'none',
      crossConfidence: Number(rankTrendView.crossConfidence) || 0,
      finalSignal: rankTrendView.finalSignal || 'none',
      finalConfidence: Number(rankTrendView.finalConfidence) || 0,
      jumpDirection: rankTrendView.jumpDirection || 'none',
      jumpConfidence: Number(rankTrendView.jumpConfidence) || 0,
      macdCross: rankTrendView.macdCross || 'none',
    }
    return { ...signals, resonanceIntensity: computeResonanceFromSignals(signals) }
  }

  const direction = getRawSignalValue(item, 'direction')
  const acceleration = getRawSignalValue(item, 'acceleration')
  const cross = getRawSignalValue(item, 'cross')
  const final = getRawSignalValue(item, 'final')

  const jumpDirection = typeof item?.jumpDirection === 'string' ? item.jumpDirection : 'none'
  const jumpConfidence = Number.isFinite(Number(item?.jumpConfidence)) ? Number(item.jumpConfidence) : 0
  const macdCross = typeof item?.macdCross === 'string' ? item.macdCross : 'none'

  const signals = {
    rankChange: Number(item?.rankChange) || 0,
    directionSignal: direction.signal,
    directionConfidence: direction.confidence,
    accelerationSignal: acceleration.signal,
    accelerationConfidence: acceleration.confidence,
    crossSignal: cross.signal,
    crossConfidence: cross.confidence,
    finalSignal: final.signal,
    finalConfidence: final.confidence,
    jumpDirection,
    jumpConfidence,
    macdCross,
  }
  return { ...signals, resonanceIntensity: computeResonanceFromSignals(signals) }
}

function buildRotationSummary(rotationAnalysis: any): Record<string, any> | null {
  if (!rotationAnalysis) return null
  return {
    marketPhase: rotationAnalysis.marketPhase || '',
    rotationSpeed: rotationAnalysis.rotationSpeed || 0,
    suggestion: rotationAnalysis.summary?.suggestion || rotationAnalysis.suggestion || '',
  }
}

function toDepthLevels(levels: any): DepthLevel[] {
  return (Array.isArray(levels) ? levels : [])
    .slice(0, 10)
    .map((level: any) => ({
      price: Number(level?.price) || 0,
      volume: Number(level?.volume) || 0,
    }))
}

function cloneDepth10Book(book?: Depth10Book | null): Depth10Book | undefined {
  if (!book?.code) return undefined
  return {
    code: book.code,
    bids: toDepthLevels(book.bids),
    asks: toDepthLevels(book.asks),
    sourceTs: Number(book.sourceTs) || 0,
    seq: Number(book.seq) || 0,
    timestamp: Number(book.timestamp) || 0,
  }
}

function resolveL2Summary(context: SnapshotBuildContext | undefined, stock: any): Partial<L2Summary> {
  const byCode = context?.l2SummaryByCode?.get?.(stock?.code)
  return {
    bid1Price: Number(byCode?.bid1Price ?? stock?.bid1Price) || 0,
    bid1Volume: Number(byCode?.bid1Volume ?? stock?.bid1Volume) || 0,
    ask1Price: Number(byCode?.ask1Price ?? stock?.ask1Price) || 0,
    ask1Volume: Number(byCode?.ask1Volume ?? stock?.ask1Volume) || 0,
    spread: Number(byCode?.spread ?? stock?.spread) || 0,
    bid10Total: Number(byCode?.bid10Total ?? stock?.bid10Total) || 0,
    ask10Total: Number(byCode?.ask10Total ?? stock?.ask10Total) || 0,
    depthImbalance: Number(byCode?.depthImbalance ?? stock?.depthImbalance) || 0,
    tickBuyVolume: Number(byCode?.tickBuyVolume ?? stock?.tickBuyVolume) || 0,
    tickSellVolume: Number(byCode?.tickSellVolume ?? stock?.tickSellVolume) || 0,
    tickBuyCount: Number(byCode?.tickBuyCount ?? stock?.tickBuyCount) || 0,
    tickSellCount: Number(byCode?.tickSellCount ?? stock?.tickSellCount) || 0,
    lastTradePrice: Number(byCode?.lastTradePrice ?? stock?.lastTradePrice) || 0,
    lastTradeVolume: Number(byCode?.lastTradeVolume ?? stock?.lastTradeVolume) || 0,
  }
}

export function buildSnapshotHotlistItem(
  stock: any,
  index: number,
  totalStocks: number,
  context?: SnapshotBuildContext,
) {
  // 单只股票在这里被压成各类快照共享的“热榜标准项”，
  // 后续 QuantBoard 研究链路、复盘、导出都默认依赖这套字段。
  const l2Summary = resolveL2Summary(context, stock)
  const depth10 = cloneDepth10Book(context?.depth10ByCode?.get?.(stock?.code))
  return {
    code: stock.code,
    name: stock.name,
    avgRank: stock.avgRank,
    avgRankNum: stock.avgRankNum,
    compRank: stock.compRank,
    platforms: stock.platforms,
    emRank: stock.emRank,
    thsRank: stock.thsRank,
    kplRank: stock.kplRank,
    tdxRank: stock.tdxRank,
    xqRank: stock.xqRank,
    clsRank: stock.clsRank,
    tgbRank: stock.tgbRank,
    dzhRank: stock.dzhRank,
    rank: index + 1,
    price: stock.price,
    change: stock.change,
    volume: stock.volume,
    turnover: stock.turnover,
    turnoverRate: stock.turnoverRate,
    totalMV: stock.totalMV,
    cirMV: stock.cirMV,
    ...({
      zlje: stock.zlje,
      zljzb: stock.zljzb,
      cddje: stock.cddje,
      cddjzb: stock.cddjzb,
      moneyFlowSource: stock.moneyFlowSource,
      moneyFlowEstimated: stock.moneyFlowEstimated,
      capitalFlowSource: stock.capitalFlowSource,
      capitalFlowConfidence: stock.capitalFlowConfidence,
      money_flow_source: stock.moneyFlowSource,
      money_flow_estimated: stock.moneyFlowEstimated,
      capital_flow_source: stock.capitalFlowSource,
      capital_flow_confidence: stock.capitalFlowConfidence,
    }),
    pe: stock.pe,
    pb: stock.pb,
    volumeRatio: stock.volumeRatio,
    speed: stock.speed,
    leadStatus: stock.leadStatus,
    leadTimes: stock.leadTimes,
    lianbanStr: stock.lianbanStr,
    fengdan: stock.fengdan,
    maxFengdan: stock.maxFengdan,
    popularity: stock.popularity,
    popularityChange: stock.popularityChange,
    institutionBuy: stock.institutionBuy,
    bigMoney300: stock.bigMoney300,
    themes: toThemeRefs(stock.themes),
    isNew: stock.isNew,
    reason: stock.reason,
    firstZtTime: stock.firstZtTime,
    lastZtTime: stock.lastZtTime,
    boardHeight: stock.boardHeight,
    highDays: stock.highDays,
    hotness: stock.hotness,
    mainTheme: stock.mainTheme,
    themeHeat: stock.themeHeat,
    themeLevel: stock.themeLevel,
    depth10,
    ...l2Summary,
  }
}

export function buildIntradaySnapshotMetadata(
  hotlist: Array<Record<string, unknown>>,
  timestamp: number,
  marketMode: 'hot' | 'full',
  dataVersion: number,
  totalStocks: number,
) {
  const featureCoverage = resolveSnapshotFeatureCoverage({
    metadata: { version: '2.1' },
    hotlist,
  })

  return {
    version: '2.1',
    featureCoverage,
    totalStocks,
    marketMode,
    dataVersion,
    timestamp,
  }
}

export function buildIntradaySnapshotBase(
  context: SnapshotBuildContext,
  snapshotTime: Date,
  limit: number,
) {
  // 一刻与半小时快照共用这套主体结构，
  // 改字段时要同步评估 QuantBoard 研究链路、真龙复盘和导出兼容性。
  const timestamp = snapshotTime.getTime()
  const hotlist = context.stocks
    .slice(0, limit)
    .map((stock, index) => buildSnapshotHotlistItem(stock, index, context.stocks.length, context))
  const continuousBoards = {
    board1: context.marketData?.limitData?.yiban || 0,
    board2: context.marketData?.limitData?.erban || 0,
    board3: context.marketData?.limitData?.sanban || 0,
    board4plus: context.marketData?.limitData?.sibanPlus || 0,
  }
  const zhaban = {
    count: context.marketData?.zhaban?.count || 0,
    rate: context.marketData?.zhaban?.rate || 0,
    fengbanRate: context.marketData?.zhaban?.fengbanRate || 0,
  }

  return {
    timestamp,
    hotlist,
    sectors: context.hotThemes.map((theme: any) => ({
      ...theme,
      code: theme.id,
      strength: theme.heatScore,
    })),
    sentiment: {
      overall: context.breathData?.overall || 50,
      phase: context.breathData?.phase || 'start',
      phaseName: context.breathData?.phaseName || '启动',
      emotionValue: context.marketData?.emotionValue || 50,
    },
    moneyFlow: {
      main: context.marketData?.moneyFlow?.main || 0,
      retail: context.marketData?.moneyFlow?.retail || 0,
    },
    marketStats: {
      upCount: context.marketData?.upCount || 0,
      downCount: context.marketData?.downCount || 0,
      ztCount: context.marketData?.ztCount || 0,
      dtCount: context.marketData?.dtCount || 0,
      totalAmo: context.marketData?.totalAmo || 0,
    },
    limitSummary: buildLimitSummary({
      continuousBoards,
      zhaban,
      thsPools: clonePlainObject(context.marketData?.thsLimitUpPools || null),
    }),
    metadata: buildIntradaySnapshotMetadata(
      hotlist,
      timestamp,
      context.marketMode,
      context.stocksVersion,
      context.stocks.length,
    ),
  }
}

export function buildHourlySnapshot(context: SnapshotBuildContext, snapshotTime: Date) {
  // 整点快照在日内基础上补充涨停池、炸板、连板统计，承载“盘中阶段总结”用途。
  const timestamp = snapshotTime.getTime()
  const hotlist = context.stocks
    .slice(0, 100)
    .map((stock, index) => buildSnapshotHotlistItem(stock, index, context.stocks.length, context))
  const continuousBoards = {
    board1: context.marketData?.limitData?.yiban || 0,
    board2: context.marketData?.limitData?.erban || 0,
    board3: context.marketData?.limitData?.sanban || 0,
    board4plus: context.marketData?.limitData?.sibanPlus || 0,
  }
  const zhaban = {
    count: context.marketData?.zhaban?.count || 0,
    rate: context.marketData?.zhaban?.rate || 0,
    fengbanRate: context.marketData?.zhaban?.fengbanRate || 0,
  }

  return {
    timestamp,
    metadata: buildIntradaySnapshotMetadata(
      hotlist,
      timestamp,
      context.marketMode,
      context.stocksVersion,
      context.stocks.length,
    ),
    hotlist,
    sectors: context.hotThemes.map((theme: any) => ({
      ...theme,
      code: theme.id,
      strength: theme.heatScore,
    })),
    sentiment: {
      overall: context.breathData?.overall || 50,
      phase: context.breathData?.phase || 'start',
      phaseName: context.breathData?.phaseName || '启动',
      emotionValue: context.marketData?.emotionValue || 50,
    },
    marketStats: {
      upCount: context.marketData?.upCount || 0,
      downCount: context.marketData?.downCount || 0,
      ztCount: context.marketData?.ztCount || 0,
      dtCount: context.marketData?.dtCount || 0,
      totalAmo: context.marketData?.totalAmo || 0,
      zhabanRate: context.marketData?.zhaban?.rate || 0,
    },
    zhaban,
    moneyFlow: {
      main: context.marketData?.moneyFlow?.main || 0,
      retail: context.marketData?.moneyFlow?.retail || 0,
      cddje: context.marketData?.cddje || 0,
    },
    continuousBoards,
    limitSummary: buildLimitSummary({
      continuousBoards,
      zhaban,
      thsPools: clonePlainObject(context.marketData?.thsLimitUpPools || null),
    }),
    rotationSummary: buildRotationSummary(context.rotationAnalysis),
  }
}

export function buildDailySnapshot(context: SnapshotBuildContext, snapshotTime: Date = new Date()): any {
  // 日级快照是信息最全的一层，承担收盘归档与云端 day bundle 的主体数据。
  const timestamp = snapshotTime.getTime()

  const sentiment = {
    overall: context.breathData?.overall || 0,
    phase: context.breathData?.phase || '',
    phaseName: context.breathData?.phaseName || '',
    riskLevel: context.breathData?.riskLevel || '',
    suggestion: context.breathData?.suggestion || '',
    history: context.breathHistory,
    factors: context.breathFactors,
  }

  const marketStats = {
    upCount: context.marketData?.upCount || 0,
    downCount: context.marketData?.downCount || 0,
    ztCount: context.marketData?.ztCount || 0,
    dtCount: context.marketData?.dtCount || 0,
    totalAmo: context.marketData?.totalAmo || 0,
    volumeRatio: context.marketData?.volumeRatio || 0,
    emotionValue: context.marketData?.emotionValue || 0,
    emotionStatus: context.marketData?.emotionStatus || '震荡',
  }

  const limitData = {
    continuousBoards: {
      board1: context.marketData?.limitData?.yiban ?? 0,
      board2: context.marketData?.limitData?.erban ?? 0,
      board3: context.marketData?.limitData?.sanban ?? 0,
      board4plus: context.marketData?.limitData?.sibanPlus ?? 0,
    },
    zhaban: {
      count: context.marketData?.zhaban?.count || 0,
      rate: context.marketData?.zhaban?.rate || 0,
      fengbanRate: context.marketData?.zhaban?.fengbanRate || 0,
    },
    yesterdayZt: {
      total: context.marketData?.yesterdayLimit?.total || 0,
      dtCount: context.marketData?.yesterdayLimit?.dtCount || 0,
      bigLossCount: context.marketData?.yesterdayLimit?.bigLossCount || 0,
      redCount: context.marketData?.yesterdayLimit?.redCount || 0,
      greenCount: context.marketData?.yesterdayLimit?.greenCount || 0,
      avgChange: context.marketData?.yesterdayLimit?.avgChange || 0,
      maxChange: context.marketData?.yesterdayLimit?.maxChange || 0,
      minChange: context.marketData?.yesterdayLimit?.minChange || 0,
    },
    thsPools: clonePlainObject(context.marketData?.thsLimitUpPools || null),
  }
  const limitSummary = buildLimitSummary(limitData)

  const moneyFlow = {
    main: context.marketData?.moneyFlow?.main || 0,
    retail: context.marketData?.moneyFlow?.retail || 0,
    cddje: context.marketData?.cddje || 0,
    cddjzb: context.marketData?.cddjzb || 0,
  }

  const indices = {
    sh: context.marketData?.indices?.sh?.change || 0,
    hs300: context.marketData?.indices?.hs300?.change || 0,
    zz500: context.marketData?.indices?.zz500?.change || 0,
    zz1000: context.marketData?.indices?.zz1000?.change || 0,
    largeCapChange: context.marketData?.largeCapChange || 0,
    microCapChange: context.marketData?.microCapChange || 0,
  }

  const sectors = [...context.hotThemes]
    .sort((a, b) => b.heatScore - a.heatScore)
    .map((theme: any) => ({
      ...theme,
      code: theme.id,
      strength: theme.heatScore,
    }))

  const hotlist = [...context.stocks]
    .sort((a: any, b: any) => (a.compRank || 999) - (b.compRank || 999))
    .map((stock: any, index: number) => buildSnapshotHotlistItem(stock, index, context.stocks.length, context))

  return {
    timestamp,
    type: 'daily',
    sentiment,
    market: marketStats,
    indices,
    moneyFlow,
    limit: limitData.continuousBoards,
    zhaban: limitData.zhaban,
    yesterdayZt: limitData.yesterdayZt,
    limitSummary,
    sectors,
    hotlist,
    rotationSummary: buildRotationSummary(context.rotationAnalysis),
    stats: {
      totalStocks: context.stocks.length,
      totalSectors: sectors.length,
      timestamp,
    },
  }
}

export function buildSnapshotFrameRow(record: SnapshotRecord): SnapshotFrameRow | null {
  if (record.type === 'five_minute') return null
  const payload = (record.payload && typeof record.payload === 'object' ? record.payload : {}) as Record<string, any>
  const marketStats = clonePlainObject((payload.marketStats || payload.market) as Record<string, any> | null)
  const payloadLimitSummary =
    payload.limitSummary && typeof payload.limitSummary === 'object'
      ? (payload.limitSummary as Record<string, any>)
      : {}
  const limitSummary = buildLimitSummary({
    continuousBoards: (payloadLimitSummary.continuousBoards || payload.limit || payload.continuousBoards) as
      | Record<string, any>
      | null,
    zhaban: (payloadLimitSummary.zhaban || payload.zhaban) as Record<string, any> | null,
    yesterdayZt: (payloadLimitSummary.yesterdayZt || payload.yesterdayZt) as Record<string, any> | null,
    thsPools: (payloadLimitSummary.thsPools || payload.thsPools || payload.thsLimitUpPools) as
      | Record<string, any>
      | null,
  })

  const stockRowCount = Array.isArray(payload.hotlist) ? payload.hotlist.length : 0
  const sectorCount = Array.isArray(payload.sectors) ? payload.sectors.length : 0
  const hotThemeCount = Array.isArray(payload.hotThemes) ? payload.hotThemes.length : 0
  const rotationLineCount = Array.isArray(payload.rotation?.mainLines)
    ? payload.rotation.mainLines.length
    : Array.isArray(payload.rotationSummary?.mainLines)
      ? payload.rotationSummary.mainLines.length
      : 0

  return {
    id: record.id,
    snapshotId: record.id,
    type: record.type,
    tradingDate: record.tradingDate,
    slotTime: record.slotTime,
    timestamp: record.timestamp,
    displayKey: record.displayKey,
    captureMode: record.captureMode,
    source: record.source,
    qualityFlags: [...record.qualityFlags],
    delayMs: record.delayMs,
    metadata: clonePlainObject(payload.metadata as Record<string, any> | null) || null,
    marketStats: marketStats || null,
    sentiment: clonePlainObject(payload.sentiment as Record<string, any> | null) || null,
    moneyFlow: clonePlainObject(payload.moneyFlow as Record<string, any> | null) || null,
    indices: clonePlainObject(payload.indices as Record<string, any> | null) || null,
    limitSummary,
    rotationSummary:
      clonePlainObject((payload.rotationSummary || payload.rotation) as Record<string, any> | null) || null,
    stockRowCount,
    sectorRowCount: sectorCount + hotThemeCount + rotationLineCount,
  }
}

export function buildSnapshotStockRows(
  record: SnapshotRecord,
  sourceStocksByCode?: Map<string, any>,
): SnapshotStockRow[] {
  if (record.type === 'five_minute') return []
  const payload = (record.payload && typeof record.payload === 'object' ? record.payload : {}) as Record<string, any>
  const hotlist = Array.isArray(payload.hotlist) ? payload.hotlist : []

  return hotlist
    .filter((item: any) => item && item.code)
    .map((item: any, index: number) => {
      const sourceStock = getHotlistSourceStock(sourceStocksByCode, String(item.code || ''))
      const signalColumns = getCompactSignalColumns(item, sourceStock)
      const themes = toThemeRefs(item.themes)
      const primaryTheme = primaryThemeRef(themes)
      return {
        id: `${record.id}:${item.code}`,
        snapshotId: record.id,
        type: record.type as Exclude<SnapshotType, 'five_minute'>,
        tradingDate: record.tradingDate,
        slotTime: record.slotTime,
        timestamp: record.timestamp,
        captureMode: record.captureMode,
        source: record.source,
        code: String(item.code),
        name: String(item.name || item.code || ''),
        rank: Number(item.rank) || index + 1,
        compRank: Number(item.compRank) || Number(item.rank) || index + 1,
        platforms: Number(item.platforms) || 0,
        avgRank: typeof item.avgRank === 'string' ? item.avgRank : undefined,
        avgRankNum: Number(item.avgRankNum) || 0,
        emRank: Number(item.emRank) || 0,
        thsRank: Number(item.thsRank) || 0,
        kplRank: Number(item.kplRank) || 0,
        tdxRank: Number(item.tdxRank) || 0,
        xqRank: Number(item.xqRank) || 0,
        clsRank: Number(item.clsRank) || 0,
        tgbRank: Number(item.tgbRank) || 0,
        dzhRank: Number(item.dzhRank) || 0,
        price: Number(item.price) || 0,
        change: Number(item.change) || 0,
        volume: Number(item.volume) || 0,
        turnover: Number(item.turnover) || 0,
        turnoverRate: Number(item.turnoverRate) || 0,
        totalMV: Number(item.totalMV) || 0,
        cirMV: Number(item.cirMV) || 0,
        zlje: finiteNumberOrUndefined(item.zlje),
        zljzb: finiteNumberOrUndefined(item.zljzb),
        cddje: finiteNumberOrUndefined(item.cddje),
        cddjzb: finiteNumberOrUndefined(item.cddjzb),
        moneyFlowSource: item.moneyFlowSource,
        moneyFlowEstimated: item.moneyFlowEstimated,
        capitalFlowSource: item.capitalFlowSource,
        capitalFlowConfidence: item.capitalFlowConfidence,
        money_flow_source: item.money_flow_source ?? item.moneyFlowSource,
        money_flow_estimated: item.money_flow_estimated ?? item.moneyFlowEstimated,
        capital_flow_source: item.capital_flow_source ?? item.capitalFlowSource,
        capital_flow_confidence: item.capital_flow_confidence ?? item.capitalFlowConfidence,
        pe: Number(item.pe) || 0,
        pb: Number(item.pb) || 0,
        depth10: cloneDepth10Book(item.depth10),
        bid1Price: Number(item.bid1Price) || 0,
        bid1Volume: Number(item.bid1Volume) || 0,
        ask1Price: Number(item.ask1Price) || 0,
        ask1Volume: Number(item.ask1Volume) || 0,
        spread: Number(item.spread) || 0,
        bid10Total: Number(item.bid10Total) || 0,
        ask10Total: Number(item.ask10Total) || 0,
        depthImbalance: Number(item.depthImbalance) || 0,
        tickBuyVolume: Number(item.tickBuyVolume) || 0,
        tickSellVolume: Number(item.tickSellVolume) || 0,
        tickBuyCount: Number(item.tickBuyCount) || 0,
        tickSellCount: Number(item.tickSellCount) || 0,
        lastTradePrice: Number(item.lastTradePrice) || 0,
        lastTradeVolume: Number(item.lastTradeVolume) || 0,
        volumeRatio: Number(item.volumeRatio) || 0,
        speed: Number(item.speed) || 0,
        leadStatus: String(item.leadStatus || ''),
        leadTimes: Number(item.leadTimes) || 0,
        lianbanStr: String(item.lianbanStr || ''),
        fengdan: Number(item.fengdan) || 0,
        maxFengdan: Number(item.maxFengdan) || 0,
        popularity: Number(item.popularity) || 0,
        popularityChange: Number(item.popularityChange) || 0,
        institutionBuy: Number(item.institutionBuy) || 0,
        bigMoney300: Number(item.bigMoney300) || 0,
        themes,
        themeContribution: finiteNumberOrUndefined(primaryTheme?.themeContribution),
        themeRole: primaryTheme?.role,
        themeExposureWeight: finiteNumberOrUndefined(primaryTheme?.exposureWeight),
        themeRiskFlags: toThemeRiskFlags(primaryTheme),
        isNew: Boolean(item.isNew),
        reason: String(item.reason || ''),
        firstZtTime: String(item.firstZtTime || ''),
        lastZtTime: String(item.lastZtTime || ''),
        boardHeight: Number(item.boardHeight) || 0,
        highDays: Number(item.highDays) || 0,
        hotness: Number(item.hotness) || 0,
        mainTheme: typeof item.mainTheme === 'string' ? item.mainTheme : undefined,
        themeHeat: Number(item.themeHeat) || 0,
        themeLevel: typeof item.themeLevel === 'string' ? item.themeLevel : undefined,
        ...signalColumns,
      } satisfies SnapshotStockRow
    })
}

function buildSectorRow(
  record: SnapshotRecord,
  entityType: SnapshotSectorEntityType,
  entityKey: string,
  entityName: string,
  rank: number,
  payload: Record<string, any>,
): SnapshotSectorRow {
  const themeFactor = getThemeFactorPayload(payload)
  const includesFormalFunds = true
  return {
    id: `${record.id}:${entityType}:${entityKey}`,
    snapshotId: record.id,
    type: record.type as Exclude<SnapshotType, 'five_minute'>,
    tradingDate: record.tradingDate,
    slotTime: record.slotTime,
    timestamp: record.timestamp,
    captureMode: record.captureMode,
    source: record.source,
    entityType,
    entityKey,
    entityCode: typeof payload.code === 'string' ? payload.code : undefined,
    entityName,
    rank,
    strength: Number(payload.strength ?? payload.score ?? payload.heatScore) || 0,
    heatScore: finiteNumberOrNull(
      Object.prototype.hasOwnProperty.call(payload, 'heatScore') ? payload.heatScore : payload.strength,
    ),
    heatLevel: typeof payload.heatLevel === 'string' ? payload.heatLevel : undefined,
    change: Number(payload.change) || 0,
    mainNetInflow: includesFormalFunds
      ? finiteNumberOrNull(
          Object.prototype.hasOwnProperty.call(payload, 'mainNetInflow')
            ? payload.mainNetInflow
            : payload.netInflow,
        )
      : undefined,
    bigMoney300: Number(payload.bigMoney300) || 0,
    institutionBuy: Number(payload.institutionBuy) || 0,
    volumeRatio: Number(payload.volumeRatio) || 0,
    ztCount: Number(payload.ztCount) || 0,
    leaderCount: Number(payload.leaderCount) || 0,
    persistentDays: Number(payload.persistentDays) || 0,
    netInflow: includesFormalFunds
      ? finiteNumberOrNull(
          Object.prototype.hasOwnProperty.call(payload, 'netInflow')
            ? payload.netInflow
            : payload.mainNetInflow,
        )
      : undefined,
    momentumScore: finiteNumberOrUndefined(themeFactor.momentumScore),
    breadthScore: finiteNumberOrUndefined(themeFactor.breadthScore),
    fundScore: includesFormalFunds ? finiteNumberOrNull(themeFactor.fundScore) : undefined,
    leadershipScore: finiteNumberOrUndefined(themeFactor.leadershipScore),
    correlationScore: finiteNumberOrUndefined(themeFactor.correlationScore),
    crowdingRisk: finiteNumberOrUndefined(themeFactor.crowdingRisk),
    persistenceScore: finiteNumberOrUndefined(themeFactor.persistenceScore),
    rotationState:
      typeof themeFactor.rotationState === 'string' ? themeFactor.rotationState : undefined,
    themeQualityFlags: Array.isArray(themeFactor.qualityFlags)
      ? clonePlainObject(themeFactor.qualityFlags as any)
      : [],
    metadata: buildSectorMetadata(payload, includesFormalFunds),
  }
}

export function buildSnapshotSectorRows(
  record: SnapshotRecord,
  buildContext?: SnapshotBuildContext,
): SnapshotSectorRow[] {
  if (record.type === 'five_minute') return []
  const payload = (record.payload && typeof record.payload === 'object' ? record.payload : {}) as Record<string, any>
  const rows: SnapshotSectorRow[] = []

  const sectors = Array.isArray(payload.sectors) ? payload.sectors : []
  sectors.forEach((sector: any, index: number) => {
    const name = String(sector?.name || sector?.themeName || sector?.code || '').trim()
    const key = String(sector?.code || name).trim()
    if (!name || !key) return
    rows.push(buildSectorRow(record, 'sector', key, name, index + 1, sector))
  })

  const hotThemes = Array.isArray(buildContext?.themeHeatFactors)
    ? buildContext.themeHeatFactors
    : Array.isArray(buildContext?.hotThemes)
      ? buildContext.hotThemes
    : Array.isArray(payload.hotThemes)
      ? payload.hotThemes
      : []
  hotThemes.forEach((theme: any, index: number) => {
    const name = String(theme?.name || theme?.themeName || theme?.id || theme?.themeId || '').trim()
    const key = String(theme?.id || theme?.themeId || name).trim()
    if (!name || !key) return
    rows.push(buildSectorRow(record, 'hot_theme', key, name, index + 1, theme))
  })

  const rotationLines = Array.isArray(buildContext?.rotationAnalysis?.mainLines)
    ? buildContext?.rotationAnalysis?.mainLines
    : Array.isArray(payload.rotation?.mainLines)
      ? payload.rotation.mainLines
      : Array.isArray(payload.rotationSummary?.mainLines)
        ? payload.rotationSummary.mainLines
        : []
  rotationLines.forEach((line: any, index: number) => {
    const name = String(line?.themeName || line?.name || '').trim()
    const key = String(line?.themeName || line?.name || `line_${index + 1}`).trim()
    if (!name || !key) return
    rows.push(buildSectorRow(record, 'rotation_main_line', key, name, index + 1, line))
  })

  return rows
}

export function arrayToCSV(data: any[][]): string {
  return data
    .map((row) =>
      row
        .map((cell) => {
          if (cell === undefined || cell === null) return ''
          const str = String(cell)
          if (str.includes(',') || str.includes('"') || str.includes('\n')) {
            return `"${str.replace(/"/g, '""')}"`
          }
          return str
        })
        .join(','),
    )
    .join('\n')
}
