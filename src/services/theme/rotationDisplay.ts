/**
 * 轮动状态页签展示元数据（纯函数，无 I/O）。
 * 后端 `/api/theme-rotation/summary` 为唯一事实源，此处仅消费侧标签映射与分布计数；
 * 未知枚举值原样透传不崩溃（fail-visible），色板遵循 A 股语义（流入红/流出绿）。
 */

export interface PhaseMeta {
  label: string
  tone: string
}

/** 轮动树形列表固定目录类别（2026-09-27 用户定版：全部/流入/流出/中性） */
export type RotationCategory = 'all' | 'inflow' | 'outflow' | 'neutral'

export const MARKET_PHASE_META: Record<string, PhaseMeta> = {
  rising: { label: '升温', tone: 'phase-rising' },
  climax: { label: '高潮', tone: 'phase-climax' },
  cooling: { label: '退潮', tone: 'phase-cooling' },
  ice: { label: '冰点', tone: 'phase-ice' },
  chaos: { label: '混沌', tone: 'phase-chaos' },
  neutral: { label: '中性', tone: 'phase-neutral' },
}

export const ROTATION_STATE_META: Record<string, PhaseMeta> = {
  mainline: { label: '主线', tone: 'state-mainline' },
  inflow: { label: '流入', tone: 'state-inflow' },
  emerging: { label: '萌发', tone: 'state-emerging' },
  neutral: { label: '中性', tone: 'state-neutral' },
  outflow: { label: '流出', tone: 'state-outflow' },
  cooling: { label: '退潮', tone: 'state-cooling' },
}

export function marketPhaseLabel(phase: string | null | undefined): string {
  if (!phase) return '未知'
  return MARKET_PHASE_META[phase]?.label ?? phase
}

export function rotationStateLabel(state: string | null | undefined): string {
  if (!state) return '—'
  return ROTATION_STATE_META[state]?.label ?? state
}

export function stateTone(state: string | null | undefined): string {
  return (state && ROTATION_STATE_META[state]?.tone) || 'state-unknown'
}

export function countRotationStates(
  statuses: { rotationState: string | null }[],
): { state: string; count: number }[] {
  const counts = new Map<string, number>()
  for (const row of statuses) {
    const key = row.rotationState || 'unknown'
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return [...counts.entries()]
    .map(([state, count]) => ({ state, count }))
    .sort((a, b) => b.count - a.count)
}
