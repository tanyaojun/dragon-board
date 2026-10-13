/**
 * 板块异动聚合引擎：与 tools/YiDongJingLing/Events/SectorEventEngine.cs 语义完全一致。
 * - 每轮行情批量后按概念映射聚合监控池成员；
 * - 个股封板/回封滚入板块 600s 滚动窗口 → 涨停潮；开板 → 开板潮；
 * - 拉升/跳水按 涨（跌）家数 + 占比 + 均涨阈值触发；
 * - 同板块同类型 600s 冷却；无映射安静返回空（告警由 ConceptMapResult.errors 上报）。
 */
import {
  buildL1EventRecord,
  type L1EventRecord,
  type L1EventTypeName,
} from './l1EventCatalog'
import type { SectorEventRules } from './l1EventRules'
import { DEFAULT_SECTOR_EVENT_RULES } from './l1EventRules'
import type { ConceptMapResult } from './ConceptMapLoader'
import { ask1Price, ask1Volume, bid1Price, bid1Volume, type L1QuoteSnapshot } from './L1QuoteSnapshot'

interface WindowEntry {
  at: number
  code: string
}

export class SectorEventEngine {
  private readonly rules: SectorEventRules
  private readonly sealWindow = new Map<string, WindowEntry[]>()
  private readonly openWindow = new Map<string, WindowEntry[]>()
  private readonly lastEmitted = new Map<string, number>()

  constructor(rules?: Partial<SectorEventRules>) {
    this.rules = { ...DEFAULT_SECTOR_EVENT_RULES, ...rules }
  }

  clear() {
    this.sealWindow.clear()
    this.openWindow.clear()
    this.lastEmitted.clear()
  }

  evaluate(
    quotes: readonly L1QuoteSnapshot[],
    stockEvents: readonly L1EventRecord[],
    map: ConceptMapResult,
    now: number,
  ): L1EventRecord[] {
    const results: L1EventRecord[] = []
    if (!quotes.length || map.sectorToStocks.size === 0) return results

    const quotesByCode = new Map<string, L1QuoteSnapshot>()
    for (const quote of quotes) quotesByCode.set(quote.code, quote)

    // 1) 板块成员行情聚合（仅统计监控池内出现快照的成员）
    const sectorMembers = new Map<string, L1QuoteSnapshot[]>()
    for (const [sector, codes] of map.sectorToStocks) {
      const members: L1QuoteSnapshot[] = []
      for (const code of codes) {
        const quote = quotesByCode.get(code)
        if (quote) members.push(quote)
      }
      if (members.length) sectorMembers.set(sector, members)
    }

    // 2) 封板/开板事件滚入板块滚动窗口（回封与首封同等计入涨停潮）
    for (const evt of stockEvents) {
      if (evt.type !== 'LimitUpSealed' && evt.type !== 'LimitUpResealed' && evt.type !== 'LimitUpOpened') continue
      const window = evt.type === 'LimitUpOpened' ? this.openWindow : this.sealWindow
      const sectors = map.stockToSectors.get(evt.code) || []
      for (const sector of sectors) {
        const queue = window.get(sector) || []
        queue.push({ at: evt.timestamp, code: evt.code })
        window.set(sector, queue)
      }
    }

    // 3) 触发判定
    for (const [sector, members] of sectorMembers) {
      const rise = members.filter(item => item.changePct > 0).length
      const fall = members.filter(item => item.changePct < 0).length
      const avg = round2(members.reduce((sum, item) => sum + item.changePct, 0) / members.length)

      if (this.waveTriggered(this.sealWindow, sector, now)) {
        if (this.tryEmit(results, sector, 'SectorLimitUpWave', '板块涨停潮', 'critical', members, rise, fall, avg, now, windowCodes(this.sealWindow, sector))) {
          this.sealWindow.set(sector, [])
        }
      }
      if (this.waveTriggered(this.openWindow, sector, now)) {
        if (this.tryEmit(results, sector, 'SectorLimitUpOpenWave', '板块开板潮', 'critical', members, rise, fall, avg, now, windowCodes(this.openWindow, sector))) {
          this.openWindow.set(sector, [])
        }
      }
      if (
        rise >= this.rules.minRiseCount &&
        members.length > 0 &&
        rise >= members.length * this.rules.riseRatio &&
        avg >= this.rules.rushMinAvgPct
      ) {
        this.tryEmit(results, sector, 'SectorRush', '板块拉升', 'important', members, rise, fall, avg, now)
      }
      if (
        fall >= this.rules.minFallCount &&
        members.length > 0 &&
        fall >= members.length * this.rules.fallRatio &&
        avg <= this.rules.diveMaxAvgPct
      ) {
        this.tryEmit(results, sector, 'SectorDive', '板块跳水', 'important', members, rise, fall, avg, now)
      }
    }

    this.pruneWindows(now)
    return results
  }

  private waveTriggered(window: Map<string, WindowEntry[]>, sector: string, now: number): boolean {
    const queue = window.get(sector)
    if (!queue || queue.length < this.rules.waveThreshold) return false
    while (queue.length && now - queue[0].at > this.rules.waveWindowMs) {
      queue.shift()
    }
    return queue.length >= this.rules.waveThreshold
  }

  private tryEmit(
    results: L1EventRecord[],
    sector: string,
    type: L1EventTypeName,
    typeName: string,
    severity: 'critical' | 'important',
    members: L1QuoteSnapshot[],
    rise: number,
    fall: number,
    avg: number,
    now: number,
    memberCodes?: string[],
  ): boolean {
    const key = `S:${sector}:${type}`
    const last = this.lastEmitted.get(key)
    if (last !== undefined && now - last < this.rules.cooldownMs) return false
    this.lastEmitted.set(key, now)

    const leaders = [...members]
      .sort((a, b) => b.changePct - a.changePct)
      .slice(0, 3)
      .map(item => `${item.name || item.code} ${formatNumber(item.changePct)}%`)
    const reason = `${members.length} 只成员 ${rise} 涨 ${fall} 跌，均涨 ${formatNumber(avg)}%；领涨 ${leaders.join('、')}`

    results.push(buildL1EventRecord({
      type,
      typeName,
      code: '',
      name: sector,
      price: 0,
      changePct: avg,
      volume: 0,
      amount: 0,
      timestamp: now,
      severity,
      reason,
      sector,
      memberCodes: memberCodes ? dedupe(memberCodes) : [],
    }))
    return true
  }

  private pruneWindows(now: number) {
    prune(this.sealWindow, now, this.rules.waveWindowMs)
    prune(this.openWindow, now, this.rules.waveWindowMs)
  }
}

function windowCodes(window: Map<string, WindowEntry[]>, sector: string): string[] {
  const queue = window.get(sector)
  return queue ? dedupe(queue.map(item => item.code)) : []
}

function prune(window: Map<string, WindowEntry[]>, now: number, windowMs: number) {
  for (const queue of window.values()) {
    while (queue.length && now - queue[0].at > windowMs) {
      queue.shift()
    }
  }
}

function dedupe(values: string[]): string[] {
  return [...new Set(values)]
}

function round2(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.round(value * 100) / 100
}

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return '0'
  const text = value.toFixed(2).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')
  return text === '-0' ? '0' : text
}
