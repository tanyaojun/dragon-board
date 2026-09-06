// src/services/hotlist/hotlistSentimentApi.ts
// 薄 API client：只做 fetch + 类型化，无兜底计算（口径唯一来源 = QuantBoard 后端）
import type { HotListSentimentDayDoc } from '@/types/hotlistSentiment'

export interface HotlistSentimentSeriesResponse {
  ok: boolean
  degraded?: boolean
  reason?: string
  items: Array<HotListSentimentDayDoc | { tradingDate: string; missing: true; reason: string }>
}

export interface HotlistSentimentMissingDay {
  tradingDate: string
  reason: string | null
}

export interface HotlistSentimentSeriesResult {
  items: HotListSentimentDayDoc[]
  degraded: boolean
  reason: string | null
  missingDays: HotlistSentimentMissingDay[]
}

type HotlistSentimentSeriesEntry = HotlistSentimentSeriesResponse['items'][number]

// missing 条目：后端对窗口内无快照的交易日返回 { tradingDate, missing: true, reason }
function isMissingEntry(item: HotlistSentimentSeriesEntry): item is {
  tradingDate: string
  missing: true
  reason: string
} {
  return (item as { missing?: unknown }).missing === true
}

export async function fetchHotlistSentimentSeries(
  days = 3,
  datasetId = 'dragonboard_live',
): Promise<HotlistSentimentSeriesResult> {
  const params = new URLSearchParams({ dataset_id: datasetId, days: String(days) })
  const response = await fetch(`/api/hotlist-sentiment/series?${params.toString()}`)
  if (!response.ok) {
    return { items: [], degraded: true, reason: `HTTP ${response.status}`, missingDays: [] }
  }
  const body = (await response.json()) as HotlistSentimentSeriesResponse
  if (!body.ok || body.degraded) {
    return { items: [], degraded: true, reason: body.reason || 'degraded', missingDays: [] }
  }
  // 缺失日不吞掉：从被过滤条目收集 tradingDate/reason，供面板展示「窗口缺失 N 日」标注
  const docs: HotListSentimentDayDoc[] = []
  const missingDays: HotlistSentimentMissingDay[] = []
  for (const item of body.items || []) {
    if (isMissingEntry(item)) {
      missingDays.push({ tradingDate: item.tradingDate || '', reason: item.reason ?? null })
    } else {
      docs.push(item)
    }
  }
  return { items: docs, degraded: false, reason: body.reason || null, missingDays }
}
