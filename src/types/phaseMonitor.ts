/**
 * 分相位验收体系前端类型（设计 ranktrend-phase-frontend-design.md；2026-09-30）。
 * 口径锚：sentiment_2b（offense ≥50 / defense <50），唯一口径源 =
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
  | { degraded: false; days: PhaseHistoryDay[]; threshold: number }
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

export interface PhaseBoard {
  northstar: PhaseNorthstarDoc | null
  northstarMissingReason?: string
  months: PhaseMonthlyDoc[]
  count: number
}
