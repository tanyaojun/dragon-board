import { describe, expect, it } from 'vitest'
import { detectRankJumps } from '../jumpDetector'

describe('detectRankJumps', () => {
  it('样本不足 3 帧时返回 none', () => {
    const r = detectRankJumps([50, 55], undefined, 15)
    expect(r.event).toBe('none')
    expect(r.direction).toBe('hold')
    expect(r.sustained).toBe(false)
    expect(r.eventCount).toBe(0)
  })

  it('单次累计变化未触及阈值时返回 none', () => {
    const r = detectRankJumps([50, 55, 58, 60], undefined, 15)
    expect(r.event).toBe('none')
    expect(r.cumulativeChange).toBe(10)
  })

  it('累计变化超过 delta 时触发 surge 跳跃事件', () => {
    // 50 → 68: cum_change = 18 > 15(delta)
    const r = detectRankJumps([50, 58, 65, 68], undefined, 15)
    expect(r.event).toBe('jump')
    expect(r.direction).toBe('buy')
    expect(r.sustained).toBe(false) // 仅一次事件
    expect(r.surgeCount).toBe(1)
    expect(r.collapseCount).toBe(0)
  })

  it('负向累计变化超过 delta 时触发 collapse 事件', () => {
    // 80 → 60: cum_change = -20, abs > 15
    const r = detectRankJumps([80, 72, 65, 60], undefined, 15)
    expect(r.event).toBe('jump')
    expect(r.direction).toBe('sell')
    expect(r.surgeCount).toBe(0)
    expect(r.collapseCount).toBe(1)
  })

  it('连续两次同向事件判定为 sustained', () => {
    // 50 → 70 (触发) → 重置参考点 → 再涨到 85 (再次触发)
    const r = detectRankJumps([50, 60, 70, 75, 80, 85], undefined, 15)
    expect(r.event).toBe('jump')
    expect(r.sustained).toBe(true)
    expect(r.eventCount).toBeGreaterThanOrEqual(2)
  })

  it('来回震荡不触发——累计变化互相抵消', () => {
    // 50 → 60 → 50 → 60 → 50: 纯震荡，累计变化始终不超 delta
    const r = detectRankJumps([50, 60, 50, 60, 50, 60], undefined, 15)
    expect(r.event).toBe('none')
  })

  it('delta 参数可自定义', () => {
    // delta=5: 50→57 cum_change=7 > 5, 触发（需至少 3 帧）
    const r = detectRankJumps([50, 55, 57], undefined, 5)
    expect(r.event).toBe('jump')
    expect(r.delta).toBe(5)
  })

  it('置信度随幅度和过冲量增加', () => {
    // 大幅跳跃: 50→80, cum_change=30, delta=15, overshoot=15
    const rLarge = detectRankJumps([50, 65, 80], undefined, 15)
    // 刚好触发: 50→66, cum_change=16, delta=15, overshoot=1
    const rSmall = detectRankJumps([50, 66], undefined, 15)

    expect(rLarge.confidence).toBeGreaterThan(rSmall.confidence)
    expect(rLarge.confidence).toBeGreaterThanOrEqual(55)
    expect(rLarge.confidence).toBeLessThanOrEqual(95)
  })

  it('空序列返回 none', () => {
    const r = detectRankJumps([], undefined, 15)
    expect(r.event).toBe('none')
  })

  it('单元素序列返回 none', () => {
    const r = detectRankJumps([50], undefined, 15)
    expect(r.event).toBe('none')
  })

  it('提供 ranks 时计算 rankMagnitude', () => {
    const r = detectRankJumps([50, 60, 70], [200, 150, 80], 15)
    expect(r.event).toBe('jump')
    expect(r.rankMagnitude).toBe(120) // |80 - 200|
  })

  it('参考点重置到近 3 帧均值而非极值', () => {
    // 构造序列：50→70 (触发 surge) → 重置到近3帧均值 ≈ 63
    // 然后 63→50 cum_change=-13, abs < 15, 不触发反向
    const percentiles = [50, 60, 70]
    // 在 index=2 (70) 触发 surge，ref 重置到 (60+70)/2=65 或 (50+60+70)/3=60
    // 继续加几帧降下来：
    percentiles.push(65, 55, 50)
    const r = detectRankJumps(percentiles, undefined, 15)
    // 应该只有一次 surge 事件，降回来时因为参考点已重置而未触发 collapse
    expect(r.event).toBe('jump')
    expect(r.direction).toBe('buy')
    expect(r.collapseCount).toBe(0)
  })
})
