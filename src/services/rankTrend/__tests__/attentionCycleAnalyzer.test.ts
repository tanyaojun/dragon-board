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

  it('输出生命周期辅助决策合同，避免 entryAdvice 承担交易许可', () => {
    const cycle = analyzeAttentionCycle({
      ranks: [88, 76, 61, 44],
      percentiles: [18, 26, 39, 57],
    })

    expect(cycle.decision.action).toBe('allow')
    expect(cycle.decision.confidence).toBeGreaterThanOrEqual(50)
    expect(cycle.decision.reasons.length).toBeGreaterThan(0)
    expect(cycle.decision.evidence.rawStage).toBe(cycle.rawStage)
    expect(cycle.decision.evidence.stage).toBe(cycle.stage)
    expect(cycle.decision.evidence.transition).toBe(cycle.transition)
    expect(cycle.decision.evidence.rankVelocity).toBe(cycle.metrics.rankVelocity)
    expect(cycle.decision.evidence.rankAcceleration).toBe(cycle.metrics.rankAcceleration)
    expect(cycle.decision.evidence.drawdownFromPeak).toBe(cycle.metrics.drawdownFromPeak)
    expect(cycle.decision.evidence.hotZoneStreak).toBe(cycle.metrics.hotZoneStreak)
  })

  it('生命周期辅助决策证据可以承接真实风险压力', () => {
    const cycle = analyzeAttentionCycle({
      ranks: [88, 76, 61, 44],
      percentiles: [18, 26, 39, 57],
      risk: {
        pressure: 0.42,
        divergenceSeverity: 0.35,
        overheatSeverity: 0.51,
      },
    })

    expect(cycle.decision.evidence.riskPressure).toBe(0.42)
    expect(cycle.decision.evidence.divergenceSeverity).toBe(0.35)
    expect(cycle.decision.evidence.overheatSeverity).toBe(0.51)
  })

  it('点火或扩散路径出现高风险背离时不能继续普通 allow', () => {
    const cycle = analyzeAttentionCycle({
      ranks: [88, 76, 61, 44],
      percentiles: [18, 26, 39, 57],
      risk: {
        pressure: 0.78,
        divergenceSeverity: 0.84,
        overheatSeverity: 0.72,
      },
    })

    expect(cycle.stage).toBe('ignition')
    expect(cycle.decision.action).toBe('veto')
    expect(cycle.decision.reasons.join(' ')).toContain('风险')
  })

  it('生命周期输出漏选研究提示但不制造交易许可', () => {
    const cycle = analyzeAttentionCycle({
      ranks: [120, 96, 72, 55],
      percentiles: [28, 41, 53, 64],
    })

    expect(cycle.decision.discovery.action).toBe('research_watch')
    expect(cycle.decision.discovery.reasons.join(' ')).toContain('漏选')
    expect(cycle.decision.action).toBe('allow')
  })

  it('最后一跳很猛但整段承接不足时生命周期B应标记假突破谨慎而非硬否决', () => {
    const cycle = analyzeAttentionCycle({
      ranks: [132, 134, 133, 132, 131, 130, 72],
      percentiles: [32, 31, 31.5, 32, 33, 34, 69],
    })

    const evidence = cycle.decision.evidence as Record<string, number>
    expect(evidence.rankPathCommitment).toBeLessThan(0.45)
    expect(cycle.decision.action).toBe('caution')
    expect(cycle.decision.reasons.join(' ')).toContain('承接')
  })

  it('路径承接偏弱但中长动量已建立时不应被承接质量单点误杀', () => {
    const cycle = analyzeAttentionCycle({
      ranks: [132, 134, 133, 132, 131, 130, 72],
      percentiles: [32, 31, 31.5, 32, 33, 34, 69],
      momentumProfile: {
        short: 17.03,
        mid: 16.61,
        long: 36.07,
        acceleration: 23.51,
      },
    })

    expect(cycle.decision.evidence.rankPathCommitment).toBeLessThan(0.45)
    expect(cycle.decision.action).not.toBe('veto')
    expect(cycle.decision.reasons.join(' ')).not.toContain('一票否决')
  })

  it('低长周期动量但整段承接连续改善时生命周期B不能误杀', () => {
    const cycle = analyzeAttentionCycle({
      ranks: [108, 101, 94, 88, 81, 74, 68],
      percentiles: [42, 47, 51, 55, 59, 63, 68],
    })

    const evidence = cycle.decision.evidence as Record<string, number>
    expect(evidence.rankPathCommitment).toBeGreaterThanOrEqual(0.65)
    expect(cycle.decision.action).not.toBe('veto')
    expect(cycle.decision.reasons.join(' ')).not.toContain('长周期')
  })

  it('首段点火但注意力承接尚未扩散时生命周期B应标记低可见度抢仓风险', () => {
    const cycle = analyzeAttentionCycle({
      ranks: [132, 131, 130, 128, 126, 124, 82],
      percentiles: [32, 32.5, 33, 34, 35, 36, 60],
      momentumProfile: {
        short: 21.83,
        mid: 28.95,
        long: 23.83,
        acceleration: 24.29,
      },
    })

    expect(cycle.stage).toBe('ignition')
    expect(cycle.transition).toBe('cooling->ignition')
    expect(cycle.metrics.hotZoneStreak).toBe(0)
    expect(cycle.decision.evidence.rankPathCommitment).toBeLessThan(0.7)
    expect(cycle.decision.action).toBe('caution')
    expect(cycle.decision.reasons.join(' ')).toContain('低可见度')
  })

  it('高热回撤会识别为 reversal', () => {
    const cycle = analyzeAttentionCycle({
      ranks: [18, 8, 4, 6, 9],
      percentiles: [82, 93, 97, 94, 89],
    })

    expect(cycle.stage).toBe('reversal')
    expect(cycle.entryAdvice.bias).toBe('blocked')
    expect(cycle.decision.action).toBe('veto')
    expect(cycle.decision.reasons.join(' ')).toContain('反转')
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
