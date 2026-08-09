/**
 * 量价验证（展示层纯函数 + 后续信号层内核）。
 * 口径（2026-08-09 定稿）：
 * - 放量/缩量：绝对阈值（量比 ≥ 1.05 放量；≤ 0.95 缩量，classifyVolumeRatio）
 * - 资金：zlje > 0 且（zljzb 缺失时仅看 zlje）> 0 → 资金配合；zlje <= 0 → 资金背离；zlje 缺失 → noData
 * - 四象限：change 方向 × 放缩量
 * - 涨停按板块（主板 10% / 创业板·科创板 20% / 北交所 30%，resolveLiveLimitState）
 * 约束：fail-visible——量价字段缺失 → score=null + 结构化原因，不伪造、不阻断。
 */
import { classifyVolumeRatio, toFiniteNumber } from '@/utils/volumeRatio'
import { resolveLiveLimitState } from './liveLimitState'

/** 量价配合四象限（normal = 有量比但非放非缩） */
export type VolumePriceQuadrant = 'rise_volume' | 'rise_shrink' | 'fall_volume' | 'fall_shrink' | 'normal'

export function getVolumePriceQuadrantLabel(quadrant: VolumePriceQuadrant | null): string {
  switch (quadrant) {
    case 'rise_volume':
      return '放量上涨'
    case 'rise_shrink':
      return '缩量上涨'
    case 'fall_volume':
      return '放量下跌'
    case 'fall_shrink':
      return '缩量下跌'
    case 'normal':
      return '量能常态'
    default:
      return '--'
  }
}

/**
 * 资金子信号：zlje > 0 且（zljzb 缺失时仅用 zlje）> 0 → support；
 * zlje <= 0 → divergent；zlje 缺失 → noData。
 */
export function classifyFundSignal(zlje: unknown, zljzb: unknown): 'support' | 'divergent' | 'noData' {
  const inflow = toFiniteNumber(zlje)
  if (inflow === null) return 'noData'
  if (inflow > 0) {
    const ratio = toFiniteNumber(zljzb)
    if (ratio === null || ratio > 0) return 'support'
    return 'divergent' // zlje>0 但 zljzb<=0：数据不一致，按背离保守处理
  }
  return 'divergent'
}

/**
 * 四象限：change 方向 × 放缩量。change 缺失或量比无有效值/无基准 → null。
 */
export function classifyVolumePriceQuadrant(
  change: unknown,
  volumeRatio: unknown,
  median?: unknown,
): VolumePriceQuadrant | null {
  const changeNum = toFiniteNumber(change)
  const volume = classifyVolumeRatio(volumeRatio, median)
  if (changeNum === null || volume === 'unknown') return null
  if (volume === 'normal') return 'normal'
  const rising = changeNum > 0
  const falling = changeNum < 0
  if (volume === 'up') return rising ? 'rise_volume' : falling ? 'fall_volume' : 'normal'
  // volume === 'down'
  return rising ? 'rise_shrink' : falling ? 'fall_shrink' : 'normal'
}

export const volumeStateLabel = (volume: 'up' | 'down' | 'normal' | 'noData'): string =>
  volume === 'up' ? '放量' : volume === 'down' ? '缩量' : volume === 'normal' ? '常态' : '无量比基准'

// ========== 量价综合评估值（0-100） ==========

export interface VolumePriceScoreResult {
  /** 0-100 综合评估值；量价数据不足时为 null（不伪造） */
  score: number | null
  /** 涨跌方向（由 change 决定） */
  direction: 'up' | 'down' | 'neutral' | null
  /** 分项贡献：方向 / 量价交叉 / 资金 */
  breakdown: { direction: number; volume: number; fund: number }
  quadrant: VolumePriceQuadrant | null
  reasons: string[]
}

/**
 * 量价综合评估值（0-100，连续化权重）：
 * score = clamp(round(50 + 方向 + 量价 + 资金), 0, 100)
 *   方向（change 连续）：涨 +min(15, change×1.5)；跌 -min(15, |change|×1.5)
 *   量价（量比幅度 + 涨停语境，涨停阈值按板块：主板 10% / 创业板·科创板 20% / 北交所 30%，复用 resolveLiveLimitState）：
 *     缩量涨停（vr<0.95 且达到板块涨停）→ +25（封板惜售，好票）
 *     缩量上涨（非涨停）→ +10~15（惜售/无量涨）
 *     温和放量上涨（1.05≤vr≤2）→ +10~15（量价配合正常）
 *     放量过大（2<vr≤2.5）→ 渐扣；过度放量（vr>2.5）→ -15~-20（出货风险）
 *     缩量下跌 -10；放量下跌 -20；量能常态 ±5
 *   资金（主力净占比）：
 *     0<zljzb≤20 → +min(15, zljzb×3)（真流入）
 *     zljzb>20 → -min(15, 10+(zljzb-20)×0.5)（净占比异常高，疑似对倒出货，不奖反罚）
 *     zljzb<0 → -min(15, |zljzb|×3)；缺失按 zlje 符号 ±5
 * 量价数据不足（涨跌/量比缺失）返回 score=null，不评估、不伪造。
 */
