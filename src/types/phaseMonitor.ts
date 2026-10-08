/**
 * 分相位验收体系前端类型（设计 ranktrend-phase-frontend-design.md；2026-09-30）。
 * 口径锚：sentiment_2b（offense ≥60 / defense <60，2026-10-01 章程 Q1 边界 50→60），唯一口径源 =
 * quant-board backend/operations/phase_label_run.py CANDIDATES['sentiment_2b']。
 */

export type PhaseKind = 'offense' | 'defense' | 'unknown'

/** GET /api/hotlist-sentiment/phase-history 的单日条目 */
export interface PhaseHistoryDay {
  tradingDate: string
  eodScore: number | null
  phase: PhaseKind
}

export interface PhaseHistoryResponse {
  datasetId: string
  snapshotType: string
  threshold: number
  count: number
  days: PhaseHistoryDay[]
}

export type PhaseHistoryResult =
  | { degraded: false; days: PhaseHistoryDay[]; threshold: number | null }
  | { degraded: true; days: []; threshold: null; reason: string }

/** GET /api/phase-monitor/board 的 northstar 基线文档（report 为 phase_northstar 产物） */
export interface PhaseNorthstarDoc {
  _id: string
  kind: 'northstar'
  key: string
  report: {
    meta?: { candidate?: string; thresholds?: Record<string, number>; tradeCount?: number; equityPoints?: number }
    fullWindow?: { maxDD: number | null; segReturn: number | null }
    byPhase?: Record<string, PhaseTradeStats>
    equitySlices?: Record<string, { equityPoints: number; segReturn: number | null; maxDD: number | null }>
    northstar?: Record<string, PhaseNorthstarEntry>
  }
  updatedAt: string
}

export interface PhaseTradeStats {
  trades: number
  missingNetReturn: number
  winRate: number | null
  profitFactor: number | null
  wrxpf: number | null
  sumNetReturn: number | null
  maxSingleLoss: number | null
}

export interface PhaseNorthstarEntry {
  trades?: number
  wrxpf?: number | null
  sumNetReturn?: number | null
  maxDD?: number | null
  segReturn?: number | null
  equityPoints?: number | null
  line?: { wrxpf: boolean; trades: boolean; maxDD: boolean }
  defenseLine?: { ddBetter: boolean; lossBetter: boolean }
  pass?: boolean
}

/** GET /api/phase-monitor/board 的月度监督文档（report 为 phase_monitor_monthly 产物） */
export interface PhaseMonthlyDoc {
  _id: string
  kind: 'monthly'
  month: string
  report: {
    meta?: { month?: string; generatedAt?: string; gitCommit?: string }
    coverage?: { sentimentDocs?: number; tradingDays?: number; labelsFresh?: boolean; labelsNote?: string | null }
    supervision?: {
      saTriggerRate?: { value: number | null; alert: boolean | null }
      insufficientShare?: { value: number | null; alert: boolean | null }
      northstar?: { pass: { offense: boolean | null; defense: boolean | null } }
    }
  }
  updatedAt: string
}

export interface PhasePulseDoc {
  _id: string
  kind: 'pulse'
  month: string
  report: {
    month?: string
    tradeCount?: number
    sampleNote?: string
    eodDays?: number
    /** 当月入场却进不了任何分档的笔数（缺前一日分/缺平仓价；fail-visible，>0 时前端提示） */
    unbandedTrades?: number
    byPhase?: Record<string, PhaseTradeStats>
    fullWindow?: { maxDD: number | null; segReturn: number | null }
    northstar?: Record<string, PhaseNorthstarEntry>
    meta?: { gate?: string; generatedAt?: string }
    /** 分档战绩（键=引擎 BAND_TAGS 四带；label/rangeText=后端携带的用户展示语义，前端纯渲染） */
    bands?: Record<string, {
      label?: string
      rangeText?: string
      trades: number
      sumNetReturn: number
      avgPerTrade: number | null
    }>
    ab?: {
      baseline?: { tradeCount: number; sumNetReturn: number }
      bandAvoided?: { tradeCount: number; sumNetReturn: number }
      delta?: { tradesRemoved: number; netReturnSaved: number }
      /** 规则描述（后端携带的用户语言，如「按情绪分档出手（低温满仓、弱势期不开新仓、高温三成）」） */
      arm?: string
      degraded?: boolean
      reason?: string
    }
    challengers?: Array<{
      name: string
      /** 试验打法用户名与一句解释（臂数注册表登记，后端透传；null 回退显示 name） */
      label?: string | null
      description?: string | null
      degraded?: boolean
      reason?: string
      stats?: { tradeCount: number; sumNetReturn: number }
      attribution?: {
        availableTrades?: number
        missingEntryPhase?: number
        rebalanceCount?: number
        byPhase?: Record<string, number>
        byBand?: Record<string, unknown>
      }
    }>
    armSkipped?: string[]
  }
  updatedAt: string
}

