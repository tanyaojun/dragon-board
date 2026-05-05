import type {
  MarketPhaseType,
  RotationAnalysis,
  RotationDirection,
  RotationStrength,
  ThemeRotationStatus,
} from '@/types/core'
import type { ThemeFactorSnapshot } from './types'

type RotationBuildOptions = {
  timestamp?: number
  previous?: RotationAnalysis | null
}

function directionFor(factor: ThemeFactorSnapshot): RotationDirection {
  if (factor.netInflow > 0 || factor.rotationState === 'inflow' || factor.rotationState === 'mainline') {
    return 'inflow'
  }
  if (factor.netInflow < 0 || factor.rotationState === 'outflow' || factor.rotationState === 'cooling') {
    return 'outflow'
  }
  return 'neutral'
}

function strengthFor(score: number): RotationStrength {
  if (score >= 70) return 'strong'
  if (score >= 45) return 'medium'
  return 'weak'
}

function previousByTheme(previous?: RotationAnalysis | null): Map<string, ThemeRotationStatus> {
  const result = new Map<string, ThemeRotationStatus>()
  if (!previous) return result
  ;[
    ...previous.inflowThemes,
    ...previous.outflowThemes,
    ...previous.mainLines,
    ...previous.quickRotation,
  ].forEach((status) => {
    if (!result.has(status.themeId)) result.set(status.themeId, status)
  })
  return result
}

function persistentDaysFor(
  factor: ThemeFactorSnapshot,
  direction: RotationDirection,
  previousStatus?: ThemeRotationStatus,
): number {
  if (!previousStatus) return factor.rotationState === 'mainline' ? 1 : 0
  const sameDirection = previousStatus.direction === direction
  const stayedMainline = previousStatus.isMainLine && factor.rotationState === 'mainline'
  if (sameDirection || stayedMainline) return Math.max(1, previousStatus.persistentDays + 1)
  return factor.rotationState === 'mainline' ? 1 : 0
}

function marketPhaseFor(statuses: ThemeRotationStatus[], rotationSpeed: number): MarketPhaseType {
  const mainLineCount = statuses.filter((status) => status.isMainLine).length
  const inflowCount = statuses.filter((status) => status.direction === 'inflow').length
  const outflowCount = statuses.filter((status) => status.direction === 'outflow').length
  const coolingCount = statuses.filter((status) => status.topReasons?.includes('题材降温')).length

  if (statuses.length === 0) return 'accumulation'
  if (outflowCount > inflowCount * 1.5 || coolingCount >= Math.max(2, mainLineCount)) return 'falling'
  if (rotationSpeed >= 70 && mainLineCount >= 3) return 'climax'
  if (mainLineCount > 0 || inflowCount > outflowCount) return 'rising'
  if (inflowCount > 0 && outflowCount > 0 && Math.abs(inflowCount - outflowCount) <= 2) {
    return 'distribution'
  }
  return 'accumulation'
}

function suggestionFor(phase: MarketPhaseType, mainLines: ThemeRotationStatus[]): string {
  const base: Record<MarketPhaseType, string> = {
    ice: '冰点期：等待题材企稳',
    accumulation: '筑底期：关注率先转强题材',
    rising: '上升期：跟踪主线题材',
    climax: '高潮期：注意拥挤和分化',
    distribution: '出货期：控制仓位，减少追高',
    falling: '退潮期：规避降温题材',
  }
  const mainLineNames = mainLines
    .slice(0, 3)
    .map((theme) => theme.themeName)
    .join('、')
  return mainLineNames ? `${base[phase]} 主线：${mainLineNames}` : base[phase]
}

export function buildThemeRotationSummary(
  factors: ThemeFactorSnapshot[],
  options: RotationBuildOptions = {},
): RotationAnalysis {
  const previous = previousByTheme(options.previous)
  const orderedFactors = [...factors].sort((a, b) => {
    const rankDiff = a.rank - b.rank
    if (rankDiff !== 0) return rankDiff
    return b.heatScore - a.heatScore
  })

  const statuses = orderedFactors.map<ThemeRotationStatus>((factor, index) => {
    const previousStatus = previous.get(factor.themeId)
    const rank = index + 1
    const rankChange = previousStatus?.rank ? previousStatus.rank - rank : 0
    const direction = directionFor(factor)
    const persistentDays = persistentDaysFor(factor, direction, previousStatus)
    const isMainLine =
      factor.rotationState === 'mainline' ||
      (persistentDays >= 2 && factor.heatScore >= 70 && factor.netInflow >= 0)

    return {
      themeId: factor.themeId,
      themeName: factor.themeName,
      inflow: Math.max(0, factor.netInflow),
      outflow: Math.max(0, -factor.netInflow),
      netInflow: factor.netInflow,
      avgChange: factor.momentumScore,
      totalTurnover: 0,
      ztCount: factor.ztCount,
      stockCount: factor.stockCount,
      rank,
      rankChange,
      direction,
      strength: strengthFor(factor.heatScore),
      persistentDays,
      isMainLine,
      relatedThemes: factor.relatedThemeIds.map((id) => ({ id, name: id, correlation: 0 })),
      strengthScore: factor.heatScore,
      volumeRatio: factor.volumeRatio,
      bigMoney300: 0,
      institutionBuy: 0,
      inflowChange: 0,
      totalBoardHeight: 0,
      avgBoardHeight: 0,
      highDays: 0,
      topReasons: factor.rotationState === 'cooling' ? ['题材降温'] : [],
    }
  })

  const inflowThemes = statuses.filter((status) => status.direction === 'inflow')
  const outflowThemes = statuses.filter((status) => status.direction === 'outflow')
  const mainLines = statuses.filter((status) => status.isMainLine)
  const strongThemes = statuses.filter((status) => (status.strengthScore || 0) >= 70)
  const quickRotation = statuses.filter((status) => Math.abs(status.rankChange) >= 3)
  const rotationSpeed =
    statuses.length === 0
      ? 0
      : Math.min(
          100,
          Math.round(
            statuses.reduce((sum, status) => sum + Math.abs(status.rankChange), 0) /
              statuses.length *
              18,
          ),
        )
  const marketPhase = marketPhaseFor(statuses, rotationSpeed)

  return {
    timestamp: options.timestamp || Date.now(),
    inflowThemes: inflowThemes.slice(0, 10),
    outflowThemes: outflowThemes.slice(0, 10),
    mainLines: mainLines.slice(0, 5),
    strongThemes: strongThemes.slice(0, 5).map((status) => ({
      themeId: status.themeId,
      themeName: status.themeName,
      strengthScore: status.strengthScore || 0,
    })),
    quickRotation: quickRotation.slice(0, 5),
    rotationSpeed,
    marketPhase,
    summary: {
      mainLineCount: mainLines.length,
      inflowCount: inflowThemes.length,
      outflowCount: outflowThemes.length,
      topInflow: inflowThemes[0]?.themeName || '无',
      topOutflow: outflowThemes[0]?.themeName || '无',
      suggestion: suggestionFor(marketPhase, mainLines),
      strongCount: strongThemes.length,
      topStrength: strongThemes[0]?.themeName || '无',
    },
  }
}