const OVER_VOLUME_RATIO = 2.5 // 过度放量阈值（出货风险）
const ABNORMAL_FUND_RATIO = 20 // 异常主力净占比阈值（对倒出货）

export function computeVolumePriceScore(args: {
  code?: unknown
  change?: unknown
  volumeRatio?: unknown
  median?: unknown
  zlje?: unknown
  zljzb?: unknown
}): VolumePriceScoreResult {
  const change = toFiniteNumber(args.change)
  const vr = toFiniteNumber(args.volumeRatio)
  const volume = classifyVolumeRatio(args.volumeRatio, args.median)
  const quadrant = classifyVolumePriceQuadrant(args.change, args.volumeRatio, args.median)
  const reasons: string[] = []

  if (change === null || volume === 'unknown') {
    return {
      score: null,
      direction: null,
      breakdown: { direction: 0, volume: 0, fund: 0 },
      quadrant,
      reasons: ['量价数据不足（涨跌/量比缺失），不评估'],
    }
  }

  // 涨停判断：按板块（主板 10% / 创业板·科创板 20% / 北交所 30%），复用 liveLimitState
  const isLimitUp = resolveLiveLimitState({ code: args.code, change }).atLimitUp

  // 方向分（连续）
  let directionScore = 0
  let direction: 'up' | 'down' | 'neutral'
  if (change > 0) {
    directionScore = Math.min(15, change * 1.5)
    direction = 'up'
  } else if (change < 0) {
    directionScore = -Math.min(15, Math.abs(change) * 1.5)
    direction = 'down'
  } else {
    direction = 'neutral'
  }

  // 量价分（缩量涨停最好，过度放量为出货风险；isLimitUp 已在函数开头按板块计算）
  let volumeScore = 0
  if (vr !== null) {
    if (change > 0) {
      if (vr <= 0.95) {
        volumeScore = isLimitUp ? 25 : Math.min(15, 10 + (0.95 - vr) * 15) // 缩量：涨停 +25 / 非涨停温和
      } else if (vr <= 1.05) {
        volumeScore = isLimitUp ? 20 : 5 // 量能常态
      } else if (vr <= 2) {
        volumeScore = Math.min(15, 10 + (vr - 1) * 5) // 温和放量上涨
      } else if (vr <= OVER_VOLUME_RATIO) {
        volumeScore = Math.max(5, 15 - (vr - 2) * 10) // 放量过大渐扣
      } else {
        volumeScore = -Math.min(20, 15 + (vr - OVER_VOLUME_RATIO) * 10) // 过度放量：出货风险
      }
    } else if (change < 0) {
      if (vr > 1.05) volumeScore = -20 // 放量下跌
      else if (vr >= 0.95) volumeScore = -5 // 量能常态下跌
      else volumeScore = -10 // 缩量下跌
    }
  }

  // 资金分（净占比：正常流入加分，异常高净占比判对倒出货）
  const zljzb = toFiniteNumber(args.zljzb)
  const zlje = toFiniteNumber(args.zlje)
  let fundScore = 0
  if (zljzb !== null && zljzb > ABNORMAL_FUND_RATIO) {
    fundScore = -Math.min(15, 10 + (zljzb - ABNORMAL_FUND_RATIO) * 0.5) // 疑似对倒出货，不奖反罚
  } else if (zljzb !== null && zljzb > 0) {
    fundScore = Math.min(15, zljzb * 3)
  } else if (zljzb !== null && zljzb < 0) {
    fundScore = -Math.min(15, Math.abs(zljzb) * 3)
  } else if (zljzb === null && zlje !== null) {
    fundScore = zlje > 0 ? 5 : zlje < 0 ? -5 : 0
  }

  const score = Math.max(0, Math.min(100, Math.round(50 + directionScore + volumeScore + fundScore)))

  if (isLimitUp && vr !== null && vr <= 0.95) {
    reasons.push('缩量涨停（封板惜售，好票）')
  } else if (vr !== null && vr <= 0.95 && change > 0) {
    reasons.push('缩量上涨（惜售/无量涨）')
  } else if (vr !== null && vr > OVER_VOLUME_RATIO && change > 0) {
    reasons.push('过度放量上涨（疑似出货）')
  } else if (vr !== null && vr > 1.05 && change > 0) {
    reasons.push('放量上涨（量价配合）')
  } else if (vr !== null && vr > 1.05 && change < 0) {
    reasons.push('放量下跌（风险）')
  } else if (vr !== null && vr < 0.95 && change < 0) {
    reasons.push('缩量下跌（无量阴跌）')
  }
  if (zljzb !== null && zljzb > ABNORMAL_FUND_RATIO) reasons.push('主力净占比异常高（疑似对倒出货）')
  else if (zljzb !== null && zljzb > 0) reasons.push('主力净流入')
  else if (zljzb !== null && zljzb < 0) reasons.push('主力净流出')

  return {
    score,
    direction,
    breakdown: { direction: directionScore, volume: volumeScore, fund: fundScore },
    quadrant,
    reasons,
  }
}
