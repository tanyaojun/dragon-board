import type { JxbkBlockData } from '@/types'
import type { ThemeFactorSnapshot, ThemeQualityFlag, ThemeRotationState, ThemeSourceContext } from './types'
import { clamp, hasFiniteNumber, round, toFiniteNumber } from './utils'

const LIMIT_UP_CHANGE = 9.5

function normalizeName(value: string): string {
  return String(value || '')
    .trim()
    .replace(/概念$/, '')
    .replace(/板块$/, '')
}

function isSameThemeName(left: string, right: string): boolean {
  const normalizedLeft = normalizeName(left)
  const normalizedRight = normalizeName(right)
  return Boolean(
    normalizedLeft &&
      normalizedRight &&
      (normalizedLeft === normalizedRight ||
        normalizedLeft.includes(normalizedRight) ||
        normalizedRight.includes(normalizedLeft)),
  )
}

function findJxbkBlock(themeName: string, blocks: JxbkBlockData[] = []): JxbkBlockData | undefined {
  return blocks.find((block) => isSameThemeName(themeName, block.name))
}

function jxbkStrengthScore(block?: JxbkBlockData): number {
  if (!block) return 0
  const strength = toFiniteNumber(block.strength)
  const ztCount = toFiniteNumber(block.ztCount)
  const volumeRatio = toFiniteNumber(block.volumeRatio)
  const netInflow = toFiniteNumber(block.mainNetInflow)

  let score = 0
  if (strength >= 4000) score += 40
  else if (strength >= 3000) score += 30
  else if (strength >= 2000) score += 20
  else if (strength >= 1000) score += 10
  else if (strength > 0) score += 5

  if (ztCount >= 10) score += 30
  else if (ztCount >= 5) score += 25
  else if (ztCount >= 3) score += 20
  else if (ztCount >= 1) score += 15

  if (volumeRatio >= 2.5) score += 15
  else if (volumeRatio >= 1.5) score += 10
  else if (volumeRatio >= 0.8) score += 5

  if (netInflow > 100000000) score += 15
  else if (netInflow > 50000000) score += 12
  else if (netInflow > 10000000) score += 8
  else if (netInflow > 0) score += 5

  return clamp(Math.round(score))
}

function stockBreadthScore(stocks: ThemeSourceContext['stocks']): number {
  if (!stocks.length) return 0
  const valid = stocks.filter((stock) => Number.isFinite(Number(stock.change)))
  if (!valid.length) return 0
  const upCount = valid.filter((stock) => toFiniteNumber(stock.change) > 0).length
  const ztCount = valid.filter((stock) => toFiniteNumber(stock.change) >= LIMIT_UP_CHANGE).length
  const strongCount = valid.filter((stock) => toFiniteNumber(stock.change) >= 5).length
  return clamp(round((upCount / valid.length) * 45 + (strongCount / valid.length) * 25 + ztCount * 12))
}

function hasAnyValidStockSignal(stocks: ThemeSourceContext['stocks']): boolean {
  return stocks.some(
    (stock) =>
      hasFiniteNumber(stock.change) ||
      hasFiniteNumber((stock as any).volumeRatio) ||
      hasFiniteNumber((stock as any).mainNetInflow),
  )
}

function fundScore(block: JxbkBlockData | undefined, stocks: ThemeSourceContext['stocks']): number {
  const blockScore = block
    ? clamp(
        Math.min(35, Math.max(0, toFiniteNumber(block.mainNetInflow) / 100000000) * 18) +
          Math.min(20, Math.max(0, toFiniteNumber(block.bigMoney300) / 10000000) * 6) +
          Math.min(15, Math.max(0, toFiniteNumber(block.institutionBuy) / 10000000) * 8),
      )
    : 0

  const stockInflow = stocks.reduce((sum, stock) => sum + Math.max(0, toFiniteNumber((stock as any).mainNetInflow)), 0)
  const stockScore = Math.min(30, (stockInflow / 100000000) * 20)
  return clamp(round(blockScore + stockScore))
}

