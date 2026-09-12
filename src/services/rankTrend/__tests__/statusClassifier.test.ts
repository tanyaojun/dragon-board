import { describe, expect, it } from 'vitest'

import { getRankTrendDisplayBreakdown, getRankTrendDisplayStatus, stageClassKey } from '../statusClassifier'

// 2026-09-10 口径统一：displayStatus 是后端 `cycle.stage` 的纯投影 {stage, label, tooltip}。
// 本文件是**纯消费合同测试**：直通 / 无阶段 / 未知态 / breakdown 同源词表；不做任何本地分类。
const withStatus = (displayStatus?: unknown) => ({ displayStatus }) as any

describe('getRankTrendDisplayStatus（后端 stage 投影直通）', () => {
  it('后端有 displayStatus 时逐字透传 stage/label/tooltip', () => {
    const status = getRankTrendDisplayStatus(
      withStatus({ stage: 'crowded', label: '拥挤', tooltip: '注意力拥挤高位，追高风险上升。' }),
    )
    expect(status).toEqual({
      stage: 'crowded',
      label: '拥挤',
      tooltip: '注意力拥挤高位，追高风险上升。',
    })
  })

  it('stage 为 null 时保留"无阶段"（有记录但阶段缺失）', () => {
    const status = getRankTrendDisplayStatus(
      withStatus({ stage: null, label: '无阶段', tooltip: '生命周期阶段缺失或非法，无法判定。' }),
    )
    expect(status.stage).toBeNull()
    expect(status.label).toBe('无阶段')
  })

  it('stage 非字符串（数字/空串）时归一为 null', () => {
    expect(getRankTrendDisplayStatus(withStatus({ stage: 3, label: '冷却' })).stage).toBeNull()
    expect(getRankTrendDisplayStatus(withStatus({ stage: '', label: '冷却' })).stage).toBeNull()
  })

  it('displayStatus 整体缺失 → 结构化未知（与"无阶段"区分）', () => {
    const status = getRankTrendDisplayStatus(withStatus(undefined))
    expect(status.stage).toBeNull()
    expect(status.label).toBe('未知')
    expect(status.tooltip).toContain('缺失')
    expect(getRankTrendDisplayStatus(null).label).toBe('未知')
  })

  it('label 非字符串视为缺失，不误当有效状态', () => {
    expect(getRankTrendDisplayStatus(withStatus({ stage: 'crowded', label: 3 })).label).toBe('未知')
    expect(getRankTrendDisplayStatus(withStatus({ stage: 'crowded', label: null })).label).toBe('未知')
  })
})

describe('stageClassKey', () => {
  it('有 stage 时 stage-<stage>，无 stage 时 stage-none', () => {
    expect(stageClassKey('cooling')).toBe('stage-cooling')
    expect(stageClassKey(null)).toBe('stage-none')
  })
})

describe('getRankTrendDisplayBreakdown（同源词表，无本地映射）', () => {
  it('周期栏与展示状态栏同用后端 label', () => {
    const breakdown = getRankTrendDisplayBreakdown(
      withStatus({ stage: 'ignition', label: '点火', tooltip: '点火启动，观察是否扩散。' }),
    )
    expect(breakdown.displayStatusLabel).toBe('点火')
    expect(breakdown.cycleLabel).toBe('点火')
    expect(breakdown.classKeys.displayStatus).toBe('stage-ignition')
    expect(breakdown.classKeys.cycle).toBe('cycle-ignition')
    expect(breakdown.tooltip).toContain('展示状态：点火')
  })

  it('未知态的 classKey 为 stage-none', () => {
    const breakdown = getRankTrendDisplayBreakdown(withStatus(undefined))
    expect(breakdown.displayStatusLabel).toBe('未知')
    expect(breakdown.classKeys.displayStatus).toBe('stage-none')
    expect(breakdown.classKeys.cycle).toBe('cycle-empty')
  })

  it('无 rankTrend 时质量栏标样本不足，且不伪造 stage', () => {
    const breakdown = getRankTrendDisplayBreakdown(null)
    expect(breakdown.qualityLabel).toBe('样本不足')
    expect(breakdown.classKeys.quality).toBe('quality-insufficient')
    expect(breakdown.classKeys.displayStatus).toBe('stage-none')
  })

  it('breakdown 不再包含 8 类风险栏字段（分类层已删除）', () => {
    const breakdown = getRankTrendDisplayBreakdown(
      withStatus({ stage: 'cooling', label: '冷却', tooltip: 't' }),
    ) as Record<string, any>
    expect(breakdown.riskLabel).toBeUndefined()
    expect(breakdown.classKeys.risk).toBeUndefined()
  })
})
