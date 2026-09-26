/**
 * 量比状态判定（golden 3 日口径，绝对阈值）。
 * 量比 = 当前成交量 / (近 3 日同期均量 × 交易进度)：>1 放量、<1 缩量，业务语义清晰。
 * 1.0 附近 ±0.05 缓冲（常态区间）避免噪声抖动。纯函数、无状态。
 */

export type VolumeRatioState = 'up' | 'down' | 'normal' | 'unknown'

// 量比绝对阈值（golden 3 日口径）：≥1.05 放量、≤0.95 缩量
const UP_THRESHOLD = 1.05
const DOWN_THRESHOLD = 0.95

export function toFiniteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

/**
 * 判定个股量比状态（绝对阈值，3 日口径）。
 * @param ratio 个股量比（golden 3 日口径或腾讯 f10 兜底值）
 * @param _median 历史中位数仅作参考（不参与分类，保留签名兼容）
 * @returns 'up' 放量（≥1.05）/ 'down' 缩量（≤0.95）/ 'normal' 常态（1.0 附近）/ 'unknown' 数值缺失
 */
export function classifyVolumeRatio(
  ratio: unknown,
  _median?: unknown,
): VolumeRatioState {
  const ratioNum = toFiniteNumber(ratio)
  if (ratioNum === null || ratioNum <= 0) {
    return 'unknown'
  }
  if (ratioNum >= UP_THRESHOLD) return 'up'
  if (ratioNum <= DOWN_THRESHOLD) return 'down'
  return 'normal'
}

export function volumeRatioStateLabel(state: VolumeRatioState): string {
  switch (state) {
    case 'up':
      return '放量'
    case 'down':
      return '缩量'
    case 'normal':
      return '常态'
    default:
      return '无量比基准'
  }
}
