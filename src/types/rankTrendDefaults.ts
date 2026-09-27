export interface RankTrendRuntimeDefaults {
  momentumPeriods: number[]
  momentumWeights: number[]
  buyThresholds: number[]
  sellThresholds: number[]
  macdFast: number
  macdSlow: number
  macdSignal: number
  directionWeight: number
  accelerationWeight: number
  crossWeight: number
  macdWeight: number
  maWeight: number
  buyScoreThreshold: number
  sellScoreThreshold: number
}

// five_minutes 为后端采集的研究类型（2026-09-28 入采，题材行只走 half_hour/daily）；
// 浏览器本地临时类型是单数 'five_minute'（见 services/snapshot/types.ts），两者互不冲突
export type RankTrendSnapshotType =
  | 'five_minutes'
  | 'quarter_hour'
  | 'half_hour'
  | 'hourly'
  | 'daily'
export type RankTrendIntradaySnapshotType = Extract<RankTrendSnapshotType, 'quarter_hour' | 'half_hour'>
export type RTConfigPatch = Partial<RankTrendRuntimeDefaults>

export const DEFAULT_RANK_TREND_SNAPSHOT_TYPE: RankTrendSnapshotType = 'half_hour'
export const RANK_TREND_SNAPSHOT_TYPES: RankTrendSnapshotType[] = [
  'five_minutes',
  'quarter_hour',
  'half_hour',
  'hourly',
  'daily',
]
export const RANK_TREND_INTRADAY_SNAPSHOT_TYPES: RankTrendIntradaySnapshotType[] = [
  'quarter_hour',
  'half_hour',
]

// 默认 coverage 门禁口径（无显式类型过滤时）：保持 2026-09-28 前的四类型。
// five_minutes 是后端采集的研究类型（历史日期无该类型帧），若纳入默认门禁会把
// 全部历史日期过滤掉（数据可见性回归）；显式选择 five_minutes 时仍按其自身槽位参与 coverage。
export const RANK_TREND_DEFAULT_COVERAGE_TYPES: RankTrendSnapshotType[] = [
  'quarter_hour',
  'half_hour',
  'hourly',
  'daily',
]
export const RANK_TREND_SNAPSHOT_OPTIONS: Array<{
  type: RankTrendSnapshotType
  label: string
  shortLabel: string
  historyLimit: number
}> = [
  // five_minutes：50 帧 ≈ 1 个交易日，与 quarter_hour 同默认窗口
  { type: 'five_minutes', label: '五分快照', shortLabel: '五分', historyLimit: 50 },
  { type: 'quarter_hour', label: '一刻快照', shortLabel: '一刻', historyLimit: 50 },
  { type: 'half_hour', label: '半小时快照', shortLabel: '半小时', historyLimit: 50 },
  { type: 'hourly', label: '整点快照', shortLabel: '整点', historyLimit: 50 },
  { type: 'daily', label: '日级快照', shortLabel: '日级', historyLimit: 30 },
]

export const DEFAULT_RANK_TREND_RUNTIME_CONFIG: RankTrendRuntimeDefaults = {
  momentumPeriods: [3, 5, 8, 13, 21],
  momentumWeights: [0.15, 0.2, 0.25, 0.25, 0.15],
  buyThresholds: [5, 8, 13, 21, 34],
  sellThresholds: [-5, -8, -13, -21, -34],
  macdFast: 13,
  macdSlow: 21,
  macdSignal: 8,
  // 决策合成五权重（2026-09-13 阶段 21.7 五因子化 → 阶段 22.8 权重重定义落默认）：
  // 当前默认 = 阶段 22 p2_aggressive 实证口径（用户决策），和恒=1；
  // 与 py RankTrendConfig 默认值逐位对齐（依据：evaluate_ts_factor_weights 三窗
  // 两层实证 + Track 2 判定卡 PASS_CANDIDATE，详见长测计划 §22）。
  directionWeight: 0.06,
  accelerationWeight: 0.04,
  crossWeight: 0.24,
  macdWeight: 0.29,
  maWeight: 0.37,
  buyScoreThreshold: 0.12,
  sellScoreThreshold: -0.12,
}

export function cloneDefaultRankTrendRuntimeConfig(): RankTrendRuntimeDefaults {
  return {
    ...DEFAULT_RANK_TREND_RUNTIME_CONFIG,
    momentumPeriods: [...DEFAULT_RANK_TREND_RUNTIME_CONFIG.momentumPeriods],
    momentumWeights: [...DEFAULT_RANK_TREND_RUNTIME_CONFIG.momentumWeights],
    buyThresholds: [...DEFAULT_RANK_TREND_RUNTIME_CONFIG.buyThresholds],
    sellThresholds: [...DEFAULT_RANK_TREND_RUNTIME_CONFIG.sellThresholds],
  }
}

