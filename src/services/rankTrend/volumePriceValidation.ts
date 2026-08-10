/**
 * 量价展示辅助（前端只消费，评分由后端生产）。
 *
 * 阶段 2（四象观察）后：量价评分（0-100）由后端 `observation.volumePrice` 产出
 * （Python `compute_volume_price_score`，与 TS 旧版同口径），前端经
 * `RankTrendSignalService` 投影 `_volumePrice*` 字段消费，与三轨数据链路一致。
 * 本文件仅保留展示层辅助：象限标签、资金分类、量能标签（不含评分计算）。
 */
import { toFiniteNumber } from '@/utils/volumeRatio'

/** 主力净占比对倒阈值（与后端 volume_price.py _ABNORMAL_FUND_RATIO=20 口径一致） */
const ABNORMAL_FUND_RATIO = 20

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
 * 资金子信号（展示分类）：zlje > 0 且（zljzb 缺失时仅用 zlje）> 0 → support；
 * zlje <= 0 → divergent；zlje 缺失 → noData。
 */
export function classifyFundSignal(zlje: unknown, zljzb: unknown): 'support' | 'divergent' | 'suspect' | 'noData' {
  const inflow = toFiniteNumber(zlje)
  if (inflow === null) return 'noData'
  const ratio = toFiniteNumber(zljzb)
  // 对倒出货：主力净占比异常高（与后端 fund_score 的 zljzb>20 惩罚口径一致，展示不伪称净流入）
  if (ratio !== null && ratio > ABNORMAL_FUND_RATIO) return 'suspect'
  if (inflow > 0) {
    if (ratio === null || ratio > 0) return 'support'
    return 'divergent' // zlje>0 但 zljzb<=0：数据不一致，按背离保守处理
  }
  return 'divergent'
}

export const volumeStateLabel = (volume: 'up' | 'down' | 'normal' | 'noData'): string =>
  volume === 'up' ? '放量' : volume === 'down' ? '缩量' : volume === 'normal' ? '常态' : '无量比基准'
