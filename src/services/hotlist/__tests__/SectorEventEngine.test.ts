import { describe, expect, it } from 'vitest'

import { SectorEventEngine } from '../SectorEventEngine'
import type { ConceptMapResult } from '../ConceptMapLoader'
import { buildL1EventRecord, type L1EventRecord } from '../l1EventCatalog'
import type { L1QuoteSnapshot } from '../L1QuoteSnapshot'

function makeMap(pairs: Array<[string, string[]]>): ConceptMapResult {
  const sectorToStocks = new Map(pairs)
  const stockToSectors = new Map<string, string[]>()
  for (const [sector, codes] of pairs) {
    for (const code of codes) {
      const list = stockToSectors.get(code) || []
      list.push(sector)
      stockToSectors.set(code, list)
    }
  }
  return {
    sectorToStocks,
    stockToSectors,
    fetchedAt: null,
    stale: false,
    errors: [],
    conceptCount: sectorToStocks.size,
  }
}

function makeQuote(code: string, changePct: number, sourceTime: number): L1QuoteSnapshot {
  return {
    code,
    name: `股${code}`,
    lastPrice: 10,
    changePct,
    changeAmount: 0,
    volume: 100,
    amount: 1000,
    open: 10,
    high: 10,
    low: 10,
    preClose: 10,
    bids: [],
    asks: [],
    sourceTime,
  }
}

function makeStockEvent(type: 'LimitUpSealed' | 'LimitUpOpened' | 'LimitUpResealed', code: string, timestamp: number): L1EventRecord {
  return buildL1EventRecord({
    type,
    typeName: type === 'LimitUpSealed' ? '封涨停板' : type === 'LimitUpOpened' ? '打开涨停板' : '涨停回封',
    code,
    name: `股${code}`,
    price: 10,
    changePct: 10,
    volume: 0,
    amount: 0,
    timestamp,
    severity: 'critical',
    reason: 'test',
  })
}

const T0 = Date.parse('2026-10-13T10:00:00+08:00')

describe('SectorEventEngine（对齐 SectorEventEngine.cs）', () => {
  it('板块拉升：涨家数≥3、占比≥60%、均涨≥1%', () => {
    const engine = new SectorEventEngine()
    const map = makeMap([['算力', ['000001', '000002', '000003', '000004']]])
    const quotes = [
      makeQuote('000001', 3, T0),
      makeQuote('000002', 2, T0),
      makeQuote('000003', 1.5, T0),
      makeQuote('000004', -1, T0),
    ]
    const events = engine.evaluate(quotes, [], map, T0)
    const rush = events.find(item => item.type === 'SectorRush')
    expect(rush).toBeTruthy()
    expect(rush?.sector).toBe('算力')
    expect(rush?.severity).toBe('important')
    expect(rush?.reason).toContain('3 涨 1 跌')
    expect(rush?.reason).toContain('领涨')
  })

  it('板块跳水：跌家数与均跌达标触发，方向为 down 语义（avg<0）', () => {
    const engine = new SectorEventEngine()
    const map = makeMap([['算力', ['000001', '000002', '000003', '000004']]])
    const quotes = [
      makeQuote('000001', -2, T0),
      makeQuote('000002', -3, T0),
      makeQuote('000003', -1.5, T0),
      makeQuote('000004', 1, T0),
    ]
    const events = engine.evaluate(quotes, [], map, T0)
    expect(events.some(item => item.type === 'SectorDive')).toBe(true)
  })

  it('涨停潮：600s 窗口内 2 只成员封板触发 Critical，事件带 MemberCodes 且窗口清空', () => {
    const engine = new SectorEventEngine()
    const map = makeMap([['算力', ['000001', '000002']]])
    engine.evaluate([makeQuote('000001', 10, T0), makeQuote('000002', 10, T0)], [
      makeStockEvent('LimitUpSealed', '000001', T0),
    ], map, T0)
    const events = engine.evaluate([makeQuote('000001', 10, T0), makeQuote('000002', 10, T0)], [
      makeStockEvent('LimitUpSealed', '000002', T0 + 5000),
    ], map, T0 + 5000)
    const wave = events.find(item => item.type === 'SectorLimitUpWave')
    expect(wave).toBeTruthy()
    expect(wave?.severity).toBe('critical')
    expect(wave?.memberCodes).toEqual(['000001', '000002'])
    // 窗口清空后同窗口不重复
    const again = engine.evaluate([makeQuote('000001', 10, T0), makeQuote('000002', 10, T0)], [
      makeStockEvent('LimitUpResealed', '000001', T0 + 6000),
    ], map, T0 + 6000)
    expect(again.some(item => item.type === 'SectorLimitUpWave')).toBe(false)
  })

  it('冷却：同板块同类型 600s 内不重复', () => {
    const engine = new SectorEventEngine()
    const map = makeMap([['算力', ['000001', '000002', '000003']]])
    const quotes = [makeQuote('000001', 2, T0), makeQuote('000002', 2, T0), makeQuote('000003', 2, T0)]
    expect(engine.evaluate(quotes, [], map, T0).some(item => item.type === 'SectorRush')).toBe(true)
    expect(engine.evaluate(quotes, [], map, T0 + 300_000).some(item => item.type === 'SectorRush')).toBe(false)
    expect(engine.evaluate(quotes, [], map, T0 + 600_000).some(item => item.type === 'SectorRush')).toBe(true)
  })

  it('窗口过期：超 600s 的封板事件出窗不触发潮', () => {
    const engine = new SectorEventEngine()
    const map = makeMap([['算力', ['000001', '000002']]])
    const quotes = [makeQuote('000001', 10, T0), makeQuote('000002', 10, T0)]
    engine.evaluate(quotes, [makeStockEvent('LimitUpSealed', '000001', T0)], map, T0)
    const events = engine.evaluate(quotes, [makeStockEvent('LimitUpSealed', '000002', T0 + 601_000)], map, T0 + 601_000)
    expect(events.some(item => item.type === 'SectorLimitUpWave')).toBe(false)
  })

  it('空映射安静返回空（告警由 ConceptMapResult.errors 上报）', () => {
    const engine = new SectorEventEngine()
    const events = engine.evaluate([makeQuote('000001', 5, T0)], [], makeMap([]), T0)
    expect(events).toHaveLength(0)
  })

  it('开板潮：窗口内 2 只成员开板触发', () => {
    const engine = new SectorEventEngine()
    const map = makeMap([['算力', ['000001', '000002']]])
    const quotes = [makeQuote('000001', 10, T0), makeQuote('000002', 10, T0)]
    engine.evaluate(quotes, [makeStockEvent('LimitUpOpened', '000001', T0)], map, T0)
    const events = engine.evaluate(quotes, [makeStockEvent('LimitUpOpened', '000002', T0 + 5000)], map, T0 + 5000)
    expect(events.some(item => item.type === 'SectorLimitUpOpenWave')).toBe(true)
  })
})
