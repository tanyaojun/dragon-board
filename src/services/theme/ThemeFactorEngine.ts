import type {
  ThemeFactorSnapshot,
  ThemeQualityFlag,
  ThemeRotationState,
  ThemeSourceContext,
} from './types'
import { clamp, hasFiniteNumber, round, toFiniteNumber } from './utils'
import { getTrustedVolumeRatio } from '@/services/dataLoader/VolumeRatioTrust'

const LIMIT_UP_CHANGE = 9.5
const HEAT_BREADTH_WEIGHT = 0.36
const HEAT_FUND_WEIGHT = 0.22
const HEAT_LEADERSHIP_WEIGHT = 0.28
const HEAT_CORRELATION_WEIGHT = 0.14
const HEAT_PERSISTENCE_WEIGHT = 0.08
const CROWDING_RISK_PENALTY_RATIO = 0.14

function normalizeName(value: string): string {
  return String(value || '').trim().replace(/概念$/, '').replace(/板块$/, '')
}

function isSameThemeName(left: string, right: string): boolean {
  const a = normalizeName(left)
  const b = normalizeName(right)
  return Boolean(a && b && (a === b || a.includes(b) || b.includes(a)))
}

function stockBreadthScore(stocks: ThemeSourceContext['stocks']): number {
  const valid = stocks.filter((stock) => Number.isFinite(Number(stock.change)))
  if (!valid.length) return 0
  const upRate = valid.filter((stock) => toFiniteNumber(stock.change) > 0).length / valid.length
  const strongRate = valid.filter((stock) => toFiniteNumber(stock.change) >= 5).length / valid.length
  const limitUpRate = valid.filter((stock) => toFiniteNumber(stock.change) >= LIMIT_UP_CHANGE).length / valid.length
  return clamp(round(upRate * 45 + strongRate * 30 + limitUpRate * 25))
}

function hasAnyValidStockSignal(stocks: ThemeSourceContext['stocks']): boolean {
  return stocks.some(
    (stock) =>
      hasFiniteNumber(stock.change) ||
      getTrustedVolumeRatio(stock) > 0 ||
      hasFiniteNumber((stock as any).mainNetInflow),
  )
}

function stockFundScore(stocks: ThemeSourceContext['stocks']): number {
  const valid = stocks.filter((stock) => hasFiniteNumber((stock as any).mainNetInflow))
  if (!valid.length) return 0
  const positiveRate = valid.filter((stock) => toFiniteNumber((stock as any).mainNetInflow) > 0).length / valid.length
  const inflow = valid.reduce((sum, stock) => sum + toFiniteNumber((stock as any).mainNetInflow), 0)
  const amount = valid.reduce((sum, stock) => sum + Math.max(0, toFiniteNumber((stock as any).amount)), 0)
  const ratio = amount > 0 ? clamp(inflow / amount, -0.1, 0.1) : 0
  return clamp(round((50 + ratio * 500) * 0.7 + positiveRate * 100 * 0.3))
}

function leadershipScore(stocks: ThemeSourceContext['stocks']): { score: number; leaderCount: number } {
  if (!stocks.length) return { score: 0, leaderCount: 0 }
  const limitUpRate = stocks.filter((stock) => toFiniteNumber(stock.change) >= LIMIT_UP_CHANGE).length / stocks.length
  const maxBoardHeight = Math.max(
    0,
    ...stocks.map((stock) =>
      Math.max(
        toFiniteNumber((stock as any).boardHeight),
        toFiniteNumber((stock as any).continuousDays),
        toFiniteNumber((stock as any).highDays),
      ),
    ),
  )
  const leaderCount = stocks.filter((stock) => String((stock as any).leadStatus || '').includes('龙')).length
  return {
    score: clamp(
      round(
        limitUpRate * 50 +
          Math.min(maxBoardHeight * 6, 30) +
          Math.min((leaderCount / stocks.length) * 100, 20),
      ),
    ),
    leaderCount,
  }
}

function correlationScore(context: ThemeSourceContext, themeId: string, stocks: ThemeSourceContext['stocks']): number {
  const detail = context.correlations?.get(themeId)
  if (detail) return clamp(round(toFiniteNumber(detail.overallCorrelation) * 100))
  const directions = stocks.map((stock) => Math.sign(toFiniteNumber(stock.change))).filter(Boolean)
  if (!directions.length) return 0
  const positive = directions.filter((direction) => direction > 0).length
  const negative = directions.filter((direction) => direction < 0).length
  return clamp(round((Math.max(positive, negative) / directions.length) * 100))
}

function crowdingRiskScore(weighted: number, stocks: ThemeSourceContext['stocks']): number {
  const ratios = stocks.map((stock) => Math.min(getTrustedVolumeRatio(stock), 10))
  const average = ratios.length ? ratios.reduce((sum, value) => sum + value, 0) / ratios.length : 0
  const hotRate = stocks.length
    ? stocks.filter((stock) => toFiniteNumber(stock.change) >= 7).length / stocks.length
    : 0
  return clamp(round((weighted >= 85 ? 24 : 0) + Math.max(0, average - 2.5) * 12 + hotRate * 28))
}

