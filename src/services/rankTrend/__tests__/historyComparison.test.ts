import { describe, expect, it } from 'vitest'
import {
  pickPreviousFrame,
  buildHistoryComparisonView,
  type HistoryFrameRef,
} from '../historyComparison'

const frames: HistoryFrameRef[] = [
  { snapshotId: 'half_hour:2026-09-12:15:00', tradingDate: '2026-09-12', slotTime: '15:00' },
  { snapshotId: 'half_hour:2026-09-12:14:30', tradingDate: '2026-09-12', slotTime: '14:30' },
  { snapshotId: 'half_hour:2026-09-12:09:30', tradingDate: '2026-09-12', slotTime: '09:30' },
]

describe('pickPreviousFrame', () => {
  it('优先取前一交易日同时点帧', () => {
    expect(pickPreviousFrame(frames, '14:30')?.snapshotId).toBe('half_hour:2026-09-12:14:30')
  })

  it('同时点缺失时回退前一交易日最新帧（15:00 收盘）', () => {
    expect(pickPreviousFrame(frames, '10:00')?.snapshotId).toBe('half_hour:2026-09-12:15:00')
  })

  it('空帧列表返回 null（fail-visible，不伪造）', () => {
    expect(pickPreviousFrame([], '09:30')).toBeNull()
  })
})

describe('buildHistoryComparisonView', () => {
  it('组装昨日同时点的 状态/分层/信号/迁移 视图并标记变化', () => {
    const view = buildHistoryComparisonView(
      {
        displayStatus: { stage: 'ignition', label: '点火' },
        cycle: { transition: 'cooling->ignition' },
        strategy: { candidateTier: 'B_IGNITION' },
        decision: { final: { signal: 'buy' } },
      },
      { stageLabel: '冷却', tier: 'N_NEUTRAL', signal: 'hold' },
    )
    expect(view).toMatchObject({
      stageLabel: '点火',
      transition: 'cooling->ignition',
      changed: true,
    })
  })

  it('状态与分层均未变时 changed=false', () => {
    const view = buildHistoryComparisonView(
      { displayStatus: { stage: 'cooling', label: '冷却' }, strategy: { candidateTier: 'N_NEUTRAL' } },
      { stageLabel: '冷却', tier: 'N_NEUTRAL', signal: 'hold' },
    )
    expect(view?.changed).toBe(false)
  })

  it('无昨日分析产物返回 null（新上榜股，不伪造）', () => {
    expect(buildHistoryComparisonView(undefined, { stageLabel: '冷却', tier: 'N_NEUTRAL', signal: 'hold' })).toBeNull()
  })
})
