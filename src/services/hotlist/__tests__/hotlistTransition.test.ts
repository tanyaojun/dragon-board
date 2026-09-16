import { describe, expect, it } from 'vitest'
import { formatTransitionCounts } from '../hotlistTransition'

describe('formatTransitionCounts', () => {
  it('a->b 迁移串格式化为「阶段A→阶段B」并按次数降序截取 topN', () => {
    const items = formatTransitionCounts(
      { cooling: 3, 'ignition->cooling': 28, 'expansion->reversal': 18, 'reversal->cooling': 9 },
      3,
    )
    expect(items).toHaveLength(3)
    expect(items[0]).toMatchObject({ key: 'ignition->cooling', text: '点火→冷却', count: 28 })
    expect(items[1]).toMatchObject({ key: 'expansion->reversal', text: '扩散→反转', count: 18 })
    expect(items[2]).toMatchObject({ key: 'reversal->cooling', text: '反转→冷却', count: 9 })
  })

  it('单段迁移表示阶段延续，格式化为「阶段X延续」', () => {
    const items = formatTransitionCounts({ cooling: 156 })
    expect(items[0].text).toBe('冷却延续')
    expect(items[0].count).toBe(156)
  })

  it('未知阶段键原样保留（不伪装、不丢弃）', () => {
    const items = formatTransitionCounts({ 'mystery->cooling': 2 })
    expect(items[0].text).toBe('mystery→冷却')
  })

  it('空/缺字段返回空数组（调用方隐藏整行，不伪造）', () => {
    expect(formatTransitionCounts(null)).toEqual([])
    expect(formatTransitionCounts({})).toEqual([])
  })
})
