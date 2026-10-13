import { describe, expect, it } from 'vitest'

import { L1EventEngine, formatMoney } from '../L1EventEngine'
import type { L1QuoteSnapshot } from '../L1QuoteSnapshot'

function makeQuote(overrides: Partial<L1QuoteSnapshot> = {}): L1QuoteSnapshot {
  return {
    code: '600001',
    name: '测试股',
    lastPrice: 10,
    changePct: 5,
    changeAmount: 0.5,
    volume: 100_000,
    amount: 1_000_000,
    open: 9.5,
    high: 10,
    low: 9.4,
    preClose: 9.52,
    bids: [{ price: 9.99, volume: 500 }],
    asks: [{ price: 10.01, volume: 300 }],
    sourceTime: Date.parse('2026-10-13T10:00:00+08:00'),
    ...overrides,
  }
}

/** 涨停封板快照：last=bid1=涨停价，封单 1000 手 ×10 元 = 1000万 */
function sealedQuote(overrides: Partial<L1QuoteSnapshot> = {}, limitPct = 10): L1QuoteSnapshot {
  const preClose = overrides.preClose ?? 9.52
  const limitUp = Math.round(preClose * (1 + limitPct / 100) * 100) / 100
  return makeQuote({
    lastPrice: limitUp,
    changePct: (limitUp - preClose) / preClose * 100,
    bids: [{ price: limitUp, volume: 1000 }],
    asks: [{ price: limitUp, volume: 0 }],
    ...overrides,
    preClose,
  })
}

describe('L1EventEngine（对齐 L1EventEngine.cs）', () => {
  it('首板封板：事件名"封涨停板"，Reason 含买一封单金额', () => {
    const engine = new L1EventEngine()
    const events = engine.evaluate(sealedQuote(), null, [])
    const seal = events.find(item => item.type === 'LimitUpSealed')
    expect(seal?.typeName).toBe('封涨停板')
    expect(seal?.severity).toBe('critical')
    expect(seal?.reason).toContain('买一封单')
  })

  it('昨日涨停股今日再封：事件名"N连板"', () => {
    const engine = new L1EventEngine()
    engine.setLimitUpStreaks(new Map([['600001', 2]]))
    const events = engine.evaluate(sealedQuote(), null, [])
    const seal = events.find(item => item.type === 'LimitUpSealed')
    expect(seal?.typeName).toBe('3连板')
  })

  it('同日打开后回封：LimitUpResealed + 首板标签', () => {
    const engine = new L1EventEngine()
    const sealed = sealedQuote()
    engine.evaluate(sealed, null, [])
    // 打开
    const opened = makeQuote({ sourceTime: sealed.sourceTime + 10_000 })
    engine.evaluate(opened, sealed, [sealed])
    // 回封
    const resealed = sealedQuote({ sourceTime: sealed.sourceTime + 20_000 })
    const events = engine.evaluate(resealed, opened, [sealed, opened])
    const reseal = events.find(item => item.type === 'LimitUpResealed')
    expect(reseal?.typeName).toBe('涨停回封')
    expect(reseal?.severity).toBe('critical')
  })

  it('打开涨停板：封转开触发一次', () => {
    const engine = new L1EventEngine()
    const sealed = sealedQuote()
    engine.evaluate(sealed, null, [])
    const events = engine.evaluate(makeQuote({ sourceTime: sealed.sourceTime + 10_000 }), sealed, [sealed])
    expect(events.filter(item => item.type === 'LimitUpOpened')).toHaveLength(1)
  })

  it('逼近涨停：距涨停 1% 内且未封', () => {
    const engine = new L1EventEngine()
    const preClose = 10
    const price = preClose * 1.095
    const quote = makeQuote({
      preClose,
      lastPrice: price,
      changePct: 9.5,
      open: preClose,
      high: price,
      low: preClose,
    })
    const events = engine.evaluate(quote, null, [])
    expect(events.some(item => item.type === 'NearLimitUp')).toBe(true)
  })

  it('新股（N前缀）不报涨跌停事件，冲高回落报新股开板', () => {
    const engine = new L1EventEngine()
    const preClose = 10
    const quote = makeQuote({
      code: '301600',
      name: 'N新股份',
      preClose,
      high: preClose * 1.3,
      lastPrice: preClose * 1.2,
      changePct: 20,
    })
    const events = engine.evaluate(quote, null, [])
    expect(events.some(item => item.type === 'LimitUpSealed')).toBe(false)
    const opened = events.find(item => item.type === 'NewStockOpened')
    expect(opened).toBeTruthy()
    expect(opened?.reason).toContain('冲高')
  })

  it('快速拉升：30 秒窗口涨幅破阈值', () => {
    const engine = new L1EventEngine()
    const t0 = Date.parse('2026-10-13T10:00:00+08:00')
    const base = makeQuote({ lastPrice: 10, sourceTime: t0 })
    const now = makeQuote({ lastPrice: 10.3, sourceTime: t0 + 15_000 })
    const history = [
      // 基线须落在 [now-40s, now-30s]：更旧会被断档守卫（窗口+容忍度）判 0，与 C# 一致
      makeQuote({ lastPrice: 10, sourceTime: t0 - 20_000 }),
      base,
    ]
    const events = engine.evaluate(now, base, history)
    expect(events.some(item => item.type === 'FastRise')).toBe(true)
  })

  it('快照断档：超窗口+容忍度的旧基线不产快拉快跳', () => {
    const engine = new L1EventEngine()
    const t0 = Date.parse('2026-10-13T10:00:00+08:00')
    const staleBase = makeQuote({ lastPrice: 9, sourceTime: t0 - 120_000 })
    const now = makeQuote({ lastPrice: 10.3, sourceTime: t0 })
    const events = engine.evaluate(now, staleBase, [staleBase])
    expect(events.some(item => item.type === 'FastRise')).toBe(false)
  })

  it('封单增强：较前帧增 50% 触发', () => {
    const engine = new L1EventEngine()
    const sealed = sealedQuote({ bids: [{ price: 10.47, volume: 1000 }] })
    engine.evaluate(sealed, null, [])
    const stronger = sealedQuote({ bids: [{ price: 10.47, volume: 1600 }], sourceTime: sealed.sourceTime + 31_000 })
    const events = engine.evaluate(stronger, sealed, [sealed])
    const increased = events.find(item => item.type === 'SealOrderIncreased')
    expect(increased?.reason).toContain('封单增至')
  })

  it('ST 股涨跌幅按 5% 判定', () => {
    const engine = new L1EventEngine()
    const preClose = 10
    const limitUp = Math.round(preClose * 1.05 * 100) / 100
    const quote = sealedQuote({
      code: '600000',
      name: 'ST测试',
      preClose,
      lastPrice: limitUp,
      bids: [{ price: limitUp, volume: 1000 }],
    }, 5)
    const events = engine.evaluate(quote, null, [])
    expect(events.some(item => item.type === 'LimitUpSealed')).toBe(true)
  })

  it('翻红翻绿：涨跌幅符号翻转', () => {
    const engine = new L1EventEngine()
    const previous = makeQuote({ changePct: -1 })
    const events = engine.evaluate(makeQuote({ changePct: 0.5 }), previous, [])
    expect(events.some(item => item.type === 'TurnRed')).toBe(true)
  })

  it('formatMoney：万/亿换算', () => {
    expect(formatMoney(1_500_000_000)).toBe('15亿')
    expect(formatMoney(12_000_000)).toBe('1200万')
    expect(formatMoney(999)).toBe('999')
  })
})