/** GET /api/phase-monitor/board 的深谷节点账本文档（盘后链 deepValley 步 / deep_valley_revalidate 产物，池等权代理口径） */
export interface C9DeepValleyDoc {
  _id: string
  kind?: 'c9'
  ok?: boolean
  month: string
  summary: {
    month: string
    deepSamples: number
    reboundHit: string
    poolMean: number | null
    baselineMean: number | null
    edge: number | null
  }
  samples: Array<{
    date: string
    eodScore: number
    rebound3d: number
    rebound3dHit: boolean
    poolRetPct: number | null
    poolN: number
  }>
  noData?: boolean
  reason?: string | null
  updatedAt: string
}

/** GET /api/phase-monitor/board 的高峰兑现账本文档（peak_revalidate 产物，缺口三分组口径，方案 §4） */
export interface C10PeakDoc {
  _id: string
  kind?: 'c10'
  ok?: boolean
  month: string
  summary: {
    month: string
    peakDays: number
    samples: number
    gapLt1: { n: number; mean: number | null; win: number }
    gap1to3: { n: number; mean: number | null; win: number }
    gapGe3: { n: number; mean: number | null; win: number }
    baselineMean: number | null
    edgeGe3VsBaseline: number | null
    /** 月末跨月高峰日（T+3 出窗，不进样本；fail-visible 留痕） */
    truncatedPeakDays?: string[]
    /** jiuyan final 缺失的高峰日（人口缺失，与真涨停池空可区分） */
    populationMissing?: string[]
    noData?: boolean
    reason?: string | null
  }
  samples: Array<{
    date: string
    eodScore: number
    n: number
    gapLt1: number[]
    gap1to3: number[]
    gapGe3: number[]
  }>
  noData?: boolean
  reason?: string | null
  updatedAt: string
}

/** 哨兵分歧单日（融合总纲合流点一：规则分主定义 × jev 日级哨兵，只告警不改判） */
export interface SentinelDivergenceDay {
  date: string
  ruleScore: number
  ruleBand: string
  sentinelBand: string
  sentinelRaw: string
  relation: 'agree' | 'lower' | 'higher'
  /** 档位差（负=哨兵更冷，可 ±2；前端按差值表述） */
  notches: number
}

export interface SentinelDivergence {
  summary: { comparable: number; agree: number; lower: number; higher: number; skipped: number }
  days: SentinelDivergenceDay[]
}

/** GET /api/phase-monitor/board 的日度情绪一句话文档（jev-daily-line-design.md，kind=daily_line） */
export interface PhaseDailyLineDoc {
  _id: string
  kind: 'daily_line'
  date: string
  report: {
    date: string
    sentence: string
    parts: {
      calendarFlag: string | null
      shape: string
      bandTag: string
      bandLabel: string
      bandWord: string
      action: string
    }
    /** 形态来源：jev=jev 归层；rule_fallback=jev 失败规则兑底；rule=未调用（dry/原料不足） */
    shapeSource: 'jev' | 'rule_fallback' | 'rule'
    ruleShape: string | null
    jev?: { latencyMs?: number; model?: string } | null
    skippedJev?: boolean
    degraded?: Array<{ source: string; reason: string; action?: string }>
    meta?: { templateVersion?: number; generatedAt?: string }
  }
  updatedAt: string
}

export interface PhaseBoard {
  northstar: PhaseNorthstarDoc | null
  pulse?: PhasePulseDoc | null
  pulses?: PhasePulseDoc[]
  northstarMissingReason?: string
  months: PhaseMonthlyDoc[]
  count: number
  /** 深谷节点账本（C9 事件轴，按月升序；可能为空=尚无深谷状态日） */
  c9?: C9DeepValleyDoc[]
  /** 高峰兑现账本（C10 逃顶侧事件轴，按月升序；可能为空=尚无高峰状态日） */
  c10?: C10PeakDoc[]
  /** 哨兵分歧（合流点一：逐日三档带比较 + 汇总计数） */
  sentinelDivergence?: SentinelDivergence
  /** 日度情绪一句话（最新一天；null=尚未产出，另见 dailyLineMissingReason） */
  dailyLine?: PhaseDailyLineDoc | null
  dailyLineMissingReason?: string
  /** 四带刻度（边界+用户展示名，后端单一事实源携带；前端按分数落区间，禁止手抄阈值） */
  bandScale?: Array<{ tag: string; label: string; rangeText: string; lower: number; upper: number | null }>
}
