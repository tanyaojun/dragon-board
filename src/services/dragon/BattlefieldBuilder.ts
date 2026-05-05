import { dataLayer } from '../../services/DataLayer'
import { themeMapping } from '../../services/ThemeDataService'
import { themeFacade } from '../../services/theme/ThemeFacade'
import type { MergedStock } from '@/types'
import type { ThemeExposureProjection } from '../theme/types'
import type { BattlefieldDominance, BattlefieldRecord, ReviewFrame, SignalStrength } from './types'
import { getNetCapital, getStockTagNames, themeNamesFromStock, toSignalStrength, uniq } from './helpers'

interface BattlefieldSeed {
  battlefieldId: string
  type: 'THEME' | 'STYLE' | 'INDEPENDENT'
  themeId?: string
  themeName: string
  aliases: string[]
  stocks: MergedStock[]
  continuityScore: number
  carryScore: number
  qualityScore: number
  capitalScore: number
  fragilityScore: number
  themeHeatScore: number
  themeZtCount: number
  themeMainNetInflow: number
  overallCorrelation: number
  persistentDays: number
  isMainLine: boolean
  attentionScore: number
  baseScore: number
  evidence: string[]
  risks: string[]
}

const STYLE_TAGS = ['次新', '低价', '微盘', '重组', '超跌']
const MAX_THEME_BATTLEFIELDS = 12
const MAX_STYLE_BATTLEFIELDS = 3
const MAX_INDEPENDENT_BATTLEFIELDS = 3
const MAX_TOTAL_BATTLEFIELDS = 18

function findThemeIdByName(name: string): string | undefined {
  const allThemes = themeMapping.getAllThemes()
  const exact = allThemes.find((theme) => theme.name === name)
  if (exact) return exact.id
  const fuzzy = allThemes.find((theme) => theme.name.includes(name) || name.includes(theme.name))
  return fuzzy?.id
}

function stockThemeIds(stock: MergedStock): string[] {
  const ids = (stock.themes || [])
    .map((theme: any) => theme?.id || findThemeIdByName(theme?.name || String(theme)))
    .filter(Boolean)
  return uniq(ids as string[])
}

function stockExposuresByTheme(exposures: ThemeExposureProjection, themeId: string) {
  return exposures.byTheme.get(themeId) || []
}

function themeNetInflow(hotTheme: any): number {
  return hotTheme?.mainNetInflow || hotTheme?.jxbk?.mainNetInflow || 0
}

function isStrongCandidate(stock: MergedStock, frameHits: number): boolean {
  return Boolean(
    (stock.leadStatus || '').includes('龙') ||
      (stock.firstZtTime && (stock.compRank || 999) <= 50) ||
      (stock.continuousDays || 0) >= 2 ||
      (stock.highDays || 0) >= 2 ||
      frameHits >= 2 ||
      (stock.popularity || 0) > 0 ||
      (stock.hotness || 0) > 0,
  )
}

function qualityScoreForStocks(stocks: MergedStock[]): number {
  if (!stocks.length) return 0
  const topStocks = [...stocks]
    .sort((a, b) => (b.change || 0) - (a.change || 0))
    .slice(0, 3)
  const healthyTurnoverCount = topStocks.filter((stock) => {
    const rate = stock.turnoverRate || 0
    return rate >= 4 && rate <= 28
  }).length
  return Math.min(100, healthyTurnoverCount * 35 + topStocks.length * 10)
}

function continuityScoreForTheme(themeId: string, frames: ReviewFrame[]): number {
  const hitCount = frames.filter((frame) =>
    frame.hotlist.slice(0, 20).some((item) => item.themes?.some((theme) => theme.id === themeId)),
  ).length
  return frames.length > 0 ? Math.round((hitCount / frames.length) * 100) : 0
}

function carryScoreForStocks(stocks: MergedStock[]): number {
  const followers = stocks.filter((stock) => (stock.change || 0) > 0).length
  const limitUps = stocks.filter((stock) => (stock.change || 0) >= 9.5).length
  return Math.min(100, followers * 12 + limitUps * 20)
}

