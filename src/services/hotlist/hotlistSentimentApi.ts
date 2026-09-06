// src/services/hotlist/hotlistSentimentApi.ts
// 薄 API client：只做 fetch + 类型化，无兜底计算（口径唯一来源 = QuantBoard 后端）
import type { HotListSentimentDayDoc } from '@/types/hotlistSentiment'

export interface HotlistSentimentSeriesResponse {
  ok: boolean
  degraded?: boolean
  reason?: string
  items: Array<HotListSentimentDayDoc | { tradingDate: string; missing: true; reason: string }>
}

export interface HotlistSentimentSeriesResult {
  items: HotListSentimentDayDoc[]
  degraded: boolean
  reason: string | null
}

export async function fetchHotlistSentimentSeries(
  days = 3,
  datasetId = 'dragonboard_live',
): Promise<HotlistSentimentSeriesResult> {
  const params = new URLSearchParams({ dataset_id: datasetId, days: String(days) })
  const response = await fetch(`/api/hotlist-sentiment/series?${params.toString()}`)
  if (!response.ok) {
    return { items: [], degraded: true, reason: `HTTP ${response.status}` }
  }
  const body = (await response.json()) as HotlistSentimentSeriesResponse
  if (!body.ok || body.degraded) {
    return { items: [], degraded: true, reason: body.reason || 'degraded' }
  }
  const docs = (body.items || []).filter((item): item is HotListSentimentDayDoc => !item.missing)
  return { items: docs, degraded: false, reason: body.reason || null }
}
