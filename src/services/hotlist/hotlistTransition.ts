// src/services/hotlist/hotlistTransition.ts
// 阶段迁移计数格式化（2026-09-16）：后端 sentiment 文档 metrics.transitionCounts
// （键为 cycle.transition 原始串："a->b" 迁移 / 单段 "a" 延续）→ 展示条目。
// 阶段词表唯一来源 = HOT_LIST_STAGE_LABELS（与后端 STAGE_LABELS 逐字一致）；未知键原样保留。
import { HOT_LIST_STAGE_LABELS, type HotListStageKey } from '@/types/hotlistSentiment'

export interface HotlistTransitionItem {
  /** 原始迁移串（后端键原样，供 key/调试） */
  key: string
  /** 展示文本：「点火→冷却」/「冷却延续」 */
  text: string
  count: number
}

function formatTransitionText(raw: string): string {
  const parts = raw.split('->').map((part) => part.trim())
  const labels = parts.map((part) => HOT_LIST_STAGE_LABELS[part as HotListStageKey] ?? part)
  if (labels.length === 1) return `${labels[0]}延续`
  return labels.join('→')
}

export function formatTransitionCounts(
  counts: Record<string, number> | null | undefined,
  topN = 4,
): HotlistTransitionItem[] {
  if (!counts || typeof counts !== 'object') return []
  return Object.entries(counts)
    .filter(([, count]) => Number(count) > 0)
    .sort(([, a], [, b]) => Number(b) - Number(a))
    .slice(0, Math.max(1, topN))
    .map(([key, count]) => ({ key, text: formatTransitionText(key), count: Number(count) }))
}
