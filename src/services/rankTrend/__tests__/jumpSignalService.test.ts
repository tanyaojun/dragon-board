import { describe, expect, it } from 'vitest'
import { checkEntryConditions } from '../jumpSignalService'
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
    ).toBe(true)
  })

  it('缺少多周期动量和加速度共振时不触发入场', () => {
    expect(
      checkEntryConditions(
        { code: '600001', rank: 8, change: 2.5 },
        rankTrendWithSignals('buy', 'hold'),
        baseJump,
      ),
    ).toBe(false)
  })
})
