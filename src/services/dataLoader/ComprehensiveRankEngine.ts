import {
  COMPREHENSIVE_WEIGHTS,
  DEFAULT_RANK,
  OPTIMAL_TURNOVER,
  PENALTY_SCORE,
  TURNOVER_SIGMA,
} from '../../types/config'

const PLATFORMS = ['eastmoney', 'ths', 'kpl', 'tdx', 'xueqiu', 'cls', 'tgb', 'dzh'] as const

type Platform = (typeof PLATFORMS)[number]
type PlatformTotals = Record<Platform, number>
type PlatformData = Partial<Record<Platform, unknown[] | null | undefined>>
type RankableStock = Record<string, any> & {
  platforms?: number
  avgRankNum?: number
  avgRank?: string
  fundPenetration?: number | null
  compScore?: number | null
  compRank?: number
  rank?: number
  missingFields?: string[]
  qualityFlags?: string[]
}

const rankFieldMap: Record<Platform, string> = {
  eastmoney: 'emRank',
  ths: 'thsRank',
  kpl: 'kplRank',
  tdx: 'tdxRank',
  xueqiu: 'xqRank',
  cls: 'clsRank',
  tgb: 'tgbRank',
  dzh: 'dzhRank',
}

const weightMap: Record<Platform, number> = {
  kpl: 1.0,
  tdx: 0.9,
  ths: 0.85,
  eastmoney: 0.75,
  dzh: 0.7,
  tgb: 0.4,
  xueqiu: 0.35,
  cls: 0.35,
}

export function getRankField(platform: string): string | null {
  return rankFieldMap[platform as Platform] || null
}

export function getPlatformWeight(platform: string): number {
  return weightMap[platform as Platform] || 0.5
}

export function calculatePlatformTotals(platformData: PlatformData): PlatformTotals {
  return PLATFORMS.reduce((totals, platform) => {
    totals[platform] = platformData[platform]?.length || 0
    return totals
  }, {} as PlatformTotals)
}

export function calculateAverageRank<T extends RankableStock>(
  stock: T,
  platformTotals: PlatformTotals,
): T {
  let weightedSum = 0
  let totalWeight = 0
  let platforms = 0

  for (const platform of PLATFORMS) {
    const rankField = rankFieldMap[platform]
    const rank = stock[rankField]
    const total = platformTotals[platform]
    const weight = getPlatformWeight(platform)

    if (total > 0) {
      totalWeight += weight
      if (rank < DEFAULT_RANK) {
        platforms++
        weightedSum += (rank / total) * 100 * weight
      } else {
        weightedSum += PENALTY_SCORE * weight
      }
    }
  }

  stock.platforms = platforms
  if (totalWeight > 0) {
    stock.avgRankNum = weightedSum / totalWeight
    stock.avgRank = stock.avgRankNum.toFixed(1)
  }

  return stock
}

export function calculateComprehensiveRanks<T extends RankableStock>(stocks: T[]): void {
  if (!stocks.length) return

  stocks.forEach((stock) => {
    const cirMV = toNumber(stock.cirMV)
    const zlje = toNumber(stock.zlje)
    stock.fundPenetration = cirMV !== null && zlje !== null && cirMV > 0 ? (zlje / cirMV) * 100 : null
  })

  const stats = {
    avgRankNum: { min: Infinity, max: -Infinity },
    zljzb: { min: Infinity, max: -Infinity },
    fundPenetration: { min: Infinity, max: -Infinity },
    turnover: { min: Infinity, max: -Infinity },
  }

  stocks.forEach((stock) => {
    ;[
      ['avgRankNum', toNumber(stock.avgRankNum)],
      ['zljzb', toNumber(stock.zljzb)],
      ['fundPenetration', toNumber(stock.fundPenetration)],
      ['turnover', toNumber(stock.turnover)],
    ].forEach(([key, value]) => { if (value !== null) updateMinMax(stats[key as keyof typeof stats], value as number) })
  })

  stocks.forEach((stock) => {
    const avgRankNum = toNumber(stock.avgRankNum)
    const zljzb = toNumber(stock.zljzb)
    const fundPenetration = toNumber(stock.fundPenetration)
    const turnover = toNumber(stock.turnover)

    const components: Array<[number | null, number, (value: number) => number]> = [
      [avgRankNum, COMPREHENSIVE_WEIGHTS.HOT_RANK, (v) => normalize(v, stats.avgRankNum.min, stats.avgRankNum.max, true)],
      [zljzb, COMPREHENSIVE_WEIGHTS.MONEY_RATIO, (v) => normalize(v, stats.zljzb.min, stats.zljzb.max, false)],
      [fundPenetration, COMPREHENSIVE_WEIGHTS.FUND_PENETRATION, (v) => normalize(v, stats.fundPenetration.min, stats.fundPenetration.max, false)],
      [toNumber(stock.turnoverRate), COMPREHENSIVE_WEIGHTS.TURNOVER_RATE, getTurnoverScore],
      [turnover, COMPREHENSIVE_WEIGHTS.VOLUME, (v) => normalize(v, stats.turnover.min, stats.turnover.max, false)],
    ]
    const available = components.filter(([value]) => value !== null) as Array<[number, number, (value: number) => number]>
    stock.compScore = available.length
      ? available.reduce((sum, [value, weight, scorer]) => sum + scorer(value) * weight, 0) / available.reduce((sum, [, weight]) => sum + weight, 0)
      : null
    const missingFields = ['avgRankNum', 'zljzb', 'fundPenetration', 'turnoverRate', 'turnover'].filter((field) => toNumber(stock[field]) === null)
    stock.missingFields = missingFields
    stock.qualityFlags = missingFields.length ? ['missing_comprehensive_fields'] : []
  })

  const sorted = [...stocks].sort(
    (a, b) => (b.compScore ?? -1) - (a.compScore ?? -1) || String(a.code).localeCompare(String(b.code)),
  )
  sorted.forEach((stock, index) => {
    stock.compRank = index + 1
  })
}

export function rankMergedStocks<T extends RankableStock>(
  stockMap: Map<string, T>,
  platformData: PlatformData,
): T[] {
  const platformTotals = calculatePlatformTotals(platformData)
  const merged = Array.from(stockMap.values()).map((stock) =>
    calculateAverageRank(stock, platformTotals),
  )

  calculateComprehensiveRanks(merged)
  merged.sort(
    (a, b) => (b.compScore || 0) - (a.compScore || 0) || String(a.code).localeCompare(String(b.code)),
  )
  merged.forEach((stock, index) => {
    stock.rank = index + 1
  })

  return merged
}

function updateMinMax(stat: { min: number; max: number }, value: number): void {
  if (value < stat.min) stat.min = value
  if (value > stat.max) stat.max = value
}

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function normalize(val: number, min: number, max: number, reverse = false): number {
  if (isNaN(val) || val === null || val === undefined) return reverse ? 100 : 0
  if (max === min || isNaN(min) || isNaN(max) || min === Infinity || max === -Infinity) {
    if (val > 0) return reverse ? 0 : 100
    if (val < 0) return reverse ? 100 : 0
    return 50
  }

  const score = ((val - min) / (max - min)) * 100
  const clampedScore = Math.min(100, Math.max(0, score))
  return reverse ? 100 - clampedScore : clampedScore
}

function getTurnoverScore(rate: number): number {
  const r = rate
  return 100 * Math.exp(-Math.pow(r - OPTIMAL_TURNOVER, 2) / (2 * TURNOVER_SIGMA ** 2))
}
