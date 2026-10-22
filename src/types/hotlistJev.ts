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

/** 涨停打标轨道（hotlist_jev_driver_labels）：个股四题标签（研究↔展示同步 2026-10-03） */
export interface HotlistJevLimitUpStock {
  code: string
  name: string | null
  label: string | null
  labelProbabilities: Record<string, number> | null
  catalystDepth: string | null
  catalystDepthProbabilities: Record<string, number> | null
  freshness: string | null
  buySideLogic: string | null
  buySideProbabilities: Record<string, number> | null
  board: string | null
  inHotlist: boolean
  rank: number | null
  /** 个股相位分线（2026-10-04 试点字段：该股自身本轮行情位置；未跑日为 null） */
  stockPhasePosition: string | null
  stockPhaseProbabilities: Record<string, number> | null
  computedAt: string | null
  /** 涨停原因=韭研异动解析首行（2026-10-20 读口 join；缺失时字段不出现，展示 '-'） */
  reason?: string | null
  /** 投喂槽位：midday=12:30 午盘投喂（收盘幂等不重复投喂）/final=收盘投喂；旧档为 null */
  labelSlot?: string | null
  /** 打标所用韭研名单的抓取时点（原料时点可追溯，如 2026-10-20T12:06:00） */
  jiuyanFetchedAt?: string | null
}

/** 日级相位哨兵（_id={date}:PHASE） */
export interface HotlistJevLimitUpPhase {
  band: string | null
  probabilities: Record<string, number> | null
  computedAt: string | null
}

export interface HotlistJevLimitUpDay {
  ok: boolean
  date: string
  phase: HotlistJevLimitUpPhase | null
  stocks: HotlistJevLimitUpStock[]
  summary: {
    total: number
    label: Record<string, number>
    catalystDepth: Record<string, number>
    buySideLogic: Record<string, number>
  }
  noData: boolean
  reason: string | null
}

/** 题材层「板块龙头隔日连板」单只投喂记录（GET /api/hotlist-jev/theme-leaders）。 */
export interface HotlistJevThemeLeaderRow {
  /** 存档 _id（{date}:{code}） */
  docId?: string | null
  code: string
  name: string | null
  board: string | null
  streak: number | null
  time: string | null
  boardN: number | null
  ladderFollowers: number | null
  prevBoardN: number | null
  /** 落库口径（过证据门后）= 消费端单一事实源 */
  choice: string | null
  probabilities: Record<string, number> | null
  /** 模型原答（审计用）：与 choice 不同时说明被证据门覆盖过，必须双显 */
  modelChoice: string | null
  modelProbabilities: Record<string, number> | null
  catalystStage: string | null
  gate: { applied?: boolean; reason?: string | null; label?: string | null } | null
  evidenceMissing: boolean
  evidenceMissingReason: string | null
  evidenceIndustry: string | null
  evidenceEventTitles: string[]
  baselineKey: string | null
  baselineMeta: { start?: string | null; end?: string | null; rows?: number } | null
  /** 次一交易日是否仍封板；null = 结局未封（不得展示为「未续」） */
  outcomeSealedNextDay: boolean | null
  status: string | null
  /** live = 当日 16:20 前瞻挂链；backfill = 事后回填（含语料未来信息，不得当结论） */
  sampleOrigin: string
  questionSetVersion: string | null
  questionSetHash: string | null
  ammoVersion: string | null
  usage: { input_tokens?: number; output_tokens?: number } | null
  latencyMs: number | null
  computedAt: string | null
  errorCode: string | null
  errorDetail: string | null
  /** 后端透出（2026-10-20 review P2-3 补齐）：档案 _id 中的日期部分（=读口径 date） */
  tradingDate?: string | null
  /** 结局回填元数据（schedule 自愈写入） */
  outcomeMeta?: Record<string, unknown> | null
  /** jev 模型标识（审计） */
  model?: string | null
  /** with_narrative=1 才返回：jev 响应原文（成功路径存解析结果的 envelope） */
  responseRaw?: Record<string, unknown> | null
  /** with_narrative=1 才返回：实际投喂给 jev 的语料全文 */
  narrative?: string | null
  /** with_narrative=1 才返回：v2 题目集原文 */
  questionsRaw?: Record<string, unknown> | null
}

export interface HotlistJevThemeLeaderDay {
  ok: boolean
  date: string
  no_data?: boolean
  count: number
  versions: Record<string, number>
  mixedVersions: boolean
  origins: Record<string, number>
  questionSetHash: string | null
  ammoVersion: string | null
  statusCounts: Record<string, number>
  gatedCount: number
  sealedCount: number
  leaders: HotlistJevThemeLeaderRow[]
}