function persistenceScore(context: ThemeSourceContext, themeId: string, themeName: string): number {
  const mainLine = context.rotationAnalysis?.mainLines?.find(
    (line: any) => line?.themeId === themeId || isSameThemeName(String(line?.themeName || line?.name || ''), themeName),
  ) as any
  if (!mainLine) return 0
  const days = Math.max(0, toFiniteNumber(mainLine.persistentDays))
  return clamp(round(Math.min(100, days * 20)))
}

function rotationState(context: ThemeSourceContext, themeId: string, themeName: string): ThemeRotationState {
  const rotation = context.rotationAnalysis
  if (!rotation) return 'neutral'
  const matches = (item: any) =>
    item?.themeId === themeId || isSameThemeName(String(item?.themeName || item?.name || ''), themeName)
  if (rotation.mainLines?.some(matches)) return 'mainline'
  if (rotation.quickRotation?.some(matches)) return 'quick'
  if (rotation.inflowThemes?.some(matches)) return 'inflow'
  if (rotation.outflowThemes?.some(matches)) {
    return rotation.marketPhase === 'distribution' || rotation.marketPhase === 'falling' ? 'cooling' : 'outflow'
  }
  return 'neutral'
}

function qualityFlags(
  context: ThemeSourceContext,
  themeId: string,
  stocks: ThemeSourceContext['stocks'],
): ThemeQualityFlag[] {
  const flags: ThemeQualityFlag[] = []
  if (!context.themeStocks.has(themeId)) {
    flags.push({ code: 'mapping_missing', level: 'warning', message: '题材缺少静态成分映射' })
  }
  if (!stocks.length) flags.push({ code: 'empty_theme', level: 'warning', message: '题材没有可用成分股' })
  else if (stocks.length < 2) flags.push({ code: 'low_sample', level: 'info', message: '题材样本量偏低', count: stocks.length })
  const invalidCount = stocks.reduce((count, stock) => {
    const values = [stock.change, (stock as any).volumeRatio, (stock as any).mainNetInflow]
    return count + values.filter((value) => value !== undefined && !Number.isFinite(Number(value))).length
  }, 0)
  if (invalidCount) {
    flags.push({ code: 'invalid_number', level: 'warning', message: '题材成分存在非法数值', count: invalidCount })
  }
  return flags
}

function averageChange(stocks: ThemeSourceContext['stocks']): number {
  const values = stocks.map((stock) => toFiniteNumber(stock.change)).filter(Number.isFinite)
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0
}

export function buildThemeFactors(context: ThemeSourceContext): ThemeFactorSnapshot[] {
  const timestamp = context.timestamp || Date.now()
  const stockByCode = new Map(context.stocks.map((stock) => [stock.code, stock]))
  return context.themes
    .map((theme) => {
      const stockCodes = context.themeStocks.get(theme.id) || []
      const stocks = stockCodes.map((code) => stockByCode.get(code)).filter(Boolean) as ThemeSourceContext['stocks']
      const breadth = stockBreadthScore(stocks)
      const funds = stockFundScore(stocks)
      const leadership = leadershipScore(stocks)
      const correlation = correlationScore(context, theme.id, stocks)
      const persistence = persistenceScore(context, theme.id, theme.name)
      const weighted =
        breadth * HEAT_BREADTH_WEIGHT +
        funds * HEAT_FUND_WEIGHT +
        leadership.score * HEAT_LEADERSHIP_WEIGHT +
        correlation * HEAT_CORRELATION_WEIGHT
      const crowdingRisk = crowdingRiskScore(weighted, stocks)
      const riskPenalty = Math.min(14, crowdingRisk * CROWDING_RISK_PENALTY_RATIO)
      const heatScore = stocks.length && hasAnyValidStockSignal(stocks)
        ? clamp(round(weighted + persistence * HEAT_PERSISTENCE_WEIGHT - riskPenalty))
        : 0
      const volumeRatios = stocks.map(getTrustedVolumeRatio)
      return {
        themeId: theme.id,
        themeName: theme.name,
        source: 'static',
        snapshotId: context.snapshotId,
        timestamp,
        heatScore,
        momentumScore: clamp(round(50 + averageChange(stocks) * 8)),
        breadthScore: breadth,
        fundScore: funds,
        leadershipScore: leadership.score,
        correlationScore: correlation,
        crowdingRisk,
        persistenceScore: persistence,
        rotationState: rotationState(context, theme.id, theme.name),
        stockCount: stocks.length,
        ztCount: stocks.filter((stock) => toFiniteNumber(stock.change) >= LIMIT_UP_CHANGE).length,
        leaderCount: leadership.leaderCount,
        netInflow: stocks.reduce((sum, stock) => sum + toFiniteNumber((stock as any).mainNetInflow), 0),
        strength: heatScore,
        volumeRatio: volumeRatios.length
          ? volumeRatios.reduce((sum, value) => sum + value, 0) / volumeRatios.length
          : 0,
        rank: 0,
        relatedThemeIds: [],
        qualityFlags: qualityFlags(context, theme.id, stocks),
        components: {
          breadthScore: breadth,
          fundScore: funds,
          leadershipScore: leadership.score,
          correlationScore: correlation,
          riskPenalty: round(riskPenalty, 1),
        },
      } satisfies ThemeFactorSnapshot
    })
    .sort((a, b) => b.heatScore - a.heatScore || b.momentumScore - a.momentumScore || a.themeName.localeCompare(b.themeName, 'zh-CN'))
    .map((factor, index) => ({ ...factor, rank: index + 1 }))
}