function capitalScoreForStocks(stocks: MergedStock[], explicitNetInflow?: number): number {
  const topCapital = [...stocks]
    .map((stock) => getNetCapital(stock))
    .sort((a, b) => b - a)
    .slice(0, 3)
    .reduce((sum, value) => sum + value, 0)
  const value = explicitNetInflow || topCapital
  if (value >= 1e9) return 100
  if (value >= 5e8) return 85
  if (value >= 1e8) return 70
  if (value > 0) return 55
  return 25
}

function fragilityScore(zhabanRate: number): number {
  if (zhabanRate >= 35) return 90
  if (zhabanRate >= 22) return 55
  return 20
}

function dominanceFromScores(seed: BattlefieldSeed): BattlefieldDominance {
  const strongCount = [
    seed.continuityScore,
    seed.carryScore,
    seed.qualityScore,
    seed.capitalScore,
  ].filter((score) => score >= 70).length

  if (strongCount >= 3 && seed.fragilityScore < 70) return 'DOMINANT'
  if (strongCount >= 2) return 'CONTESTED'
  return 'WEAK'
}

function labelStrength(score: number): SignalStrength {
  return toSignalStrength(score)
}

function buildThemeFramePresence(frames: ReviewFrame[]) {
  const presence = new Map<string, { frameHits: number; stockCodes: Set<string> }>()
  frames.forEach((frame) => {
    frame.hotlist.slice(0, 20).forEach((item) => {
      ;(item.themes || []).forEach((theme) => {
        const themeId = theme.id || findThemeIdByName(theme.name || '')
        if (!themeId) return
        const current = presence.get(themeId) || { frameHits: 0, stockCodes: new Set<string>() }
        current.frameHits += 1
        current.stockCodes.add(item.code)
        presence.set(themeId, current)
      })
    })
  })
  return presence
}

function qualifiesThemeBattlefield(params: {
  hotThemeRank?: number
  hotTheme?: any
  correlation?: any
  mainLine?: any
  relatedStocks: MergedStock[]
  framePresence?: { frameHits: number; stockCodes: Set<string> }
  strongStockCount: number
  continuityScore: number
}): boolean {
  const persistentDays = params.mainLine?.persistentDays || 0
  const heatScore = params.hotTheme?.heatScore || 0
  const correlation = params.correlation?.overallCorrelation || 0
  const ztCount = params.hotTheme?.ztCount || 0
  const mainNetInflow =
    params.hotTheme?.mainNetInflow || params.hotTheme?.jxbk?.mainNetInflow || 0
  const frameHits = params.framePresence?.frameHits || 0
  const frameStockCount = params.framePresence?.stockCodes.size || 0

  if (persistentDays >= 2) return true
  if ((params.hotThemeRank || 999) <= 5 && ztCount >= 2) return true
  if (mainNetInflow > 0 && correlation >= 0.3 && params.relatedStocks.length >= 2) return true
  if (frameHits >= 2 && frameStockCount >= 2 && params.strongStockCount >= 2 && heatScore >= 55) return true
  if (frameHits >= 3 && frameStockCount >= 3 && params.continuityScore >= 45) return true

  return false
}

function conciseBattlefieldName(name: string | undefined, fallback: string): string {
  const value = (name || '').trim()
  return value || fallback
}

function attentionScoreFromSeed(seed: BattlefieldSeed): number {
  const correlationScore = Math.min(100, Math.round(seed.overallCorrelation * 100))
  const persistentScore = Math.min(100, seed.persistentDays * 25)
  const baseWeight =
    seed.type === 'THEME'
      ? seed.themeHeatScore * 0.25 +
        seed.continuityScore * 0.15 +
        seed.carryScore * 0.18 +
        seed.qualityScore * 0.12 +
        seed.capitalScore * 0.12 +
        correlationScore * 0.1 +
        persistentScore * 0.08
      : seed.type === 'STYLE'
        ? seed.continuityScore * 0.2 +
          seed.carryScore * 0.25 +
          seed.qualityScore * 0.2 +
          seed.capitalScore * 0.2
        : seed.continuityScore * 0.2 +
          seed.carryScore * 0.2 +
          seed.qualityScore * 0.18 +
          seed.capitalScore * 0.18 +
          persistentScore * 0.08

  const ztBonus = Math.min(12, seed.themeZtCount * 2)
  const mainlineBonus = seed.isMainLine ? 10 : 0
  const fragilityPenalty = seed.fragilityScore >= 70 ? 12 : seed.fragilityScore >= 40 ? 6 : 0
  return Math.max(0, Math.min(100, Math.round(baseWeight + ztBonus + mainlineBonus - fragilityPenalty)))
}

