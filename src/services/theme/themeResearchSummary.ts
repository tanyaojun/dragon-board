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
  }
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
