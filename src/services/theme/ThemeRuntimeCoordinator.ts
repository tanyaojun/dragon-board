import { dataLayer } from '@/services/DataLayer'
import { debugLog } from '@/utils/logger'
import { buildThemeFactors } from './ThemeFactorEngine'
import { projectThemeStockExposures } from './ThemeStockProjector'
import { buildThemeRotationSummary } from './ThemeRotationEngine'
import { buildThemeEvents } from './ThemeAlertEngine'
import { themeHeatFeed } from './ThemeHeatFeed'
import { themeRuntimeStore } from './ThemeRuntimeStore'
import { themeRepository } from './ThemeRepository'
import { deriveThemeHeatLevel } from './stockThemeMeta'
import type {
  ThemeExposureProjection,
  ThemeFactorSnapshot,
  ThemeRuntimeChangedField,
  ThemeRuntimeQualitySummary,
  ThemeRuntimeRefreshOptions,
  ThemeRuntimeRefreshResult,
  ThemeSourceContext,
} from './types'

export const THEME_FACTOR_VERSION = 'theme-factor-v1'
export const THEME_EVENT_VERSION = 'theme-event-v1'

let previousSignature = ''
let previousFactors: ThemeFactorSnapshot[] = []
let previousRotation = null as ThemeRuntimeRefreshResult['rotationSummary']
let previousEvents: ThemeRuntimeRefreshResult['events'] = []

export function themeInputSignature(context: ThemeSourceContext): string {
  return JSON.stringify({
    themes: context.themes.map((theme) => theme.id).sort(),
    stocks: context.stocks
      .map((stock: any) => [
        stock.code,
        stock.name,
        stock.change,
        stock.isZT,
        stock.continuousDays,
        stock.volumeRatio,
        stock.mainNetInflow,
      ])
      .sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
  })
}

export function buildQualitySummary(factors: ThemeFactorSnapshot[]): ThemeRuntimeQualitySummary {
  const summary: ThemeRuntimeQualitySummary = {
    totalFlags: 0,
    fatalCount: 0,
    warningCount: 0,
    infoCount: 0,
    byCode: {},
  }
  factors.forEach((factor) => {
    factor.qualityFlags.forEach((flag) => {
      summary.totalFlags++
      if (flag.level === 'fatal') summary.fatalCount++
      if (flag.level === 'warning') summary.warningCount++
      if (flag.level === 'info') summary.infoCount++
      summary.byCode[flag.code] = (summary.byCode[flag.code] || 0) + 1
    })
  })
  return summary
}

function changedFieldsFor(
  signature: string,
  factors: ThemeFactorSnapshot[],
  exposures: ThemeExposureProjection,
  events: ThemeRuntimeRefreshResult['events'],
  qualitySummary: ThemeRuntimeQualitySummary,
): ThemeRuntimeChangedField[] {
  if (signature === previousSignature) return []
  return [
    factors.length ? 'factors' : null,
    exposures.byCode.size ? 'exposures' : null,
    'rotation',
    events.length ? 'events' : null,
    qualitySummary.totalFlags ? 'quality' : null,
  ].filter(Boolean) as ThemeRuntimeChangedField[]
}

function syncStocks(exposures: ThemeExposureProjection): number {
  const updates = Array.from(exposures.byCode.entries()).map(([code, items]) => {
    const sorted = [...items].sort((a, b) => b.themeContribution - a.themeContribution)
    const main = sorted[0]
    return {
      code,
      themes: sorted.map((exposure) => ({
        id: exposure.themeId,
        name: exposure.themeName,
        heatScore: exposure.themeScore,
        role: exposure.role,
        roleScore: exposure.roleScore,
        exposureWeight: exposure.exposureWeight,
        themeContribution: exposure.themeContribution,
        riskPenalty: exposure.riskPenalty,
        reasons: exposure.reasons,
      })),
      mainTheme: main?.themeName,
      themeHeat: main?.themeScore || 0,
      themeLevel: deriveThemeHeatLevel(main?.themeScore || 0),
    }
  })
  if (updates.length) dataLayer.updateStockThemes(updates)
  return updates.length
}

