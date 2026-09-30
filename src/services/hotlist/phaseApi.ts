/**
 * 分相位验收体系读口封装（前端可见化，设计 ranktrend-phase-frontend-design.md §3）。
 * 失败降级 degraded + reason（fail-visible 不伪造），循 hotlistJevApi 模式。
 */
import type { PhaseBoard, PhaseHistoryResult } from '@/types/phaseMonitor'

/**
 * 相位历史（GET /api/hotlist-sentiment/phase-history）：EOD 序列按 sentiment_2b 映射的日级相位。
 */
export async function fetchPhaseHistory(datasetId = 'dragonboard_live'): Promise<PhaseHistoryResult> {
  const params = new URLSearchParams({ dataset_id: datasetId })
  try {
    const response = await fetch(`/api/hotlist-sentiment/phase-history?${params.toString()}`)
    if (!response.ok) {
      return { degraded: true, days: [], threshold: null, reason: `HTTP ${response.status}` }
    }
    const body = (await response.json()) as {
      days?: PhaseHistoryResult extends { degraded: false; days: infer D } ? D : never
      threshold?: number
    }
    return { degraded: false, days: body.days ?? [], threshold: body.threshold ?? null }
  } catch (err) {
    return { degraded: true, days: [], threshold: null, reason: err instanceof Error ? err.message : 'fetch failed' }
  }
}

/**
 * 相位验收看板（GET /api/phase-monitor/board）：northstar 基线 + 逐月监督文档。
 */
export async function fetchPhaseMonitorBoard(): Promise<PhaseBoard | { degraded: true; reason: string }> {
  try {
    const response = await fetch('/api/phase-monitor/board')
    if (!response.ok) {
      return { degraded: true, reason: `HTTP ${response.status}` }
    }
    return (await response.json()) as PhaseBoard
  } catch (err) {
    return { degraded: true, reason: err instanceof Error ? err.message : 'fetch failed' }
  }
}
