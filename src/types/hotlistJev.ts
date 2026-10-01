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
  /** 模型 tokens 用量（input_tokens/output_tokens，snake_case 透传） */
  usage?: Record<string, number> | null
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

// ---------- 多日窗口读口（GET /api/hotlist-jev/range，2026-09-30 jev 图表消费） ----------

/** 窗口内有 jev 文档的交易日（slots 槽位升序；eod 盘后才有，盘中为 null） */
export interface HotlistJevDayEntry {
  tradingDate: string
  slots: HotlistJevDoc[]
  eod: HotlistJevDoc | null
}

/** 窗口内无任何 jev 文档的交易日（结构化缺口，不吞掉不伪造） */
export interface HotlistJevMissingDay {
  tradingDate: string
  reason: string | null
}

export interface HotlistJevRangeResponse {
  ok: boolean
  degraded?: boolean
  reason?: string
  datasetId?: string
  days?: Array<
    | { tradingDate: string; missing: true; reason: string }
    | { tradingDate: string; slots: HotlistJevDoc[]; eod: HotlistJevDoc | null }
  >
  degradedCount?: number
}

export interface HotlistJevRangeResult {
  days: HotlistJevDayEntry[]
  missingDays: HotlistJevMissingDay[]
  degraded: boolean
  reason: string | null
}

// ---------- 复核工作台（W1 辅助线，2026-10-01；GET review-list / POST review-ruling） ----------

export type JevReviewRulingStatus = 'pending' | 'rule_right' | 'jev_right' | 'ambiguous' | 'consistent'

export interface JevReviewRuling {
  status: JevReviewRulingStatus
  note: string
  ruledAt: string | null
}

/** 复核项：A=分歧仲裁（登记全槽分歧日）/ B=退潮段异议 / C=边界日（EOD 贴 40/60 ±3） */
export interface JevReviewItem {
  id: string
  type: 'A' | 'B' | 'C'
  date: string
  slot: string
  rule: {
    stage?: string | null
    stageCn?: string | null
    score?: number | null
    slope?: number | null
    nearEdge?: number | null
  }
  jev: {
    stage?: string | null
    confidence?: number | null
    temperature?: number | null
    dayStage?: string | null
  }
  narrativeHead?: string | null
  dayRet?: number | null
  ruling: JevReviewRuling
}

export interface JevReviewDay {
  date: string
  items: JevReviewItem[]
  pending: number
}

export interface JevReviewListResult {
  days: JevReviewDay[]
  total: number
  ruled: number
  degraded: boolean
  reason: string | null
}
