import type { MergedStock } from '@/types'

const INVALID_RANK = 999

interface RangeStat {
  min: number
  max: number
}

export interface StockHotnessWeights {
  avgRank: number
  platformCoverage: number
  popularity: number
  popularityChange: number
  leaderStatus: number
  boardHeight: number
  turnoverRate: number
  themeSupport: number
}

export interface StockHotnessConfig {
  weights: StockHotnessWeights
}

export interface StockHotnessComponentScores {
  avgRank: number
  platformCoverage: number
  popularity: number
  popularityChange: number
  leaderStatus: number
  boardHeight: number
  turnoverRate: number
  themeSupport: number
}

export interface StockHotnessRecord {
  code: string
  hotness: number
  components: StockHotnessComponentScores
}

export type StockHotnessConfigInput = Partial<{
  weights: Partial<StockHotnessWeights>
}>

export const DEFAULT_STOCK_HOTNESS_CONFIG: StockHotnessConfig = {
  weights: {
    avgRank: 0.36,
    platformCoverage: 0.12,
    popularity: 0.15,
    popularityChange: 0.10,
    leaderStatus: 0.11,
    boardHeight: 0.08,
    turnoverRate: 0.08,
    themeSupport: 0.05,
  },
}

function createEmptyRange(): RangeStat {
  return {
    min: Infinity,
    max: -Infinity,
  }
}

