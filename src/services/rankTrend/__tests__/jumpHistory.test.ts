import { describe, expect, it } from 'vitest'
import { buildJumpHistoryView } from '../jumpHistory'

describe('buildJumpHistoryView', () => {
  it('组装跳动摘要与事件列表（含方向标签与幅度）', () => {
    const view = buildJumpHistoryView({
      event: 'jump',
      direction: 'buy',
      signal: 'buy',
      magnitude: 29.41,
      overshoot: 14.41,
      sustained: true,
      confidence: 95,
      eventCount: 24,
      surgeCount: 12,
      collapseCount: 12,
      confirmed: true,
      events: [
        { index: 2, direction: 'collapse', magnitude: 47.23 },
        { index: 5, direction: 'surge', magnitude: 32.97 },
      ],
    })
    expect(view).not.toBeNull()
    expect(view).toMatchObject({
      eventCount: 24,
      surgeCount: 12,
      collapseCount: 12,
      magnitudeText: '+29.4%',
      directionText: '买入',
      confirmed: true,
    })
    expect(view?.items).toEqual([
      { key: 'e2', isSurge: false, isCollapse: true, label: '#2', magnitudeText: '-47.2%' },
      { key: 'e5', isSurge: true, isCollapse: false, label: '#5', magnitudeText: '+33.0%' },
    ])
  })

  it('无事件（event=none / events 空）返回 null，区块整段隐藏', () => {
    expect(buildJumpHistoryView({ event: 'none', events: [] })).toBeNull()
    expect(buildJumpHistoryView(undefined)).toBeNull()
    expect(buildJumpHistoryView({ event: 'jump', magnitude: 10 })).toBeNull()
  })

  it('direction 卖出/持有方向正确映射', () => {
    const view = buildJumpHistoryView({
      event: 'jump',
      direction: 'sell',
      magnitude: 15,
      events: [{ index: 1, direction: 'surge', magnitude: 15 }],
    })
    expect(view?.directionText).toBe('卖出')
  })
})

describe('buildJumpHistoryView 未知方向', () => {
  it('direction 非 surge/collapse 时中性无符号（fail-visible，不猜涨跌）', () => {
    const view = buildJumpHistoryView({
      event: 'jump',
      magnitude: 22,
      events: [{ index: 3, direction: 'hold', magnitude: 26.14 }],
    })
    expect(view?.items[0]).toMatchObject({
      isSurge: false,
      isCollapse: false,
      magnitudeText: '26.1%',
    })
  })
})
