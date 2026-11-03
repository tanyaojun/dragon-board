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
  /** 10 档锚点概率分布（键 "0"-"9"；2026-10-02 实测生产 100% 携带，锚期望/9×100=还原分；旧文档/降级可能缺失） */
  probabilities?: Record<string, number>
  /** 模型置信 0-1（与 choice 同字段名，实测同携带） */
  confidence?: number
}

export type HotlistJevAnswer = HotlistJevChoiceAnswer | HotlistJevScoreAnswer

/** 日级 EOD 帧覆盖（2026-10-22 日级语料修复；旧文档缺失） */
export interface HotlistJevFrameCoverage {
  expectedSlots?: string[]
  presentSlots?: string[]
  evidenceSlots?: string[]
  missingSlots?: string[]
  emptyEvidenceSlots?: Array<{ slot: string; reason: string }>
  lastSlot?: string | null
  hasCloseFrame?: boolean
  frameCount?: number
  evidenceCount?: number
  expectedCount?: number
}

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
  /** as-of 时间戳（如 "2026-10-08 14:30+08:00"；旧文档缺失） */
  asOf?: string | null
  /** 【近20日参照】首行区间（extract_history_anchor_range 产出；旧文档缺失） */
  historyAnchorRange?: string | null
  /** 涨停生态标注（§十三 detect_ecosystem_break 产出）：ecosystemBreak=断层日才有；ecoBreadth=宽度参照每日落盘（U 形三段分区展示消费，2026-10-04 裁决 10） */
  diagnostics?: {
    ecosystemBreak?: { isBreak: boolean; ztCount: number; p20: number; advDecRatio: number; amountYi: number; prevAmountYi: number; detectedAt: string; source: string } | null
    ecoBreadth?: { ztCount: number; p20: number; advDecRatio: number | null; isBreak: boolean; detectedAt: string; source: string } | null
  } | null
  /** 当前帧结构化证据（slot/EOD 新代文档；旧文档为 null） */
  evidenceRaw?: Record<string, unknown> | null
  /** 日级 EOD 帧覆盖（2026-10-22 起；旧文档缺失） */
  frameCoverage?: HotlistJevFrameCoverage | null
  /** 语料口径代际戳（legacy_unversioned / v2.5_pre_eod_fix / eod-2026-10-22） */
  corpusCaliberVersion?: string | null
  /** 存量文档未落 evidenceRaw 的显式标记（不伪造证据） */
  evidenceRawUnavailable?: boolean
  /** 模型原始返回 envelope（jev_client 原样透传；旧文档缺失） */
  responseRaw?: Record<string, unknown> | null
  /** 实际下发题集（slot=四问 / eod=日四问；旧文档可能缺失） */
  questionsRaw?: Record<string, unknown> | null
  /** 题目判据演进号（如 "v2.4"；compute 落库写入，2026-10-02 起生效）。
   *  缺失=旧代产物（口径未知）：判据随版本漂移（实测拥挤读数月均差 5 倍），跨版本不可对比 */
  questionSetVersion?: string | null
  /** 拥挤三层概率合计（后端读口派生字段，2026-10-24 A2 单一事实源提后端；缺答案 null） */
  crowdingProbability?: number | null
  /** 叙事超限截断标记（2026-10-24 A3 fail-visible；旧文档缺失） */
  narrativeTruncated?: boolean
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
  /** 窗口内 status 为 degraded/no_data 的文档数（后端 degradedCount，缺失 0） */
  degradedCount: number
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
    /** A 类日级：全天槽位对照（2026-10-01 用户反馈，仲裁单位=天） */
    stageSummary?: string | null
    slots?: Array<{ slot: string; stageCn?: string | null; score?: number | null; slope?: number | null }>
  }
  jev: {
    stage?: string | null
    confidence?: number | null
    temperature?: number | null
    dayStage?: string | null
    stageSummary?: string | null
    slots?: Array<{ slot: string; stage?: string | null; confidence?: number | null; temperature?: number | null }>
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

// ---------- 韭研公社异动（W-jiuyan，2026-10-02；GET /api/hotlist-jev/jiuyan-action） ----------

export interface JiuyanStock {
  code: string | null
  name: string | null
  price: number | null
  time: string | null
  num: string | null
  day: number | null
  reason: string | null
  expound: string | null
  articleId: string | null
  likeCount: number | null
}

export interface JiuyanField {
  name: string
  count: number
  stocks: JiuyanStock[]
}

export interface JiuyanActionDoc {
  tradingDate: string
  updateKind: 'midday' | 'final'
  counts: { all?: number; recommend?: number }
  fields: JiuyanField[]
  totalStocks: number
  quality: { degradedSources: string[]; tokenSource: string }
  fetchedAt: string
}

export interface JiuyanDateEntry {
  date: string
  kinds: string[]
}

export interface JiuyanActionResult {
  dates: JiuyanDateEntry[]
  doc: JiuyanActionDoc | null
  degraded: boolean
  reason: string | null
}

/** 情绪 概览 EOD（市场热度计，2026-10-02 双表立项）：锚定近 20 交易日分位的第二支表 */
export interface HotlistSentimentOverviewEod {
  status: string | null
  dayTemperature: number | null
  dayStage: string | null
  dayStageProbability: number | null
  dayCrowding: string | null
  dayCrowdingProbabilities: Record<string, number> | null
  historyAnchorRange: string | null
  computedAt: number | null
  /** 2026-10-22 日级语料修复：覆盖度/代际戳（旧文档缺失） */
  anchoredSlotTime?: string | null
  frameCoverage?: HotlistJevFrameCoverage | null
  corpusCaliberVersion?: string | null
  evidenceRawUnavailable?: boolean
  /** 2026-10-24 A1/A2（题材龙头方法论回灌）：路径形态 + 逐题置信 + 拥挤合计提后端（旧文档缺失 null） */
  dayPattern?: string | null
  dayPatternProbability?: number | null
  dayStageConfidence?: number | null
  dayPatternConfidence?: number | null
  dayTemperatureConfidence?: number | null
  dayCrowdingProbability?: number | null
  dayCrowdingConfidence?: number | null
}

/** 规则 EOD（池内质量计）：hotlist_sentiment emotionScore 摘要 */
export interface HotlistSentimentRuleEod {
  score: number | null
  stageCandidate: string | null
  slope: number | null
  version: string | null
}

export interface HotlistSentimentOverviewResult {
  ok: boolean
  date: string | null
  jev: HotlistSentimentOverviewEod | null
  rule: HotlistSentimentRuleEod | null
  degraded: boolean
  reason: string | null
}