function toNumber(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

function isValidRank(value: unknown): boolean {
  const numeric = toNumber(value)
  return numeric > 0 && numeric < INVALID_RANK
}

function updateRange(range: RangeStat, value: unknown, predicate: (value: number) => boolean) {
  const numeric = toNumber(value)
  if (!predicate(numeric)) return
  range.min = Math.min(range.min, numeric)
  range.max = Math.max(range.max, numeric)
}

function normalize(value: unknown, range: RangeStat, reverse = false): number {
  const numeric = toNumber(value)
  if (!Number.isFinite(numeric) || numeric <= 0) return 0
  if (range.min === Infinity || range.max === -Infinity) return 0

  if (range.max === range.min) {
    return numeric === range.min ? 100 : 0
  }

  const score = ((numeric - range.min) / (range.max - range.min)) * 100
  const normalized = Math.min(100, Math.max(0, score))
  return reverse ? 100 - normalized : normalized
}

function leadStatusHeatScore(stock: Pick<MergedStock, 'leadStatus' | 'leadTimes'>): number {
  const status = String(stock.leadStatus || '')
  let score = 0

  if (status.includes('总龙') || status.includes('龙一')) score = 100
  else if (status.includes('龙二')) score = 85
  else if (status.includes('龙三')) score = 72
  else if (status.includes('领涨')) score = 60
  else if (status.includes('龙')) score = 45

  const leadTimes = toNumber(stock.leadTimes)
  if (leadTimes > 0) {
    score = Math.min(100, score + Math.min(18, leadTimes * 4))
  }

  return score
}

function boardHeightFromStock(
  stock: Pick<MergedStock, 'boardHeight' | 'highDays' | 'continuousDays' | 'lianbanStr'>,
): number {
  const direct = Math.max(
    toNumber(stock.boardHeight),
    toNumber(stock.highDays),
    toNumber(stock.continuousDays),
  )
  if (direct > 0) return direct

  const text = String(stock.lianbanStr || '')
  const match = text.match(/(\d+)/)
  return match ? Number(match[1]) : 0
}

function boardHeatScore(
  stock: Pick<MergedStock, 'boardHeight' | 'highDays' | 'continuousDays' | 'lianbanStr'>,
): number {
  const height = boardHeightFromStock(stock)
  if (height >= 6) return 100
  if (height >= 5) return 90
  if (height >= 4) return 78
  if (height >= 3) return 64
  if (height >= 2) return 48
  if (height >= 1) return 24
  return 0
}

function turnoverHeatScore(stock: Pick<MergedStock, 'turnoverRate'>): number {
  const rate = toNumber(stock.turnoverRate)
  if (rate <= 0) return 0
  if (rate <= 2) return rate * 12
  if (rate <= 6) return 24 + (rate - 2) * 10
  if (rate <= 18) return 64 + (rate - 6) * 2.5
  if (rate <= 30) return 94 - (rate - 18) * 1.2
  if (rate <= 45) return 80 - (rate - 30) * 1.5
  return 55
}

function themeSupportScore(stock: Pick<MergedStock, 'themeHeat' | 'themes'>): number {
  const themeHeat = toNumber(stock.themeHeat)
  const themeContributions = Array.isArray(stock.themes)
    ? stock.themes.map((theme: unknown) =>
        theme && typeof theme === 'object' ? toNumber((theme as { themeContribution?: unknown }).themeContribution) : 0,
      )
    : []
  const maxContribution = Math.max(0, ...themeContributions)
  if (themeHeat <= 0 && maxContribution <= 0) return 0
  return Math.min(100, themeHeat * 0.55 + Math.min(18, maxContribution) * 2.5)
}

function platformCoverageScore(platforms: unknown, totalPlatforms: number): number {
  const count = toNumber(platforms)
  if (count <= 0 || totalPlatforms <= 0) return 0
  return Math.min(100, (count / totalPlatforms) * 100)
}

function normalizeWeightMap(weights: Partial<StockHotnessWeights> | undefined): StockHotnessWeights {
  const merged: StockHotnessWeights = {
    ...DEFAULT_STOCK_HOTNESS_CONFIG.weights,
    ...(weights || {}),
  }

  const positiveEntries = Object.entries(merged).map(([key, value]) => [
    key,
    Number.isFinite(value) && value > 0 ? value : 0,
  ]) as Array<[keyof StockHotnessWeights, number]>

  const totalWeight = positiveEntries.reduce((sum, [, value]) => sum + value, 0)
  if (totalWeight <= 0) {
    return { ...DEFAULT_STOCK_HOTNESS_CONFIG.weights }
  }

  return positiveEntries.reduce(
    (result, [key, value]) => {
      result[key] = value / totalWeight
      return result
    },
    {} as StockHotnessWeights,
  )
}

export function normalizeStockHotnessConfig(
  config?: StockHotnessConfigInput | null,
): StockHotnessConfig {
  return {
    weights: normalizeWeightMap(config?.weights),
  }
}

function buildComponentScores(
  stock: MergedStock,
  totalPlatforms: number,
  avgRankRange: RangeStat,
  popularityRange: RangeStat,
  popularityChangeRange: RangeStat,
): StockHotnessComponentScores {
  return {
    avgRank: normalize(stock.avgRankNum, avgRankRange, true),
    platformCoverage: platformCoverageScore(stock.platforms, totalPlatforms),
    // 这里的人气是绝对热度值，不是“数值越小越强”的名次。
    // 个股讨论度越高，热度组件得分也应该越高。
    popularity: normalize(stock.popularity, popularityRange, false),
    popularityChange: normalize(stock.popularityChange, popularityChangeRange, false),
    leaderStatus: leadStatusHeatScore(stock),
    boardHeight: boardHeatScore(stock),
    turnoverRate: turnoverHeatScore(stock),
    themeSupport: themeSupportScore(stock),
  }
}

function hasAnyHeatSignal(components: StockHotnessComponentScores): boolean {
  return Object.values(components).some((value) => value > 0)
}

function calculateWeightedHotness(
  components: StockHotnessComponentScores,
  config: StockHotnessConfig,
): number {
  return (
    components.avgRank * config.weights.avgRank +
    components.platformCoverage * config.weights.platformCoverage +
    components.popularity * config.weights.popularity +
    components.popularityChange * config.weights.popularityChange +
    components.leaderStatus * config.weights.leaderStatus +
    components.boardHeight * config.weights.boardHeight +
    components.turnoverRate * config.weights.turnoverRate +
    components.themeSupport * config.weights.themeSupport
  )
}

/**
 * 个股热度的核心原则：
 * 1. avgRank 只提供“跨平台关注度”底座，不能单独冒充热度；
 * 2. 人气、人气变化、领涨状态、身位、换手共同决定“热而且活”还是“只是挂榜”；
 * 3. 权重统一走运行时配置，后续可直接接外部研究工具或手工校准。
 */
export function calculateStockHotnessRecords(
  stocks: MergedStock[],
  totalPlatforms = 8,
  config?: StockHotnessConfigInput | null,
): StockHotnessRecord[] {
  const runtimeConfig = normalizeStockHotnessConfig(config)
  const avgRankRange = createEmptyRange()
  const popularityRange = createEmptyRange()
  const popularityChangeRange = createEmptyRange()

  stocks.forEach((stock) => {
    updateRange(avgRankRange, stock.avgRankNum, isValidRank)
    updateRange(popularityRange, stock.popularity, (value) => value > 0)
    updateRange(popularityChangeRange, stock.popularityChange, (value) => value !== 0)
  })

  return stocks.map((stock) => {
    const components = buildComponentScores(
      stock,
      totalPlatforms,
      avgRankRange,
      popularityRange,
      popularityChangeRange,
    )

    return {
      code: stock.code,
      hotness: hasAnyHeatSignal(components)
        ? Math.max(0, Math.min(100, Math.round(calculateWeightedHotness(components, runtimeConfig))))
        : 0,
      components,
    }
  })
}

export function calculateStockHotnessUpdates(
  stocks: MergedStock[],
  totalPlatforms = 8,
  config?: StockHotnessConfigInput | null,
): Array<{ code: string; hotness: number }> {
  return calculateStockHotnessRecords(stocks, totalPlatforms, config).map((record) => ({
    code: record.code,
    hotness: record.hotness,
  }))
}
