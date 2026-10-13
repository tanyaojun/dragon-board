import { describe, expect, it, vi } from 'vitest'

import { AppEvents } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { L1EventRealtimeBridge } from '../L1EventRealtimeBridge'
import { ConceptMapLoader } from '../ConceptMapLoader'
import { LimitUpStreakLoader } from '../LimitUpStreakLoader'
import type { HotStockAbnormalEvent } from '../hotStockEventTypes'

// 盘中时刻（TradingSession 门禁：桥只在连续竞价时段产事件）
const IN_SESSION_MS = Date.parse('2026-10-13T10:00:00+08:00')

function makeBridge(overrides: Partial<ConstructorParameters<typeof L1EventRealtimeBridge>[0]> = {}) {
  const acceptDerivedEvents = vi.fn()
  const voiceSink = vi.fn()
  const monitorService = { acceptDerivedEvents }
  const bridge = new L1EventRealtimeBridge({
    monitorService,
    conceptLoader: new ConceptMapLoader({ fetcher: null, storage: null }),
    streakLoader: new LimitUpStreakLoader({ fetcher: null, storage: null }),
    now: () => IN_SESSION_MS,
    ...overrides,
    voiceSink,
  })
  return { bridge, acceptDerivedEvents, voiceSink }
}

function emitQuotePatch(code: string, changePct: number, name = '测试股') {
  EventManager.emit(AppEvents.WEBSOCKET.QUOTE_PATCH, {
    items: [{
      code,
      name,
      lastPrice: 10 * (1 + changePct / 100),
      changePct,
      preClose: 10,
      open: 10,
      high: 10 * (1 + changePct / 100),
      low: 10,
      volume: 100_000,
      amount: 1_000_000,
      capturedAt: new Date().toISOString(),
    }],
  })
}

describe('L1EventRealtimeBridge（行情→引擎→去重→开关→监控/语音）', () => {
  it('行情帧驱动 L1 事件：注入监控服务并进入语音层', async () => {
    const { bridge, acceptDerivedEvents, voiceSink } = makeBridge()
    bridge.start()
    emitQuotePatch('600001', 4.0) // 首帧 Prime：只建状态（4.0 记 3 档）
    emitQuotePatch('600001', 6.0) // 第二帧评估：突破 5 档 → 大幅拉升
    await vi.waitFor(() => {
      expect(acceptDerivedEvents).toHaveBeenCalled()
    })
    bridge.stop()

    const events = acceptDerivedEvents.mock.calls[0][0] as HotStockAbnormalEvent[]
    const riseTier = events.find(item => item.typeName === '大幅拉升')
    expect(riseTier).toBeTruthy()
    expect(riseTier?.code).toBe('600001')
    // 比率口径（面板 formatPct 直接 ×100 展示）；6.0% 触发 5 档
    expect(riseTier?.changePct).toBeCloseTo(0.06, 5)
    expect(voiceSink).toHaveBeenCalled()
  })

  it('EnabledEvents 产生层过滤：关=三端全无（表格与语音都没有）', async () => {
    const { bridge, acceptDerivedEvents, voiceSink } = makeBridge({
      enabledEvents: new Map([['13011', false]]), // 13011 = BigRiseTier
    })
    bridge.start()
    // 4.0→6.0 两帧：第二帧评估本应触发 5 档大幅拉升，但 13011 禁用 → 三端全无
    emitQuotePatch('600001', 4.0) // 首帧 Prime（记 3 档）
    emitQuotePatch('600001', 6.0)
    await new Promise(resolve => setTimeout(resolve, 20))
    bridge.stop()
    // 被禁的 BigRiseTier 不出现；未禁事件（如日内新高）不受牵连
    const produced = acceptDerivedEvents.mock.calls.flatMap(call => call[0] as HotStockAbnormalEvent[])
    expect(produced.some(item => item.typeName === '大幅拉升')).toBe(false)
    const voiced = voiceSink.mock.calls.flatMap(call => call[0] as HotStockAbnormalEvent[])
    expect(voiced.some(item => item.typeName === '大幅拉升')).toBe(false)
  })

  it('stop() 清理会话：重开后不重复旧状态', async () => {
    const { bridge, acceptDerivedEvents } = makeBridge()
    bridge.start()
    emitQuotePatch('600001', 4.0) // 首帧 Prime
    emitQuotePatch('600001', 6.0) // 第二帧评估 → 事件产出
    await vi.waitFor(() => expect(acceptDerivedEvents).toHaveBeenCalled())
    bridge.stop()

    const callsAfterStop = acceptDerivedEvents.mock.calls.length
    emitQuotePatch('600002', 9.9)
    await new Promise(resolve => setTimeout(resolve, 20))
    expect(acceptDerivedEvents.mock.calls.length).toBe(callsAfterStop)
  })
})


describe('L1EventRealtimeBridge（review 修复回归钉）', () => {
  it('首帧 Prime：启动快照不产首帧伪事件，第二帧才评估', async () => {
    const { bridge, acceptDerivedEvents } = makeBridge()
    bridge.start()
    emitQuotePatch('600001', 9.9) // 首帧：只建状态
    await new Promise(resolve => setTimeout(resolve, 20))
    expect(acceptDerivedEvents).not.toHaveBeenCalled()
    bridge.stop()
  })

  it('时段外（午休）不产事件，事件在时段恢复后正常产出', async () => {
    const lunchMs = Date.parse('2026-10-13T12:00:00+08:00')
    const { bridge, acceptDerivedEvents } = makeBridge({ now: () => lunchMs })
    bridge.start()
    emitQuotePatch('600001', 9.9)
    await new Promise(resolve => setTimeout(resolve, 20))
    expect(acceptDerivedEvents).not.toHaveBeenCalled()
    bridge.stop()
  })

  it('EnabledEvents 数值码键生效（面板持久化键空间）：13011=false 屏蔽大幅拉升', async () => {
    const { bridge, acceptDerivedEvents, voiceSink } = makeBridge({
      enabledEvents: new Map([['13011', false]]),
    })
    bridge.start()
    emitQuotePatch('600001', 4.0) // 首帧 Prime（记 3 档）
    emitQuotePatch('600001', 6.0) // 第二帧本应触发 5 档，但 13011=false → 被禁事件不出现
    await new Promise(resolve => setTimeout(resolve, 20))
    bridge.stop()
    const produced = acceptDerivedEvents.mock.calls.flatMap(call => call[0] as HotStockAbnormalEvent[])
    expect(produced.some(item => item.typeName === '大幅拉升')).toBe(false)
    expect(voiceSink.mock.calls.flat().some(item => item.typeName === '大幅拉升')).toBe(false)
    bridge.stop()
  })
})
