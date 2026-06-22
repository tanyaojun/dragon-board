import { ALERT_LEVELS } from '@/config/constants'
import { dedupeByKey } from './utils'
import type { ThemeEvent, ThemeExposureProjection, ThemeFactorSnapshot } from './types'

type ThemeAlertBuildContext = {
  factors: ThemeFactorSnapshot[]
  exposures?: ThemeExposureProjection
  previousFactors?: ThemeFactorSnapshot[]
  timestamp?: number
}

function eventId(type: ThemeEvent['type'], factor: ThemeFactorSnapshot, timestamp: number): string {
  return `${type}:${factor.themeId}:${timestamp}`
}

function hasFatalQuality(factor: ThemeFactorSnapshot): boolean {
  return factor.qualityFlags.some((flag) => flag.level === 'fatal')
}

function stockCodesFor(exposures: ThemeExposureProjection | undefined, themeId: string): string[] {
  return (exposures?.byTheme.get(themeId) || [])
    .slice(0, 10)
    .map((exposure) => exposure.code)
    .filter(Boolean)
}

function baseEvent(
  type: ThemeEvent['type'],
  factor: ThemeFactorSnapshot,
  timestamp: number,
  reasons: string[],
  stockCodes: string[],
): ThemeEvent {
  const riskFlags =
    factor.crowdingRisk >= 80
      ? ['crowding_high']
      : factor.rotationState === 'cooling'
        ? ['theme_cooling']
        : []
  const level =
    type === 'theme_crowding_high' || type === 'theme_leader_fall'
      ? ALERT_LEVELS.WARNING
      : type === 'theme_mapping_quality_warning'
        ? ALERT_LEVELS.WARNING
        : ALERT_LEVELS.INFO

  return {
    id: eventId(type, factor, timestamp),
    type,
    level,
    themeId: factor.themeId,
    themeName: factor.themeName,
    timestamp,
    source: 'theme',
    factorSnapshotId: factor.snapshotId,
    stockCodes,
    metrics: {
      heatScore: factor.heatScore,
      momentumScore: factor.momentumScore,
      fundScore: factor.fundScore,
      leadershipScore: factor.leadershipScore,
      crowdingRisk: factor.crowdingRisk,
      rotationState: factor.rotationState,
    },
    riskFlags,
    reasons,
  }
}

export function buildThemeEvents(context: ThemeAlertBuildContext): ThemeEvent[] {
  const timestamp = context.timestamp || Date.now()
  const previousByTheme = new Map(
    (context.previousFactors || []).map((factor) => [factor.themeId, factor]),
  )
  const events: ThemeEvent[] = []

  context.factors.forEach((factor) => {
    const stockCodes = stockCodesFor(context.exposures, factor.themeId)
    const previous = previousByTheme.get(factor.themeId)
    const hasQualityWarning = factor.qualityFlags.length > 0

    if (hasQualityWarning) {
      events.push(
        baseEvent(
          'theme_mapping_quality_warning',
          factor,
          timestamp,
          factor.qualityFlags.map((flag) => flag.message || flag.code),
          stockCodes,
        ),
      )
    }

    // Fatal quality means the source facts are not trustworthy enough to emit business alerts.
    if (hasFatalQuality(factor)) return

    if (factor.rotationState === 'mainline' && previous?.rotationState !== 'mainline') {
      events.push(baseEvent('theme_mainline_started', factor, timestamp, ['题材进入主线'], stockCodes))
    }

    if (factor.momentumScore >= 75 && factor.heatScore >= 70) {
      events.push(baseEvent('theme_strength_surge', factor, timestamp, ['题材强度快速上升'], stockCodes))
    }

    if (factor.fundScore !== null && factor.netInflow !== null && factor.fundScore >= 70 && factor.netInflow > 0) {
      events.push(baseEvent('theme_fund_inflow', factor, timestamp, ['主力资金流入增强'], stockCodes))
    }

    if (factor.crowdingRisk >= 75) {
      events.push(baseEvent('theme_crowding_high', factor, timestamp, ['题材拥挤度偏高'], stockCodes))
    }

    if (factor.rotationState === 'cooling') {
      events.push(baseEvent('theme_cooling', factor, timestamp, ['题材处于降温状态'], stockCodes))
    }

    if (factor.leadershipScore <= 20 && previous && previous.leadershipScore >= 60) {
      events.push(baseEvent('theme_leader_fall', factor, timestamp, ['龙头强度明显回落'], stockCodes))
    }
  })

  return dedupeByKey(events, (e) => `${e.type}:${e.themeId}`)
}
