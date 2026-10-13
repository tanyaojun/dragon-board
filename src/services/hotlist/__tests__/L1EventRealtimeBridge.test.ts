import { describe, expect, it, vi } from 'vitest'

import { AppEvents } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { L1EventRealtimeBridge } from '../L1EventRealtimeBridge'
import { ConceptMapLoader } from '../ConceptMapLoader'
import { LimitUpStreakLoader } from '../LimitUpStreakLoader'
import type { HotStockAbnormalEvent } from '../hotStockEventTypes'

function makeBridge(overrides: Partial<ConstructorParameters<typeof L1EventRealtimeBridge>[0]> = {}) {
  const acceptDerivedEvents = vi.fn()
  const voiceSink = vi.fn()
  const monitorService = { acceptDerivedEvents }
  const bridge = new L1EventRealtimeBridge({
    monitorService,
    conceptLoader: new ConceptMapLoader({ fetcher: null, storage: null }),
    streakLoader: new LimitUpStreakLoader({ fetcher: null, storage: null }),
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
    emitQuotePatch('600001', 9.9)
    await vi.waitFor(() => {
      expect(acceptDerivedEvents).toHaveBeenCalled()
    })
    bridge.stop()

    const events = acceptDerivedEvents.mock.calls[0][0] as HotStockAbnormalEvent[]
    const riseTier = events.find(item => item.typeName === '大幅拉升')
    expect(riseTier).toBeTruthy()
    expect(riseTier?.code).toBe('600001')
    // 比率口径（面板 formatPct 直接 ×100 展示）
    expect(riseTier?.changePct).toBeCloseTo(0.099, 5)
    expect(voiceSink).toHaveBeenCalled()
  })

  it('EnabledEvents 产生层过滤：关=三端全无（表格与语音都没有）', async () => {
    const { bridge, acceptDerivedEvents, voiceSink } = makeBridge({
      enabledEvents: new Map([['13011', false]]), // 13011 = BigRiseTier
    })
    bridge.start()
    // 4.0% 只触发涨幅破档（3 档），不触发逼近涨停（需 ≥9%）
    emitQuotePatch('600001', 4.0)
    await new Promise(resolve => setTimeout(resolve, 20))
    bridge.stop()
    expect(acceptDerivedEvents).not.toHaveBeenCalled()
    expect(voiceSink).not.toHaveBeenCalled()
  })

  it('stop() 清理会话：重开后不重复旧状态', async () => {
    const { bridge, acceptDerivedEvents } = makeBridge()
    bridge.start()
    emitQuotePatch('600001', 9.9)
    await vi.waitFor(() => expect(acceptDerivedEvents).toHaveBeenCalled())
    bridge.stop()

    const callsAfterStop = acceptDerivedEvents.mock.calls.length
    emitQuotePatch('600002', 9.9)
    await new Promise(resolve => setTimeout(resolve, 20))
    expect(acceptDerivedEvents.mock.calls.length).toBe(callsAfterStop)
  })
})
