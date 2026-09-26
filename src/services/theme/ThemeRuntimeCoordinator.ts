import { dataLayer } from '@/services/DataLayer'
import { debugLog } from '@/utils/logger'
import { projectThemeStockExposures } from './ThemeStockProjector'
import { themeHeatFeed } from './ThemeHeatFeed'
import { themeRuntimeStore } from './ThemeRuntimeStore'
import { themeRepository } from './ThemeRepository'
import { deriveThemeHeatLevel } from './stockThemeMeta'
import { refreshScheduler } from '@/services/refresh/RefreshTaskRuntime'
import { ROTATION_CONFIG } from '@/config/constants'
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

let previousSignature = ''

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
  qualitySummary: ThemeRuntimeQualitySummary,
): ThemeRuntimeChangedField[] {
  if (signature === previousSignature) return []
  return [
    factors.length ? 'factors' : null,
    exposures.byCode.size ? 'exposures' : null,
    qualitySummary.totalFlags ? 'quality' : null,
  ].filter(Boolean) as ThemeRuntimeChangedField[]
}

function syncStocks(exposures: ThemeExposureProjection): number {
  const updates = Array.from(exposures.byCode.entries()).map(([code, items]) => {
    const sorted = [...items].sort((a, b) => b.themeContribution - a.themeContribution)
    const main = sorted[0]
    // themeHeat = 主题材 heatLevel 相对分（0-100）或缺失（undefined，不伪装 0）
    const mainHeat = main?.themeScore ?? undefined
    return {
      code,
      themes: sorted.map((exposure) => ({
        id: exposure.themeId,
        name: exposure.themeName,
        heatScore: exposure.themeScore ?? undefined,
        role: exposure.role,
        roleScore: exposure.roleScore,
        exposureWeight: exposure.exposureWeight,
        themeContribution: exposure.themeContribution,
        riskPenalty: exposure.riskPenalty,
        reasons: exposure.reasons,
      })),
      mainTheme: main?.themeName,
      themeHeat: mainHeat,
      themeLevel: deriveThemeHeatLevel(main?.themeScore ?? null),
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
  const qualitySummary = buildQualitySummary(factors)
  const changedFields = changedFieldsFor(signature, factors, exposures, qualitySummary)
  const syncedStockCount = options.syncStocks ? syncStocks(exposures) : 0
  if (syncedStockCount > 0 && !changedFields.includes('stocks')) changedFields.push('stocks')

  themeRuntimeStore.update({
    factors,
    exposures,
    lastUpdate: timestamp,
    inputSignature: signature,
    factorVersion,
    qualitySummary,
    refreshSource: options.source,
    changedFields,
  })

  previousSignature = signature

  const result: ThemeRuntimeRefreshResult = {
    factors,
    exposures,
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
    factors: result.factors.length,
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
    // 唯一因子来源是后端 /api/theme-heat feed：题材热度/动量/轮动状态均由后端生产，
    // 前端不本地计算、不保留 fallback（feed 为空即空态，绝不本地补算产生第二套语义）
    const factors = themeHeatFeed.getRuntimeFactors()
    return executeWithFactors(
      options.context,
      factors,
      options,
      themeHeatFeed.getSnapshot()?.factorVersion || THEME_FACTOR_VERSION,
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

/**
 * 显式启动热门题材因子周期刷新（theme.runtime 任务，交易时段限定）。
 * 由 App.vue 启动编排调用；不采用模块顶层副作用自启动。
 */
export function startRuntimeRefresh(interval: number = ROTATION_CONFIG.ANALYSIS_INTERVAL): void {
  if (!ROTATION_CONFIG.ENABLED) return
  // 不传 syncStocks：股票主题同步由 dataLoader/sectorAnalyzer 在数据变化时驱动，
  // 周期任务只刷新因子，避免每 30s 无条件全量写 merged.stocks
  refreshScheduler.registerRunner('theme.runtime', () => {
    void refreshRuntime({ source: 'themeRuntime' })
  })
  refreshScheduler.startTask('theme.runtime', interval)
}