export class BattlefieldBuilder {
  build(frames: ReviewFrame[]): BattlefieldRecord[] {
    const currentStocks = dataLayer.getStocks()
    const themeFactors = themeFacade.getThemeFactors()
    const exposureProjection = themeFacade.getThemeExposureProjection()
    const hotThemes = themeFacade.getHotThemesCompat?.(50) || dataLayer.getHotThemes() || []
    const topHotThemes = hotThemes.slice(0, 8)
    const coreHotThemes = hotThemes.slice(0, 5)
    const rotation = themeFacade.getRotationSummary?.() || dataLayer.getCurrentRotation?.()
    const latestFrame = frames[frames.length - 1]
    const zhabanRate = latestFrame?.marketStats.zhabanRate || 0
    const frameHitByCode = new Map<string, number>()
    const themeFramePresence = buildThemeFramePresence(frames)
    const hotThemeRankById = new Map<string, number>()

    frames.forEach((frame) => {
      frame.hotlist.slice(0, 20).forEach((item) => {
        frameHitByCode.set(item.code, (frameHitByCode.get(item.code) || 0) + 1)
      })
    })

    const themeSeeds: BattlefieldSeed[] = []
    const themeIds = new Set<string>()
    const themeFactorById = new Map(themeFactors.map((factor) => [factor.themeId, factor]))

    topHotThemes.forEach((theme: any, index: number) => {
      const themeId = theme.id || findThemeIdByName(theme.name || '')
      if (!themeId) return
      hotThemeRankById.set(themeId, index + 1)
    })

    coreHotThemes.forEach((theme: any) => {
      const themeId = theme.id || findThemeIdByName(theme.name || '')
      if (!themeId) return
      if ((theme.ztCount || 0) < 2) return
      themeIds.add(themeId)
    })

    themeFactors
      .filter((factor) => factor.rotationState === 'mainline' || factor.heatScore >= 75)
      .slice(0, 8)
      .forEach((factor) => {
        themeIds.add(factor.themeId)
        hotThemeRankById.set(factor.themeId, factor.rank)
      })

    rotation?.mainLines?.forEach((line: any) => {
      const themeId = findThemeIdByName(line.themeName || '')
      if (themeId && (line.persistentDays || 0) >= 2) {
        themeIds.add(themeId)
      }
    })

    Array.from(themeFramePresence.entries())
      .filter(([, stat]) => stat.frameHits >= 2 && stat.stockCodes.size >= 2)
      .sort((a, b) => {
        if (b[1].frameHits !== a[1].frameHits) return b[1].frameHits - a[1].frameHits
        return b[1].stockCodes.size - a[1].stockCodes.size
      })
      .slice(0, 8)
      .forEach(([themeId]) => {
        themeIds.add(themeId)
      })

    themeIds.forEach((themeId) => {
      const themeName = conciseBattlefieldName(themeMapping.getThemeName(themeId), themeId)
      const exposureCodes = new Set(
        stockExposuresByTheme(exposureProjection, themeId).map((exposure) => exposure.code),
      )
      const relatedStocks = currentStocks.filter(
        (stock) => stockThemeIds(stock).includes(themeId) || exposureCodes.has(stock.code),
      )
      if (!relatedStocks.length) return

      const hotTheme: any = topHotThemes.find(
        (theme: any) => theme.id === themeId || theme.name === themeName,
      )
      const factor = themeFactorById.get(themeId)
      const correlation = dataLayer.getThemeCorrelation(themeId)
      const mainLine = rotation?.mainLines?.find((line: any) => {
        const lineThemeId = findThemeIdByName(line.themeName || '')
        return lineThemeId === themeId
      })
      const strongStockCount = relatedStocks.filter((stock) => {
        const hits = frameHitByCode.get(stock.code) || 0
        return isStrongCandidate(stock, hits)
      }).length
      const framePresence = themeFramePresence.get(themeId)
      const continuityScore = continuityScoreForTheme(themeId, frames)
      const carryScore = Math.max(
        carryScoreForStocks(relatedStocks),
        (factor?.ztCount || hotTheme?.ztCount || 0) * 18,
      )
      const qualityScore = qualityScoreForStocks(relatedStocks)
      const capitalScore = capitalScoreForStocks(
        relatedStocks,
        factor?.netInflow || themeNetInflow(hotTheme),
      )

      if (
        !qualifiesThemeBattlefield({
          hotThemeRank: hotThemeRankById.get(themeId),
          hotTheme,
          correlation,
          mainLine,
          relatedStocks,
          framePresence,
          strongStockCount,
          continuityScore,
        })
      ) {
        return
      }

      const seed: BattlefieldSeed = {
        battlefieldId: `THEME:${themeId}`,
        type: 'THEME',
        themeId,
        themeName,
        aliases: [themeName],
        stocks: relatedStocks,
        continuityScore,
        carryScore,
        qualityScore,
        capitalScore,
        fragilityScore: fragilityScore(zhabanRate),
        themeHeatScore: factor?.heatScore || hotTheme?.heatScore || 0,
        themeZtCount: factor?.ztCount || hotTheme?.ztCount || 0,
        themeMainNetInflow: factor?.netInflow || themeNetInflow(hotTheme),
        overallCorrelation: factor ? factor.correlationScore / 100 : correlation?.overallCorrelation || 0,
        persistentDays: mainLine?.persistentDays || (factor?.rotationState === 'mainline' ? 1 : 0),
        isMainLine: (mainLine?.persistentDays || 0) >= 2 || factor?.rotationState === 'mainline',
        attentionScore: 0,
        baseScore:
          continuityScore * 0.3 +
          carryScore * 0.25 +
          qualityScore * 0.2 +
          capitalScore * 0.25,
        evidence: [
          continuityScore >= 60 ? '主线在多段快照里持续出现' : '题材持续性一般',
          (hotTheme?.heatScore || 0) >= 60 ? `题材热度 ${Math.round(hotTheme?.heatScore || 0)}` : '题材热度一般',
          (hotTheme?.ztCount || 0) >= 2 ? `题材涨停数 ${hotTheme?.ztCount || 0}` : '题材涨停扩散不足',
          (mainLine?.persistentDays || 0) >= 2 ? `主线持续 ${mainLine?.persistentDays || 0} 天` : '主线持续不足',
          strongStockCount >= 2 ? `强势成员 ${strongStockCount} 只` : '强势成员不足',
          correlation?.overallCorrelation && correlation.overallCorrelation >= 0.3
            ? `联动性 ${correlation.overallCorrelation.toFixed(2)}`
            : '联动性一般',
        ],
        risks: [
          zhabanRate >= 30 ? '市场炸板率偏高' : '',
          relatedStocks.length <= 2 ? '板块跟风不足' : '',
        ].filter(Boolean),
      }
      themeSeeds.push(seed)
    })

    const styleSeeds = STYLE_TAGS.reduce<BattlefieldSeed[]>((result, tag) => {
      const stocks = currentStocks.filter((stock) => getStockTagNames(stock).includes(tag))
      if (stocks.length < 3) return result
      const carryScore = carryScoreForStocks(stocks)
      const qualityScore = qualityScoreForStocks(stocks)
      if (carryScore < 40 && qualityScore < 45) return result

      result.push({
        battlefieldId: `STYLE:${tag}`,
        type: 'STYLE',
        themeName: tag,
        aliases: [tag],
        stocks,
        continuityScore: Math.min(100, stocks.length * 15),
        carryScore,
        qualityScore,
        capitalScore: capitalScoreForStocks(stocks),
        fragilityScore: fragilityScore(zhabanRate),
        themeHeatScore: 0,
        themeZtCount: 0,
        themeMainNetInflow: 0,
        overallCorrelation: 0,
        persistentDays: 0,
        isMainLine: false,
        attentionScore: 0,
        baseScore: stocks.length * 10 + qualityScore,
        evidence: [`风格标签 ${tag}`],
        risks: ['仅作解释层，不参与总龙头竞争'],
      })

      return result
    }, [])
      .sort((a, b) => b.baseScore - a.baseScore)
      .slice(0, MAX_STYLE_BATTLEFIELDS)

    const independentSeeds: BattlefieldSeed[] = currentStocks
      .filter((stock) => stockThemeIds(stock).length === 0)
      .filter((stock) => {
        const hits = frameHitByCode.get(stock.code) || 0
        return (
          (stock.continuousDays || 0) >= 2 ||
          ((stock.leadStatus || '').includes('龙') && hits >= 2) ||
          (hits >= 3 && (stock.hotness || 0) >= 55)
        )
      })
      .map((stock) => ({
        battlefieldId: `INDEPENDENT:${stock.code}`,
        type: 'INDEPENDENT' as const,
        themeName: stock.name,
        aliases: themeNamesFromStock(stock),
        stocks: [stock],
        continuityScore: Math.min(100, (frameHitByCode.get(stock.code) || 0) * 30),
        carryScore: carryScoreForStocks([stock]),
        qualityScore: qualityScoreForStocks([stock]),
        capitalScore: capitalScoreForStocks([stock]),
        fragilityScore: fragilityScore(zhabanRate),
        themeHeatScore: stock.themeHeat || 0,
        themeZtCount: 0,
        themeMainNetInflow: getNetCapital(stock),
        overallCorrelation: 0,
        persistentDays: stock.continuousDays || 0,
        isMainLine: false,
        attentionScore: 0,
        baseScore:
          (frameHitByCode.get(stock.code) || 0) * 20 +
          (stock.continuousDays || 0) * 15 +
          (stock.change || 0),
        evidence: ['缺少稳定题材映射，按独立战场处理'],
        risks: ['默认不直接参与市场总龙头竞争'],
      }))
      .sort((a, b) => b.baseScore - a.baseScore)
      .slice(0, MAX_INDEPENDENT_BATTLEFIELDS)

    const enrichSeedAttentionScore = (seed: BattlefieldSeed): BattlefieldSeed => ({
      ...seed,
      attentionScore: attentionScoreFromSeed(seed),
    })

    const seeds = [
      ...themeSeeds
        .sort((a, b) => b.baseScore - a.baseScore)
        .slice(0, MAX_THEME_BATTLEFIELDS),
      ...styleSeeds,
      ...independentSeeds,
    ]
      .sort((a, b) => b.baseScore - a.baseScore)
      .slice(0, MAX_TOTAL_BATTLEFIELDS)
      .map(enrichSeedAttentionScore)

    return seeds.map((seed, index) => {
      let dominance = dominanceFromScores(seed)
      const nextSeed = seeds[index + 1]
      if (
        nextSeed &&
        seed.type === 'THEME' &&
        nextSeed.type === 'THEME' &&
        Math.abs(seed.baseScore - nextSeed.baseScore) <= 8 &&
        dominance !== 'WEAK'
      ) {
        dominance = 'CONTESTED'
      }

      return {
        battlefieldId: seed.battlefieldId,
        type: seed.type,
        themeId: seed.themeId,
        themeName: seed.themeName,
        aliases: uniq(seed.aliases.filter(Boolean)),
        dominance,
        continuity: labelStrength(seed.continuityScore),
        carryStrength: labelStrength(seed.carryScore),
        quality: labelStrength(seed.qualityScore),
        capital: labelStrength(seed.capitalScore),
        fragility: seed.fragilityScore >= 70 ? 'high' : seed.fragilityScore >= 40 ? 'mid' : 'low',
        themeHeatScore: seed.themeHeatScore,
        themeZtCount: seed.themeZtCount,
        themeMainNetInflow: seed.themeMainNetInflow,
        overallCorrelation: seed.overallCorrelation,
        persistentDays: seed.persistentDays,
        isMainLine: seed.isMainLine,
        attentionScore: seed.attentionScore,
        candidateCodes: seed.stocks.map((stock) => stock.code),
        challengerCodes: [],
        followerCodes: [],
        evidence: seed.evidence,
        risks: seed.risks,
      }
    })
  }
}

export const battlefieldBuilder = new BattlefieldBuilder()
