import { describe, expect, it } from 'vitest'

import { analyzeAttentionCycle } from '../attentionCycleAnalyzer'

describe('analyzeAttentionCycle', () => {
  it('仅基于热榜轨迹识别 cooling->ignition', () => {
    const cycle = analyzeAttentionCycle({
      ranks: [88, 76, 61, 44],
      percentiles: [18, 26, 39, 57],
    })

    expect(cycle.stage).toBe('ignition')
    expect(cycle.transition).toBe('cooling->ignition')
    expect(cycle.entryAdvice.bias).toBe('preferred')
  })

  it('高热回撤会识别为 reversal', () => {
    const cycle = analyzeAttentionCycle({
      ranks: [18, 8, 4, 6, 9],
      percentiles: [82, 93, 97, 94, 89],
    })

    expect(cycle.stage).toBe('reversal')
    expect(cycle.entryAdvice.bias).toBe('blocked')
    expect(cycle.metrics.drawdownFromPeak).toBeGreaterThanOrEqual(1)
  })

  it('单个高热快照不会被误判为 reversal', () => {
    const cycle = analyzeAttentionCycle({
      ranks: [8],
      percentiles: [91],
    })

    expect(cycle.stage).toBe('cooling')
    expect(cycle.rawStage).toBe('cooling')
  })
})
