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

  it('accepts version rollback after server reset instead of permanently dropping rows', () => {
    const service = (marketFundStreamService as any)
    service.versions.clear()

    const first = normalize({
      code: '000010',
      zlje: 100,
      version: 10,
      moneyFlowSource: 'ths_main_monitor',
    })
    // 服务端 version 重置（Redis 清空/后端重启后 version 从头计数）：
    // 新 version 2 < 10，修复前被永久丢弃，修复后应接受
    const second = normalize({
      code: '000010',
      zlje: 90,
      version: 2,
      moneyFlowSource: 'ths_main_monitor',
    })

    expect(first).toMatchObject({ code: '000010', zlje: 100 })
    expect(second).toMatchObject({ code: '000010', zlje: 90, version: 2 })
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
})