function leadershipScore(stocks: ThemeSourceContext['stocks']): { score: number; leaderCount: number } {
  if (!stocks.length) return { score: 0, leaderCount: 0 }

  let score = 0
  let leaderCount = 0
  stocks.forEach((stock) => {
    const leadStatus = String((stock as any).leadStatus || '')
    const leadTimes = toFiniteNumber((stock as any).leadTimes)
    const continuousDays = Math.max(
      toFiniteNumber((stock as any).continuousDays),
      toFiniteNumber((stock as any).highDays),
      toFiniteNumber((stock as any).boardHeight),
    )
    const change = toFiniteNumber(stock.change)
    const fengdan = Math.max(0, toFiniteNumber((stock as any).fengdan))

    if (leadStatus.includes('龙')) {
      leaderCount++
      score += 22
    }
    if (leadTimes > 0) score += Math.min(14, leadTimes * 4)
    if (continuousDays > 0) score += Math.min(16, continuousDays * 4)
    if (change >= LIMIT_UP_CHANGE) score += 10
    if (fengdan > 0) score += Math.min(10, fengdan / 10000)
  })

  return { score: clamp(round(score)), leaderCount }
}

function correlationScore(context: ThemeSourceContext, themeId: string, stocks: ThemeSourceContext['stocks']): number {
  const detail = context.correlations?.get(themeId)
  if (detail) return clamp(round(toFiniteNumber(detail.overallCorrelation) * 100))
  if (stocks.length < 2) return 0

  const validDirections = stocks
    .map((stock) => Math.sign(toFiniteNumber(stock.change)))
    .filter((direction) => direction !== 0)
  if (validDirections.length < 2) return 0
  const positive = validDirections.filter((direction) => direction > 0).length
  const negative = validDirections.filter((direction) => direction < 0).length
  return clamp(round((Math.max(positive, negative) / validDirections.length) * 100))
}

function crowdingRiskScore(block: JxbkBlockData | undefined, heatScore: number, stocks: ThemeSourceContext['stocks']): number {
  const volumeRatio = Math.max(toFiniteNumber(block?.volumeRatio), ...stocks.map((stock) => toFiniteNumber((stock as any).volumeRatio)))
  const hotStockRatio = stocks.length
    ? stocks.filter((stock) => toFiniteNumber(stock.change) >= 7).length / stocks.length
    : 0
  return clamp(round((heatScore >= 85 ? 24 : 0) + Math.max(0, volumeRatio - 2.5) * 12 + hotStockRatio * 28))
}

function persistenceScore(context: ThemeSourceContext, themeId: string, themeName: string): number {
  const mainLine = context.rotationAnalysis?.mainLines?.find(
    (line: any) => line?.themeId === themeId || isSameThemeName(String(line?.themeName || line?.name || ''), themeName),
  ) as any
  if (!mainLine) return 0
  const persistentDays = Math.max(0, toFiniteNumber(mainLine.persistentDays))
  return clamp(round(Math.min(92, 18 + Math.log1p(persistentDays) * 28 + Math.min(5, persistentDays) * 6)))
}

function rotationState(context: ThemeSourceContext, themeId: string, themeName: string): ThemeRotationState {
  const rotation = context.rotationAnalysis
  if (!rotation) return 'neutral'
  const matches = (item: any) =>
    item?.themeId === themeId || isSameThemeName(String(item?.themeName || item?.name || ''), themeName)
  if (rotation.mainLines?.some(matches)) return 'mainline'
  if (rotation.quickRotation?.some(matches)) return 'quick'
  if (rotation.inflowThemes?.some(matches)) return 'inflow'
  if (rotation.outflowThemes?.some(matches)) return 'outflow'
  return 'neutral'
}

