import { dataLayer } from '@/services/DataLayer'
import { themeMapping } from '@/services/ThemeDataService'
import { debugLog } from '@/utils/logger'
import { buildThemeFactors } from './ThemeFactorEngine'
import { projectThemeStockExposures } from './ThemeStockProjector'
import { buildThemeRotationSummary } from './ThemeRotationEngine'
import { buildThemeEvents } from './ThemeAlertEngine'
import { buildLegacyBlockThemeEvents } from './ThemeLegacyAlertAdapter'
import { themeRuntimeStore } from './ThemeRuntimeStore'
import { jxbkThemeFeed } from './JxbkThemeFeed'
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
        stock.lianban,
        stock.lianbanStr,
        stock.continuousDays,
        stock.fengdan,
        stock.volumeRatio,
        stock.mainNetInflow,
        stock.popularity,
      ])
      .sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
    jxbkBlocks: (context.jxbkBlocks || [])
      .map((block) => [block.code, block.name, block.strength, block.change, block.mainNetInflow, block.ztCount])
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
      themeLevel:
        (main?.themeScore || 0) >= 80
          ? '热门'
          : (main?.themeScore || 0) >= 60
            ? '活跃'
            : (main?.themeScore || 0) >= 40
              ? '温'
              : (main?.themeScore || 0) >= 20
                ? '冷'
                : '冰',
    }
  })
  if (updates.length) dataLayer.updateStockThemes(updates)
  return updates.length
}

function buildDefaultContext(timestamp?: number, snapshotId?: string): ThemeSourceContext {
  const themes = themeMapping.getAllThemes().map((theme) => ({
    id: theme.id,
    name: theme.name,
    zsCode: theme.zsCode,
  }))
  const themeStocks = new Map<string, string[]>()
  const stockThemes = new Map<string, string[]>()
  themes.forEach((theme) => {
    const stocks = themeMapping.getThemeStocks(theme.id)
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
    jxbkBlocks: dataLayer.getJxbkBlocksSorted?.() || [],
    rotationAnalysis: dataLayer.getCurrentRotation?.() || null,
    correlations: new Map(),
  }
}

export function refreshRuntime(options: ThemeRuntimeRefreshOptions & { context: ThemeSourceContext }): ThemeRuntimeRefreshResult
export async function refreshRuntime(options: ThemeRuntimeRefreshOptions): Promise<ThemeRuntimeRefreshResult>
export function refreshRuntime(options: ThemeRuntimeRefreshOptions): ThemeRuntimeRefreshResult | Promise<ThemeRuntimeRefreshResult> {
  const execute = (context: ThemeSourceContext): ThemeRuntimeRefreshResult => {
    const timestamp = context.timestamp || options.timestamp || Date.now()
    const signature = themeInputSignature(context)
    const factors = buildThemeFactors(context)
    const exposures = projectThemeStockExposures(context, factors)
    const rotationSummary =
      signature === previousSignature && previousRotation
        ? previousRotation
        : buildThemeRotationSummary(factors, {
            timestamp,
            previous: previousRotation || dataLayer.getCurrentRotation?.() || null,
          })
    const themeEvents = buildThemeEvents({
      factors,
      exposures,
      previousFactors,
      timestamp,
    })
    const legacyEvents = buildLegacyBlockThemeEvents({
      timestamp,
      blocks: context.jxbkBlocks || [],
      stockMap: jxbkThemeFeed.getStockMap(),
    })
    const events = [...themeEvents, ...legacyEvents].filter((event, index, array) => {
      const key = `${event.alertType || event.type}:${event.themeId}`
      return array.findIndex((item) => `${item.alertType || item.type}:${item.themeId}` === key) === index
    })
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
      factorVersion: THEME_FACTOR_VERSION,
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

  if (options.context) return execute(options.context)

  if (options.forceJxbk && !options.skipJxbkRefresh) {
    return jxbkThemeFeed.refreshBlocks({ force: options.force }).then(() =>
      execute(buildDefaultContext(options.timestamp, options.snapshotId)),
    )
  }

  return execute(buildDefaultContext(options.timestamp, options.snapshotId))
}