export function buildRankTrendSnapshotPriority(
  preferred: RankTrendSnapshotType = DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
): RankTrendSnapshotType[] {
  return Array.from(new Set<RankTrendSnapshotType>([preferred, ...RANK_TREND_SNAPSHOT_TYPES]))
}

export function isRankTrendSnapshotType(value: unknown): value is RankTrendSnapshotType {
  return RANK_TREND_SNAPSHOT_TYPES.includes(value as RankTrendSnapshotType)
}

export function isRankTrendIntradaySnapshotType(value: unknown): value is RankTrendIntradaySnapshotType {
  return RANK_TREND_INTRADAY_SNAPSHOT_TYPES.includes(value as RankTrendIntradaySnapshotType)
}

export function getRankTrendSnapshotLabel(type: RankTrendSnapshotType): string {
  return RANK_TREND_SNAPSHOT_OPTIONS.find((item) => item.type === type)?.label ?? type
}

export function getRankTrendSnapshotShortLabel(type: RankTrendSnapshotType): string {
  return RANK_TREND_SNAPSHOT_OPTIONS.find((item) => item.type === type)?.shortLabel ?? type
}

export function getRankTrendSnapshotHistoryLimit(type: RankTrendSnapshotType): number {
  return RANK_TREND_SNAPSHOT_OPTIONS.find((item) => item.type === type)?.historyLimit ?? 50
}

function normalizeArray(
  input: unknown,
  fallback: number[],
  min: number,
  max: number,
  round = false,
): number[] {
  if (!Array.isArray(input) || input.length !== fallback.length) return [...fallback]
  return input.map((item, index) => {
    const value = Number(item)
    const next = Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : fallback[index]
    return round ? Math.round(next) : next
  })
}

function normalizeWeights(input: unknown, fallback: number[]): number[] {
  const normalized = normalizeArray(input, fallback, 0.01, 1)
  const sum = normalized.reduce((total, value) => total + value, 0)
  if (!Number.isFinite(sum) || sum <= 0) return [...fallback]
  return normalized.map((value) => Number((value / sum).toFixed(6)))
}

function normalizeNumber(value: unknown, fallback: number, min: number, max: number, round = false): number {
  const numeric = Number(value)
  const next = Number.isFinite(numeric) ? Math.min(max, Math.max(min, numeric)) : fallback
  return round ? Math.round(next) : next
}

export function normalizeRankTrendRuntimeConfig(
  base: RankTrendRuntimeDefaults,
  overrides: RTConfigPatch = {},
): RankTrendRuntimeDefaults {
  const next: RankTrendRuntimeDefaults = {
    ...base,
    ...overrides,
    momentumPeriods: normalizeArray(overrides.momentumPeriods, base.momentumPeriods, 1, 120, true),
    momentumWeights: normalizeWeights(overrides.momentumWeights, base.momentumWeights),
    buyThresholds: normalizeArray(overrides.buyThresholds, base.buyThresholds, 0, 100),
    sellThresholds: normalizeArray(overrides.sellThresholds, base.sellThresholds, -100, 0),
    macdFast: normalizeNumber(overrides.macdFast, base.macdFast, 2, 60, true),
    macdSlow: normalizeNumber(overrides.macdSlow, base.macdSlow, 3, 120, true),
    macdSignal: normalizeNumber(overrides.macdSignal, base.macdSignal, 2, 60, true),
    directionWeight: normalizeNumber(overrides.directionWeight, base.directionWeight, 0.01, 1),
    accelerationWeight: normalizeNumber(overrides.accelerationWeight, base.accelerationWeight, 0.01, 1),
    crossWeight: normalizeNumber(overrides.crossWeight, base.crossWeight, 0.01, 1),
    macdWeight: normalizeNumber(overrides.macdWeight, base.macdWeight, 0.01, 1),
    // maWeight 允许 0：显式关闭 MA 第 5 分量（其余四权重按比例归一化回填）
    maWeight: normalizeNumber(overrides.maWeight, base.maWeight, 0, 1),
    buyScoreThreshold: normalizeNumber(overrides.buyScoreThreshold, base.buyScoreThreshold, 0.01, 1),
    sellScoreThreshold: normalizeNumber(overrides.sellScoreThreshold, base.sellScoreThreshold, -1, -0.01),
  }

  const signalWeightSum =
    next.directionWeight +
    next.accelerationWeight +
    next.crossWeight +
    next.macdWeight +
    next.maWeight
  if (signalWeightSum > 0) {
    next.directionWeight = Number((next.directionWeight / signalWeightSum).toFixed(6))
    next.accelerationWeight = Number((next.accelerationWeight / signalWeightSum).toFixed(6))
    next.crossWeight = Number((next.crossWeight / signalWeightSum).toFixed(6))
    next.macdWeight = Number((next.macdWeight / signalWeightSum).toFixed(6))
    next.maWeight = Number((next.maWeight / signalWeightSum).toFixed(6))
  }

  if (next.macdSlow <= next.macdFast) next.macdSlow = next.macdFast + 1

  return next
}