function buildDefaultContext(timestamp?: number, snapshotId?: string): ThemeSourceContext {
  const themes = themeRepository.getThemes().map((theme) => ({
    id: theme.id,
    name: theme.name,
    zsCode: theme.zsCode,
  }))
  const themeStocks = new Map<string, string[]>()
  const stockThemes = new Map<string, string[]>()
  themes.forEach((theme) => {
    const stocks = themeRepository.getThemeStocks(theme.id)
    themeStocks.set(theme.id, stocks)
    stocks.forEach((code) => {
      if (!stockThemes.has(code)) stockThemes.set(code, [])
      stockThemes.get(code)!.push(theme.id)
    })
  })
  return {
    timestamp: timestamp || Date.now(),
    snapshotId,
    themes,
    themeStocks,
    stockThemes,
    stocks: dataLayer.getStocks(),
    rotationAnalysis: dataLayer.getCurrentRotation?.() || null,
    correlations: new Map(),
  }
}

function executeWithFactors(
  context: ThemeSourceContext,
  factors: ThemeFactorSnapshot[],
  options: ThemeRuntimeRefreshOptions,
  factorVersion: string,
): ThemeRuntimeRefreshResult {
  const timestamp = context.timestamp || options.timestamp || Date.now()
  const signature = JSON.stringify({
    context: themeInputSignature(context),
    factors: factors.map((factor) => [factor.themeId, factor.heatScore, factor.momentumScore, factor.rank]),
  })
  const exposures = projectThemeStockExposures(context, factors)
  const rotationSummary =
    signature === previousSignature && previousRotation
      ? previousRotation
      : buildThemeRotationSummary(factors, {
          timestamp,
          previous: previousRotation || dataLayer.getCurrentRotation?.() || null,
        })
  const events = buildThemeEvents({ factors, exposures, previousFactors, timestamp })
  const qualitySummary = buildQualitySummary(factors)
  const changedFields = changedFieldsFor(signature, factors, exposures, events, qualitySummary)
  const syncedStockCount = options.syncStocks ? syncStocks(exposures) : 0
  if (syncedStockCount > 0 && !changedFields.includes('stocks')) changedFields.push('stocks')

  themeRuntimeStore.update({
    factors,
    exposures,
    rotationSummary,
    events,
    correlations: context.correlations || new Map(),
    lastUpdate: timestamp,
    inputSignature: signature,
    factorVersion,
    eventVersion: THEME_EVENT_VERSION,
    qualitySummary,
    refreshSource: options.source,
    changedFields,
  })
  if (rotationSummary) dataLayer.updateRotationAnalysis(rotationSummary)

  previousSignature = signature
  previousFactors = factors
  previousRotation = rotationSummary
  previousEvents = events

  const result: ThemeRuntimeRefreshResult = {
    factors,
    exposures,
    rotationSummary,
    events,
    qualitySummary,
    changedFields,
    inputSignature: signature,
    source: options.source,
    timestamp,
    syncedStockCount,
  }
  debugLog('[ThemeRuntimeCoordinator] refreshRuntime', {
    source: result.source,
    changedFields: result.changedFields,
    factors: factors.length,
    events: events.length,
  })
  return result
}

export function refreshRuntime(
  options: ThemeRuntimeRefreshOptions & { context: ThemeSourceContext },
): ThemeRuntimeRefreshResult
export async function refreshRuntime(options: ThemeRuntimeRefreshOptions): Promise<ThemeRuntimeRefreshResult>
export function refreshRuntime(
  options: ThemeRuntimeRefreshOptions,
): ThemeRuntimeRefreshResult | Promise<ThemeRuntimeRefreshResult> {
  if (options.context) {
    return executeWithFactors(
      options.context,
      buildThemeFactors(options.context),
      options,
      THEME_FACTOR_VERSION,
    )
  }

  return themeHeatFeed.refresh({ force: options.force }).then((snapshot) => {
    const context = buildDefaultContext(snapshot.computedAt || options.timestamp, options.snapshotId)
    return executeWithFactors(
      context,
      themeHeatFeed.getRuntimeFactors(),
      options,
      snapshot.factorVersion || 'theme-market-v1',
    )
  })
}
