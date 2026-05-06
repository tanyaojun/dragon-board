import { apiService } from '@/services/apiService'

export interface ThemeResearchThemeSummary {
  themeId: string
  themeName: string
  heatScore?: number
  crowdingRisk?: number
}

export interface ThemeResearchSummary {
  available: boolean
  reason?: string
  lifecycleDistribution?: Record<string, number>
  mainlineThemes?: ThemeResearchThemeSummary[]
  crowdingAlerts?: ThemeResearchThemeSummary[]
  researchGrade?: string
  qualityPassed?: boolean
  themeCount?: number
  signalCount?: number
}

export interface ThemeResearchExplanation {
  available: boolean
  statusText: string
  mainlineText: string
  riskText: string
  leaderConfirmationText: string
  hotlistConfluenceText: string
  warnings: string[]
  mainlineThemeNames: string[]
  crowdedThemeNames: string[]
}

export interface HotlistThemeResearchItem {
  code: string
  name: string
  themeName: string
  themeRole: string
  confluenceScore: number
  noise: boolean
  entryReason: string
  filterReason: string
}

function formatThemeNames(themes: ThemeResearchThemeSummary[] | undefined, limit = 3): string {
  const names = (themes || []).slice(0, limit).map((theme) => theme.themeName).filter(Boolean)
  return names.length ? names.join('、') : '暂无'
}

export function buildThemeResearchExplanation(summary: ThemeResearchSummary | null | undefined): ThemeResearchExplanation {
  if (!summary?.available) {
    return {
      available: false,
      statusText: `研究摘要不可用${summary?.reason ? `：${summary.reason}` : ''}`,
      mainlineText: '实时题材仍由 themeFacade 提供',
      riskText: '研究侧拥挤/背离摘要不可用',
      leaderConfirmationText: '龙头确认暂不使用研究摘要降级',
      hotlistConfluenceText: '热榜共振解释暂不可用',
      warnings: ['quantboard_research_unavailable'],
      mainlineThemeNames: [],
      crowdedThemeNames: [],
    }
  }

  const lifecycle = summary.lifecycleDistribution || {}
  const mainlineCount = Number(lifecycle.mainline || 0)
  const crowdedCount = Number(lifecycle.crowded || 0) + Number(lifecycle.divergence || 0)
  const mainlineText = `主线 ${mainlineCount} 个：${formatThemeNames(summary.mainlineThemes)}`
  const riskText = summary.crowdingAlerts?.length
    ? `拥挤/背离警告：${formatThemeNames(summary.crowdingAlerts)}`
    : '未触发拥挤/背离警告'
  const grade = summary.researchGrade || (summary.qualityPassed ? 'research_ready' : 'degraded')
  const warnings = [
    ...(crowdedCount > 0 ? ['crowding_or_divergence_present'] : []),
    ...(grade !== 'research_ready' ? ['research_grade_degraded'] : []),
  ]

  return {
    available: true,
    statusText: `研究摘要可用 · ${grade} · ${summary.themeCount ?? 0} 题材 / ${summary.signalCount ?? 0} 信号`,
    mainlineText,
    riskText,
    leaderConfirmationText: mainlineCount > 0
      ? `龙头优先确认是否属于 ${formatThemeNames(summary.mainlineThemes, 2)}`
      : '龙头暂缺主线题材确认',
    hotlistConfluenceText: crowdedCount > 0
      ? '热榜候选需过滤拥挤、背离和噪声暴露'
      : '热榜候选可使用题材强度与生命周期做共振解释',
    warnings,
    mainlineThemeNames: (summary.mainlineThemes || []).map((theme) => theme.themeName).filter(Boolean),
    crowdedThemeNames: (summary.crowdingAlerts || []).map((theme) => theme.themeName).filter(Boolean),
  }
}

function toNumber(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

export function buildHotlistThemeResearchItems(
  stocks: Array<Record<string, any>>,
  explanation: ThemeResearchExplanation,
  limit = 8,
): HotlistThemeResearchItem[] {
  if (!explanation.available) {
    return []
  }
  const mainline = new Set(explanation.mainlineThemeNames)
  const crowded = new Set(explanation.crowdedThemeNames)
  return stocks.slice(0, limit).map((stock) => {
    const primaryTheme = Array.isArray(stock.themes) ? stock.themes[0] : undefined
    const themeName = String(stock.mainTheme || stock.themeName || primaryTheme?.name || '')
    const role = String(stock.themeRole || stock.role || primaryTheme?.role || 'unknown')
    const contribution = toNumber(stock.themeContribution ?? primaryTheme?.themeContribution)
    const exposure = toNumber(
      stock.themeExposureWeight ?? stock.exposureWeight ?? primaryTheme?.exposureWeight,
    )
    const mainlineHit = mainline.has(themeName)
    const crowdedHit = crowded.has(themeName)
    const noise = role === 'noise' || exposure < 35 || contribution <= 2 || crowdedHit
    const confluenceScore = Math.round(Math.max(0, Math.min(100, exposure * 0.55 + contribution * 1.8 + (mainlineHit ? 22 : 0) - (crowdedHit ? 20 : 0))))
    const entryReason = mainlineHit && !noise
      ? `主线题材共振：${themeName} · 角色 ${role}`
      : '未满足主线题材共振'
    const filterReason = noise
      ? (crowdedHit ? `拥挤/背离与噪声过滤：${themeName}` : `噪声或低暴露过滤：${themeName || '无题材'}`)
      : ''
    return {
      code: String(stock.code || ''),
      name: String(stock.name || stock.code || ''),
      themeName,
      themeRole: role,
      confluenceScore,
      noise,
      entryReason,
      filterReason,
    }
  })
}

export async function loadThemeResearchExplanation(): Promise<ThemeResearchExplanation> {
  try {
    const summary = await apiService.getThemeResearchSummary({
      datasetId: 'dragonboard_live',
      snapshotType: 'half_hour',
    }) as ThemeResearchSummary
    return buildThemeResearchExplanation(summary)
  } catch (error) {
    return buildThemeResearchExplanation({
      available: false,
      reason: error instanceof Error ? error.message : 'request_failed',
    })
  }
}