function qualityFlags(
  context: ThemeSourceContext,
  themeId: string,
  stocks: ThemeSourceContext['stocks'],
  block?: JxbkBlockData,
): ThemeQualityFlag[] {
  const flags: ThemeQualityFlag[] = []
  if (!context.themeStocks.has(themeId)) {
    flags.push({ code: 'mapping_missing', level: 'warning', message: '题材缺少静态成分映射' })
  }
  if (stocks.length === 0) {
    flags.push({ code: 'empty_theme', level: 'warning', message: '题材没有可用成分股' })
  } else if (stocks.length < 2) {
    flags.push({ code: 'low_sample', level: 'info', message: '题材样本量偏低', count: stocks.length })
  }
  if (!block) {
    flags.push({ code: 'jxbk_missing', level: 'warning', message: '缺少 JXBK 实时板块数据' })
  }

  const invalidCount = stocks.reduce((count, stock) => {
    const values = [stock.change, (stock as any).volumeRatio, (stock as any).mainNetInflow]
    return count + values.filter((value) => value !== undefined && !Number.isFinite(Number(value))).length
  }, 0)
  if (invalidCount > 0) {
    flags.push({ code: 'invalid_number', level: 'warning', message: '题材成分存在非法数值', count: invalidCount })
  }
  return flags
}

function sourceFor(block: JxbkBlockData | undefined, stocks: ThemeSourceContext['stocks']) {
  if (block && stocks.length) return 'mixed' as const
  if (block) return 'jxbk' as const
  return 'static' as const
}

export function buildThemeFactors(context: ThemeSourceContext): ThemeFactorSnapshot[] {
  const timestamp = context.timestamp || Date.now()
  const stockByCode = new Map(context.stocks.map((stock) => [stock.code, stock]))

  const factors = context.themes.map((theme) => {
    const stockCodes = context.themeStocks.get(theme.id) || []
    const stocks = stockCodes.map((code) => stockByCode.get(code)).filter(Boolean) as ThemeSourceContext['stocks']
    const block = findJxbkBlock(theme.name, context.jxbkBlocks)
    const jxbkScore = jxbkStrengthScore(block)
    const breadth = stockBreadthScore(stocks)
    const funds = fundScore(block, stocks)
    const leadership = leadershipScore(stocks)
    const correlation = correlationScore(context, theme.id, stocks)
    const persistence = persistenceScore(context, theme.id, theme.name)
    const rotation = rotationState(context, theme.id, theme.name)
    const baseScore = stocks.length ? Math.min(18, stocks.length * 4) : 0
    const stockScore = clamp(breadth * 0.36 + funds * 0.22 + leadership.score * 0.28 + correlation * 0.14)
    const heatBeforeRisk = clamp(Math.max(jxbkScore, stockScore) + persistence * 0.08 + baseScore * 0.2)
    const crowdingRisk = crowdingRiskScore(block, heatBeforeRisk, stocks)
    const riskPenalty = Math.min(14, crowdingRisk * 0.14)
    const heatScore = (stocks.length && hasAnyValidStockSignal(stocks)) || block ? clamp(round(heatBeforeRisk - riskPenalty)) : 0
    const relatedThemeIds: string[] = []

    return {
      themeId: theme.id,
      themeName: theme.name,
      source: sourceFor(block, stocks),
      snapshotId: context.snapshotId,
      timestamp,
      heatScore,
      momentumScore: clamp(round(jxbkScore * 0.55 + Math.max(0, toFiniteNumber(block?.change)) * 8 + persistence * 0.15)),
      breadthScore: breadth,
      fundScore: funds,
      leadershipScore: leadership.score,
      correlationScore: correlation,
      crowdingRisk,
      persistenceScore: persistence,
      rotationState: rotation,
      stockCount: stocks.length,
      ztCount: Math.max(toFiniteNumber(block?.ztCount), stocks.filter((stock) => toFiniteNumber(stock.change) >= LIMIT_UP_CHANGE).length),
      leaderCount: leadership.leaderCount,
      netInflow: toFiniteNumber(block?.mainNetInflow),
      strength: toFiniteNumber(block?.strength),
      volumeRatio: toFiniteNumber(block?.volumeRatio),
      rank: 0,
      relatedThemeIds,
      qualityFlags: qualityFlags(context, theme.id, stocks, block),
      components: {
        baseScore,
        jxbkScore,
        stockScore: round(stockScore),
        riskPenalty: round(riskPenalty, 1),
      },
    } satisfies ThemeFactorSnapshot
  })

  return factors
    .sort((left, right) => right.heatScore - left.heatScore || right.momentumScore - left.momentumScore || left.themeName.localeCompare(right.themeName, 'zh-CN'))
    .map((factor, index) => ({ ...factor, rank: index + 1 }))
}
