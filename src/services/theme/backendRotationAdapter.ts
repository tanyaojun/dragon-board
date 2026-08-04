import type { RotationAnalysis, MarketPhaseType, ThemeRotationStatus } from '@/types/core'

type BackendStatus = {
  themeId?: string
  themeName?: string
  rotationScore?: number | null
  rotationState?: string
  rankChange?: number | null
}

type InflowOutflowItem = string | { themeId?: string; themeName?: string }

function inflowOutflowStatus(item: InflowOutflowItem, state: string, index: number): ThemeRotationStatus {
  if (typeof item === 'string') {
    // 兼容旧帧：inflow/outflow 只有 themeId
    return statusFromBackend({ themeId: item, themeName: item, rotationState: state }, index + 1, false)
  }
  return statusFromBackend({ ...item, rotationState: state }, index + 1, false)
}

function topFlowName(item: InflowOutflowItem | undefined): string {
  if (!item) return ''
  return typeof item === 'string' ? item : item.themeName || item.themeId || ''
}

/** 后端 rotationSummary → 前端 RotationAnalysis 的纯投影（无计算）。 */
export function mapBackendRotationSummary(
  backend: Record<string, any> | null | undefined,
): RotationAnalysis | null {
  // 仅接受引擎产出（H3：按 algorithmVersion 区分迁移期混排）
  if (!backend || typeof backend !== 'object' || !backend.algorithmVersion) return null
  const phase = mapMarketPhase(backend.marketPhase)
  const mainLines: ThemeRotationStatus[] = (backend.mainLines || []).map(
    (item: BackendStatus, i: number) => statusFromBackend(item, i + 1, true),
  )
  return {
    timestamp: backend.computedAt || Date.now(),
    inflowThemes: (backend.inflowThemes || []).map((item: InflowOutflowItem, i: number) =>
      inflowOutflowStatus(item, 'inflow', i),
    ),
    outflowThemes: (backend.outflowThemes || []).map((item: InflowOutflowItem, i: number) =>
      inflowOutflowStatus(item, 'outflow', i),
    ),
    mainLines,
    quickRotation: [],
    rotationSpeed: backend.rotationSpeed ?? undefined,
    marketPhase: phase,
    summary: {
      mainLineCount: mainLines.length,
      inflowCount: (backend.inflowThemes || []).length,
      outflowCount: (backend.outflowThemes || []).length,
      topInflow: topFlowName((backend.inflowThemes || [])[0]),
      topOutflow: topFlowName((backend.outflowThemes || [])[0]),
      suggestion: backend.suggestion || '',
      strongCount: mainLines.filter((m) => m.strength === 'strong').length,
      topStrength: mainLines[0]?.themeName || '',
    },
    mainlineConcentration: backend.mainlineConcentration ?? undefined,
    maxBoardHeight: backend.maxBoardHeight ?? undefined,
    algorithmVersion: backend.algorithmVersion,
    evidence: backend.evidence,
  }
}

function statusFromBackend(item: BackendStatus, rank: number, isMainLine: boolean): ThemeRotationStatus {
  const state = item.rotationState || (isMainLine ? 'mainline' : 'neutral')
  const direction =
    state === 'mainline' || state === 'inflow' || state === 'emerging'
      ? 'inflow'
      : state === 'outflow' || state === 'cooling'
        ? 'outflow'
        : 'neutral'
  const score = item.rotationScore ?? undefined
  return {
    themeId: item.themeId || '',
    themeName: item.themeName || item.themeId || '',
    rank,
    rankChange: item.rankChange ?? undefined,
    rotationScore: score,
    isMainLine,
    direction,
    persistentDays: undefined,
    strength: score != null && score >= 70 ? 'strong' : score != null && score >= 45 ? 'medium' : 'weak',
    relatedThemes: undefined,
    topReasons: [],
    // 后端 v1 不提供资金/宽度明细：保持 undefined，缺失不伪造（M10）
    inflow: undefined,
    outflow: undefined,
    netInflow: undefined,
    avgChange: undefined,
    totalTurnover: undefined,
    ztCount: undefined,
    stockCount: undefined,
    strengthScore: undefined,
  }
}

function mapMarketPhase(phase: string | undefined): MarketPhaseType {
  switch (phase) {
    case 'ice':
      return 'ice'
    case 'rising':
      return 'rising'
    case 'climax':
      return 'climax'
    case 'cooling':
      return 'falling'
    case 'chaos':
      return 'accumulation'
    case 'neutral':
      return 'accumulation'
    default:
      return 'accumulation'
  }
}
