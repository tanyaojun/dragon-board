// src/types/hotlistJev.ts
// jev 热榜情绪观察轨道类型（观察轨道 v3，2026-10-08）。
// 独立观察轨道：jev 从原始市场证据回答「当前帧五档 + 当日序列五档」，只读展示不进信号。
// 全字段可选：旧数据/缺失时正常渲染，不伪造档位。

export type HotlistJevStatus = 'ok' | 'degraded' | 'no_data'

export interface HotlistJevChoiceAnswer {
  type: 'choice'
  choice?: string
  probabilities?: Record<string, number>
  confidence?: number
}

export interface HotlistJevScoreAnswer {
  type: 'score'
  score?: number
  legend?: Record<string, string>
}

export type HotlistJevAnswer = HotlistJevChoiceAnswer | HotlistJevScoreAnswer

export interface HotlistJevDoc {
  _id?: string
  kind?: 'slot' | 'eod'
  origin?: string
  datasetId?: string
  snapshotType?: string
  tradingDate?: string
  slotTime?: string
  anchoredSlotTime?: string | null
  status?: HotlistJevStatus
  errorCode?: string | null
  errorDetail?: string | null
  answers?: Record<string, HotlistJevAnswer> | null
  /** 还原后 0-100 分数（temperature/crowding，eod 为 day_temperature/day_crowding） */
  scores?: Record<string, number> | null
  latencyMs?: number | null
  model?: string | null
  computedAt?: number
  quality?: { degradedSources?: string[] }
  narrativeRaw?: string | null
}

export interface HotlistJevSeriesResponse {
  ok: boolean
  degraded?: boolean
  reason?: string
  date: string | null
  slots: HotlistJevDoc[]
  eod: HotlistJevDoc | null
  degradedCount: number
}

export interface HotlistJevSeriesResult {
  date: string
  slots: HotlistJevDoc[]
  eod: HotlistJevDoc | null
  degraded: boolean
  reason: string | null
}
