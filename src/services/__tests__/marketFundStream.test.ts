import { beforeEach, describe, expect, it } from 'vitest'

import { marketFundStreamService } from '../marketFundStream'

function normalize(row: Record<string, unknown>) {
  return (marketFundStreamService as any).normalizeRow.call(marketFundStreamService, row)
}

describe('marketFundStream normalizeRow', () => {
  it('accepts ths_main_monitor and ths_web_seed rows with version and zlje', () => {
    const l2 = normalize({
      code: '000001',
      zlje: 100,
      version: 3,
      moneyFlowSource: 'ths_main_monitor',
    })
    const seed = normalize({
      code: '000002',
      zlje: 50,
      version: 1,
      moneyFlowSource: 'ths_web_seed',
      moneyFlowEstimated: true,
    })

    expect(l2).toMatchObject({ code: '000001', zlje: 100, moneyFlowSource: 'ths_main_monitor' })
    expect(seed).toMatchObject({
      code: '000002',
      zlje: 50,
      moneyFlowSource: 'ths_web_seed',
      moneyFlowEstimated: true,
    })
  })

  it('rejects non-dashboard sources and invalid rows', () => {
    expect(
      normalize({
        code: '000003',
        zlje: 99,
        version: 1,
        moneyFlowSource: 'tdx_transaction',
      }),
    ).toBeNull()
    expect(
      normalize({
        code: '000004',
        zlje: 99,
        version: 1,
        moneyFlowSource: 'eastmoney',
      }),
    ).toBeNull()
    expect(
      normalize({
        code: '000004',
        zlje: 'not-a-number',
        version: 1,
        moneyFlowSource: 'ths_main_monitor',
      }),
    ).toBeNull()
    expect(
      normalize({
        code: '000005',
        zlje: 99,
        version: NaN,
        moneyFlowSource: 'ths_web_seed',
      }),
    ).toBeNull()
  })

  it('drops out-of-order older version instead of overwriting newer', () => {
    const service = (marketFundStreamService as any)
    service.versions.clear()

    const first = normalize({
      code: '000010',
      zlje: 100,
      version: 10,
      moneyFlowSource: 'ths_main_monitor',
    })
    // P2-2（2026-08-11 审计）：乱序/回退旧版本直接丢弃，不覆盖新值
    const stale = normalize({
      code: '000010',
      zlje: 90,
      version: 9,
      moneyFlowSource: 'ths_main_monitor',
    })

    expect(first).toMatchObject({ code: '000010', zlje: 100, version: 10 })
    expect(stale).toBeNull()
  })

  it('accepts reset version after fund_full_state clears local versions', () => {
    const service = (marketFundStreamService as any)
    service.versions.clear()

    normalize({
      code: '000011',
      zlje: 100,
      version: 10,
      moneyFlowSource: 'ths_main_monitor',
    })
    // 服务端 version 重置（Redis 清空/后端重启）：fund_full_state 全量快照到达时
    // 清空本地版本记录，之后重置的小 version 被接受
    service.handlePayload({ type: 'fund_full_state', version: 1, items: [] })
    const afterReset = normalize({
      code: '000011',
      zlje: 90,
      version: 2,
      moneyFlowSource: 'ths_main_monitor',
    })

    expect(afterReset).toMatchObject({ code: '000011', zlje: 90, version: 2 })
  })

  it('skips duplicate version pushes', () => {
    const service = (marketFundStreamService as any)
    service.versions.clear()

    normalize({
      code: '000012',
      zlje: 100,
      version: 7,
      moneyFlowSource: 'ths_main_monitor',
    })
    const duplicate = normalize({
      code: '000012',
      zlje: 100,
      version: 7,
      moneyFlowSource: 'ths_main_monitor',
    })

    expect(duplicate).toBeNull()
  })
})

describe('marketFundStream subscription protocol', () => {
  class FakeWebSocket {
    static instances: FakeWebSocket[] = []
    readyState = 1 // WebSocket.OPEN
    sent: string[] = []
    url: string
    private listeners: Record<string, () => void> = {}
    constructor(url: string) {
      this.url = url
      FakeWebSocket.instances.push(this)
    }
    addEventListener(type: string, fn: () => void) {
      this.listeners[type] = fn
    }
    emitOpen() {
      this.listeners.open?.()
    }
    send(data: string) {
      this.sent.push(data)
    }
    close() {}
  }

  function lastSentMessage(): any {
    const instance = FakeWebSocket.instances[FakeWebSocket.instances.length - 1]
    return JSON.parse(instance.sent[instance.sent.length - 1])
  }

  beforeEach(() => {
    FakeWebSocket.instances.length = 0
    ;(globalThis as any).window = {} // connect() 依赖 typeof window !== 'undefined'
    ;(globalThis as any).WebSocket = FakeWebSocket
  })

  it('sends priorityCodes along with codes when priority is provided', () => {
    ;(globalThis as any).WebSocket = FakeWebSocket
    const service = (marketFundStreamService as any)
    service.socket = null

    service.setSubscription(['000001', '000002', '000003'], ['000001', '000002'])
    ;(FakeWebSocket.instances.at(-1) as FakeWebSocket).emitOpen()

    expect(lastSentMessage()).toEqual({
      codes: ['000001', '000002', '000003'],
      priorityCodes: ['000001', '000002'],
    })
    service.disconnect()
  })

  it('omits priorityCodes when not provided', () => {
    ;(globalThis as any).WebSocket = FakeWebSocket
    const service = (marketFundStreamService as any)
    service.socket = null

    service.setSubscription(['000001'])
    ;(FakeWebSocket.instances.at(-1) as FakeWebSocket).emitOpen()

    expect(lastSentMessage()).toEqual({ codes: ['000001'] })
    service.disconnect()
  })

  it('filters priority codes that are not in the subscribed pool', () => {
    ;(globalThis as any).WebSocket = FakeWebSocket
    const service = (marketFundStreamService as any)
    service.socket = null

    service.setSubscription(['000001'], ['000002']) // 000002 不在池内
    ;(FakeWebSocket.instances.at(-1) as FakeWebSocket).emitOpen()

    expect(lastSentMessage()).toEqual({ codes: ['000001'] })
    service.disconnect()
  })

  it('keeps the socket alive on empty subscription instead of disconnecting', () => {
    // P1-1（2026-08-11 审计）：平台临时加载失败导致热榜暂空时，不得主动断开
    // fund-stream（断开后恢复依赖重连，且会清空后端订阅池）
    ;(globalThis as any).WebSocket = FakeWebSocket
    const service = (marketFundStreamService as any)
    service.socket = null

    service.setSubscription(['000001'])
    ;(FakeWebSocket.instances.at(-1) as FakeWebSocket).emitOpen()
    expect(service.socket).toBeTruthy()

    service.setSubscription([])
    // 空订阅不清空 codes 保留连接；socket 不被关闭
    expect(service.socket).toBeTruthy()
    service.disconnect()
  })
})
