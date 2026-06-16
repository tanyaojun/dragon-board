import { describe, expect, it } from 'vitest'
import { checkEntryConditions, evaluateJumpSignal } from '../jumpSignalService'
import { applyJumpSignal } from '../compat'
import type { JumpResult } from '../jumpDetector'
import type { RankTrendAnalysisResult } from '../types'

const baseJump: JumpResult = {
  event: 'jump',
  direction: 'buy',
  signal: 'buy',
  magnitude: 28,
  overshoot: 13,
  delta: 15,
  sustained: true,
  confidence: 90,
  eventCount: 2,
  surgeCount: 2,
  collapseCount: 0,
  events: [],
}

function rankTrendWithSignals(direction: string, acceleration: string): RankTrendAnalysisResult {
  return {
    technical: {
      macd: { cross: 'golden' },
      signals: {
        direction: { signal: direction },
        acceleration: { signal: acceleration },
      },
    },
  } as RankTrendAnalysisResult
}

describe('checkEntryConditions', () => {
  it('不因当前名次数字拦截 RankTrend 跃迁共振信号', () => {
    expect(
      checkEntryConditions(
        { code: '600001', rank: 88, change: 2.5 },
        rankTrendWithSignals('buy', 'buy'),
        baseJump,
      ),
    ).toEqual({ passed: true, limitUp: false })
  })

  it('缺少多周期动量和加速度共振时不触发入场', () => {
    expect(
      checkEntryConditions(
        { code: '600001', rank: 8, change: 2.5 },
        rankTrendWithSignals('buy', 'hold'),
        baseJump,
      ),
    ).toEqual({ passed: false, limitUp: false })
  })

  it('涨停只标记 limitUp，不再阻断入场条件结果', () => {
    expect(
      checkEntryConditions(
        { code: '600001', change: 9.8 },
        rankTrendWithSignals('buy', 'buy'),
        baseJump,
      ),
    ).toEqual({ passed: true, limitUp: true })
  })
})

describe('evaluateJumpSignal', () => {
  it('将 checkEntryConditions 产出的 limitUp 透传到聚合结果', () => {
    const result = evaluateJumpSignal(
      { code: '600001', change: 9.8 },
      rankTrendWithSignals('buy', 'buy'),
      [10, 35, 55, 80],
      true,
    )

    expect(result.limitUp).toBe(true)
  })
})

describe('applyJumpSignal', () => {
  it('将 limitUp 写入 rankTrend.jump 和兼容字段', () => {
    const stock = { rankTrend: {} }

    applyJumpSignal(stock, {
      jump: baseJump,
      isEntry: true,
      isExit: false,
      exitReason: '',
      limitUp: true,
    })

    expect(stock.rankTrend.jump.limitUp).toBe(true)
    expect(stock.rankTrend._jumpLimitUp).toBe(true)
  })
})
