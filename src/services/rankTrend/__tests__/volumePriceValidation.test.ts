import { describe, expect, it } from 'vitest'

import {
  classifyFundSignal,
  getVolumePriceQuadrantLabel,
  volumeStateLabel,
} from '@/services/rankTrend/volumePriceValidation'

// 量价评分（computeVolumePriceScore）已由后端生产（observation.volumePrice，Python compute_volume_price_score），
// 前端只消费 _volumePrice* 字段；本文件仅测展示辅助函数。

describe('classifyFundSignal（资金子信号，展示分类）', () => {
  it('zlje>0 且 zljzb>0 → 资金配合', () => {
    expect(classifyFundSignal(1000000, 0.5)).toBe('support')
  })

  it('zljzb 缺失时仅用 zlje', () => {
    expect(classifyFundSignal(1000000, null)).toBe('support')
    expect(classifyFundSignal(1000000, undefined)).toBe('support')
  })

  it('zlje<=0 → 资金背离；zlje 缺失 → noData', () => {
    expect(classifyFundSignal(0, 0.5)).toBe('divergent')
    expect(classifyFundSignal(-500000, 0.5)).toBe('divergent')
    expect(classifyFundSignal(null, 0.5)).toBe('noData')
  })

  it('zljzb>20（对倒出货）→ suspect，不伪称净流入（与后端惩罚口径一致）', () => {
    expect(classifyFundSignal(1000000, 53.83)).toBe('suspect')
    expect(classifyFundSignal(1000000, 20.1)).toBe('suspect')
    expect(classifyFundSignal(-100000, 53.83)).toBe('suspect')
    expect(classifyFundSignal(1000000, 20)).toBe('support') // 边界 =20 仍算配合
  })
})

describe('getVolumePriceQuadrantLabel', () => {
  it('四象限 + 常态 + 缺失标签', () => {
    expect(getVolumePriceQuadrantLabel('rise_volume')).toBe('放量上涨')
    expect(getVolumePriceQuadrantLabel('rise_shrink')).toBe('缩量上涨')
    expect(getVolumePriceQuadrantLabel('fall_volume')).toBe('放量下跌')
    expect(getVolumePriceQuadrantLabel('fall_shrink')).toBe('缩量下跌')
    expect(getVolumePriceQuadrantLabel('normal')).toBe('量能常态')
    expect(getVolumePriceQuadrantLabel(null)).toBe('--')
  })
})

describe('volumeStateLabel', () => {
  it('量能四态标签', () => {
    expect(volumeStateLabel('up')).toBe('放量')
    expect(volumeStateLabel('down')).toBe('缩量')
    expect(volumeStateLabel('normal')).toBe('常态')
    expect(volumeStateLabel('noData')).toBe('无量比基准')
  })
})
