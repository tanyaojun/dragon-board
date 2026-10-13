/**
 * L1 事件实时桥：与 tools/YiDongJingLing/MainForm.cs 的行情→事件管线语义完全一致。
 * WS 实时行情（FULL_STATE/QUOTE_PATCH）+ 十档盘口（DEPTH_PATCH + getDepth10 快照）
 * → L1QuoteSnapshot（含 6 分钟历史窗）→ L1EventEngine → 冷却去重 → EnabledEvents 产生层过滤
 * → SectorEventEngine（消费已产出的个股封板/开板事件）→ 板块事件同样去重+过滤
 * → 合并注入 HotStockEventMonitorService（表格/飞书）+ 语音层回调。
 *
 * 竞价弱转强不在此桥处理：OpeningRealtimeEventBridge 已独立产出，避免双份事件。
 */
import { AppEvents, type QuotePatch } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { webSocketService } from '../websocket'
import { EventDeduper } from './EventDeduper'
import { filterForVoice, type VoiceLayerSettings, type VoiceMode } from './EventVoicePolicy'
import { ConceptMapLoader, sectorsOf, type ConceptMapResult } from './ConceptMapLoader'
import {
  L1_EVENT_CATALOG,
  type L1EventRecord,
  type L1EventTypeName,
} from './l1EventCatalog'
import { L1EventEngine } from './L1EventEngine'
import { buildL1QuoteSnapshot, type L1QuoteSnapshot } from './L1QuoteSnapshot'
import { LimitUpStreakLoader } from './LimitUpStreakLoader'
import { SectorEventEngine } from './SectorEventEngine'
import { hotStockEventMonitorService } from './HotStockEventMonitorService'
import { hotStockEventSpeechService } from './HotStockEventSpeechService'
import type { HotStockAbnormalEvent, HotStockAbnormalEventType } from './hotStockEventTypes'
import type { HotStockEventMonitorServiceLike } from './l1EventBridgeTypes'

/** L1 本地事件数值码段：13xxx 与选股宝 10xxx/11xxx、竞价弱转强 12001 不冲突。 */
export const L1_EVENT_TYPE_CODES: Record<L1EventTypeName, number> = {
  LimitUpSealed: 13001,
  LimitUpOpened: 13002,
  UpcomingLimitUpOpen: 13003,
  NearLimitUp: 13004,
  LimitDownSealed: 13005,
  LimitDownOpened: 13006,
  UpcomingLimitDownOpen: 13007,
  NearLimitDown: 13008,
  SealOrderIncreased: 13009,
  SealOrderWeakened: 13010,
  BigRiseTier: 13011,
  BigDropTier: 13012,
  FastRise: 13013,
  FastDrop: 13014,
  TurnRed: 13015,
  TurnGreen: 13016,
  IntradayHigh: 13017,
  IntradayLow: 13018,
  AmountTier: 13019,
  VolumeAcceleration: 13020,
  LargeBidOrder: 13021,
  LargeAskOrder: 13022,
  LowOpenLongYang: 13023,
  HighOpenLongYin: 13024,
  NewStockOpened: 13025,
  NewStockReseal: 13026,
  LimitUpResealed: 13027,
  SectorRush: 13028,
  SectorDive: 13029,
  SectorLimitUpWave: 13030,
  SectorLimitUpOpenWave: 13031,
  BidPressure: 13032,
  AskPressure: 13033,
  SpreadWidened: 13034,
}

const CODE_BY_L1_TYPE = new Map(Object.entries(L1_EVENT_TYPE_CODES).map(([name, code]) => [code, name as L1EventTypeName]))

export function l1EventLabel(typeName: string): string {
  return L1_EVENT_CATALOG.find(entry => entry.type === typeName)?.label || typeName
}

export function isL1NumericEventType(type: number): boolean {
  return CODE_BY_L1_TYPE.has(type)
}

const HISTORY_WINDOW_MS = 6 * 60_000
const DIRECTION_BY_TYPE: Partial<Record<L1EventTypeName, 'up' | 'down' | 'neutral'>> = {
  LimitUpSealed: 'up',
  NearLimitUp: 'up',
  SealOrderIncreased: 'up',
  FastRise: 'up',
  BigRiseTier: 'up',
  TurnRed: 'up',
  IntradayHigh: 'up',
  LowOpenLongYang: 'up',
  NewStockReseal: 'up',
  LimitUpResealed: 'up',
  LimitUpOpened: 'down',
  UpcomingLimitUpOpen: 'down',
  SealOrderWeakened: 'down',
  FastDrop: 'down',
  BigDropTier: 'down',
  TurnGreen: 'down',
  IntradayLow: 'down',
  HighOpenLongYin: 'down',
  NewStockOpened: 'down',
  LimitDownSealed: 'down',
  LimitDownOpened: 'up',
  UpcomingLimitDownOpen: 'up',
  NearLimitDown: 'down',
  SectorRush: 'up',
  SectorDive: 'down',
  SectorLimitUpWave: 'up',
  SectorLimitUpOpenWave: 'down',
}

export interface L1EventRealtimeBridgeOptions {
  monitorService: HotStockEventMonitorServiceLike
  engine?: L1EventEngine
  sectorEngine?: SectorEventEngine
  deduper?: EventDeduper
  sectorDeduper?: EventDeduper
  conceptLoader?: ConceptMapLoader
  streakLoader?: LimitUpStreakLoader
  /** 产生层事件开关（EnabledEvents），键为 L1EventTypeName。 */
  enabledEvents?: Map<string, boolean>
  /** 语音层回调：已过 VoiceMode/VoiceEvents 过滤的 L1 事件（零丢失逐条交给语音服务）。 */
  voiceSink?: (events: L1EventRecord[]) => void | Promise<void>
  now?: () => number
}

/**
 * 行情→事件→板块聚合→语音 的实时桥。start() 订阅 WS；stop() 反订阅并清状态。
 * 语音层（voiceSink）收到的是 VoiceMode/VoiceEvents 过滤后的 L1 事件（零丢失逐条交给语音服务）。
 */
export class L1EventRealtimeBridge {
  private readonly monitorService: HotStockEventMonitorServiceLike
  private readonly engine: L1EventEngine
  private readonly sectorEngine: SectorEventEngine
  private readonly deduper: EventDeduper
  private readonly sectorDeduper: EventDeduper
  private readonly conceptLoader: ConceptMapLoader
  private readonly streakLoader: LimitUpStreakLoader
  private readonly voiceSink: (events: L1EventRecord[]) => void | Promise<void>
  private readonly now: () => number
  private readonly historyByCode = new Map<string, L1QuoteSnapshot[]>()
  private readonly previousByCode = new Map<string, L1QuoteSnapshot>()
  private conceptMap: ConceptMapResult
  private enabledEvents: Map<string, boolean>
  private unsubscribers: Array<() => void> = []
  private started = false
  private streaksLoaded = false

  constructor(options: L1EventRealtimeBridgeOptions) {
    this.monitorService = options.monitorService
    this.engine = options.engine || new L1EventEngine()
    this.sectorEngine = options.sectorEngine || new SectorEventEngine()
    this.deduper = options.deduper || new EventDeduper()
    this.sectorDeduper = options.sectorDeduper || new EventDeduper()
    this.conceptLoader = options.conceptLoader || new ConceptMapLoader()
    this.streakLoader = options.streakLoader || new LimitUpStreakLoader()
    this.conceptMap = this.conceptLoader.getMap()
    this.enabledEvents = options.enabledEvents || new Map()
    this.voiceSink = options.voiceSink || (() => {})
    this.now = options.now || Date.now
  }

  start() {
    if (this.started) return
    this.started = true
    this.unsubscribers = [
      EventManager.on(AppEvents.WEBSOCKET.FULL_STATE, payload => {
        this.acceptQuotes(Array.isArray(payload?.quotes) ? payload.quotes : [])
      }),
      EventManager.on(AppEvents.WEBSOCKET.QUOTE_PATCH, payload => {
        this.acceptQuotes(Array.isArray(payload?.items) ? payload.items : [])
      }),
      EventManager.on(AppEvents.WEBSOCKET.DEPTH_PATCH, payload => {
        this.acceptDepth(Array.isArray(payload?.items) ? payload.items : [])
      }),
    ]
    void this.loadStreaksOnce()
    void this.refreshConceptMap()
  }

  stop() {
    this.unsubscribers.forEach(unsubscribe => unsubscribe())
    this.unsubscribers = []
    this.started = false
    this.historyByCode.clear()
    this.previousByCode.clear()
    this.engine.clear()
    this.sectorEngine.clear()
    this.deduper.clear()
    this.sectorDeduper.clear()
  }

  setEnabledEvents(enabledEvents: Map<string, boolean>) {
    this.enabledEvents = enabledEvents
  }

  /** 产生层判定：键为 13xxx 数值码（与面板/持久化一致），兼容 typeName 键。 */
  private isTypeEnabled(typeName: L1EventTypeName): boolean {
    const byCode = this.enabledEvents.get(String(L1_EVENT_TYPE_CODES[typeName]))
    if (byCode !== undefined) return byCode
    const byName = this.enabledEvents.get(typeName)
    return byName === undefined ? true : byName
  }

  clearSession() {
    this.historyByCode.clear()
    this.previousByCode.clear()
    this.engine.clear()
    this.sectorEngine.clear()
    this.deduper.clear()
    this.sectorDeduper.clear()
  }

  acceptDepth(books: Array<{ code?: unknown; bids?: unknown; asks?: unknown }>) {
    // 盘口补丁只更新缓冲；事件计算统一在行情帧驱动，保证单线程时序
    for (const book of books) {
      const code = String(book?.code || '')
      const history = this.historyByCode.get(code)
      if (!history || !history.length) continue
      const latest = history[history.length - 1]
      if (!latest) continue
      const merged = buildL1QuoteSnapshot({
        ...latest,
        bids: normalizeDepth(book?.bids),
        asks: normalizeDepth(book?.asks),
        sourceTime: latest.sourceTime,
      })
      if (merged) history[history.length - 1] = merged
    }
  }

  acceptQuotes(quotes: readonly QuotePatch[]) {
    const nowMs = this.now()
    const batchSnapshots: L1QuoteSnapshot[] = []
    const stockEvents: L1EventRecord[] = []

    for (const patch of quotes) {
      const depth = webSocketService.getDepth10(patch.code)
      const snapshot = buildL1QuoteSnapshot({
        code: patch.code,
        name: patch.name,
        lastPrice: patch.lastPrice,
        changePct: patch.changePct,
        changeAmount: patch.changeAmount,
        volume: patch.volume,
        amount: patch.amount,
        open: patch.open,
        high: patch.high,
        low: patch.low,
        preClose: patch.preClose,
        capturedAt: patch.capturedAt,
        bridgeTs: patch.bridgeTs,
        sourceTime: timestampOf(patch, nowMs),
        bids: depth?.bids,
        asks: depth?.asks,
      })
      if (!snapshot) continue

      const history = this.historyByCode.get(snapshot.code) || []
      const previous = this.previousByCode.get(snapshot.code) || null
      const emitted = this.engine.evaluate(snapshot, previous, history)
      history.push(snapshot)
      this.pruneHistory(history, snapshot.sourceTime)
      this.historyByCode.set(snapshot.code, history)
      this.previousByCode.set(snapshot.code, snapshot)
      batchSnapshots.push(snapshot)
      for (const event of emitted) stockEvents.push(event)
    }

    if (!stockEvents.length && !batchSnapshots.length) return
    void this.publish(batchSnapshots, stockEvents, nowMs)
  }

  private async publish(
    batchSnapshots: readonly L1QuoteSnapshot[],
    stockEvents: readonly L1EventRecord[],
    nowMs: number,
  ) {
    // 冷却去重 → 产生层过滤（EnabledEvents 关=三端全无）
    const deduped = this.deduper.filter(stockEvents)
    const enabled = deduped.filter(item => this.isTypeEnabled(item.type))

    // 板块聚合吃"已产出"的个股封板/开板事件（开关关闭的封板不进潮，与 C# 一致）
    const sectorAll = this.sectorEngine.evaluate(batchSnapshots, enabled, this.conceptMap, nowMs)
    const sectorEnabled = sectorAll.filter(item => this.isTypeEnabled(item.type))
    const sectorEmitted = this.sectorDeduper.filter(sectorEnabled)

    const merged = [...enabled, ...sectorEmitted]
    if (!merged.length) return

    const asAbnormalEvents = merged.map(event => toAbnormalEvent(event, this.conceptMap))
    // 表格/飞书注入（监控服务内部按 category 拆分）
    this.monitorService.acceptDerivedEvents(asAbnormalEvents)

    // 语音层：VoiceMode/VoiceEvents 过滤后零丢失逐条交付
    const voiceEvents = filterForVoice(enabled, resolveVoiceMode(), { voiceEvents: resolveVoiceEvents() })
      .concat(filterForVoice(sectorEmitted, resolveVoiceMode(), { voiceEvents: resolveVoiceEvents() }))
    if (voiceEvents.length) {
      await this.voiceSink(voiceEvents)
    }
  }

  private async refreshConceptMap() {
    try {
      const outcome = await this.conceptLoader.load()
      this.conceptMap = outcome
      if (outcome.sectorToStocks.size > 0) {
        console.info(
          `[L1EventRealtimeBridge] 概念映射已加载: ${outcome.sectorToStocks.size} 个板块` +
          (outcome.stale ? '（本地缓存回退）' : '') || '',
        )
      }
    } catch (error) {
      console.warn('[L1EventRealtimeBridge] 概念映射加载失败:', error)
    }
  }

  private async loadStreaksOnce() {
    if (this.streaksLoaded) return
    this.streaksLoaded = true
    try {
      const result = await this.streakLoader.load()
      this.engine.setLimitUpStreaks(result.streaks)
      console.info(
        `[L1EventRealtimeBridge] 涨停池已加载: ${result.coveredDates.length} 个交易日，${result.streaks.size} 只昨日涨停` +
        (result.errors.length ? `，${result.errors.length} 条告警` : ''),
      )
    } catch (error) {
      console.warn('[L1EventRealtimeBridge] 涨停池加载失败:', error)
    }
  }

  private pruneHistory(history: L1QuoteSnapshot[], sourceTime: number) {
    const cutoff = sourceTime - HISTORY_WINDOW_MS
    while (history.length && history[0].sourceTime < cutoff) history.shift()
  }
}

function timestampOf(patch: QuotePatch, fallback: number): number {
  const bridge = patch.bridgeTs ? Date.parse(patch.bridgeTs) : Number.NaN
  if (Number.isFinite(bridge)) return bridge
  const captured = patch.capturedAt ? Date.parse(patch.capturedAt) : Number.NaN
  if (Number.isFinite(captured)) return captured
  return fallback
}

function normalizeDepth(value: unknown): Array<{ price: number; volume: number }> | undefined {
  if (!Array.isArray(value)) return undefined
  const levels = value
    .map(item => {
      const record = item as { price?: unknown; volume?: unknown }
      return { price: Number(record?.price) || 0, volume: Number(record?.volume) || 0 }
    })
    .filter(level => level.price > 0 && level.volume > 0)
  return levels.length ? levels : undefined
}

export function toAbnormalEvent(event: L1EventRecord, map: ConceptMapResult): HotStockAbnormalEvent {
  const isSector = event.sector.length > 0
  const numericType = L1_EVENT_TYPE_CODES[event.type]
  const identity = isSector ? event.sector : event.code
  return {
    category: isSector ? 'sector' : 'stock',
    id: `l1-${event.type}-${identity}-${event.timestamp}`,
    eventType: numericType as HotStockAbnormalEventType,
    type: numericType as HotStockAbnormalEventType,
    typeName: event.typeName,
    direction: DIRECTION_BY_TYPE[event.type] || 'neutral',
    severity: event.severity === 'critical' || event.severity === 'important' ? 'important' : 'normal',
    timestamp: event.timestamp,
    code: event.code,
    name: event.name,
    changePct: event.changePct / 100,
    price: event.price,
    relatedPlates: event.code ? sectorsOf(map, event.code) : [],
    sectorName: event.sector,
    matchedHotStock: false,
    matchedCandidate: false,
    raw: {
      l1: {
        type: event.type,
        typeName: event.typeName,
        severity: event.severity,
        reason: event.reason,
        memberCodes: event.memberCodes,
      },
    },
  }
}

// —— 语音两层设置的读取口（设置值由面板写入 localStorage）——
const VOICE_MODE_STORAGE_KEY = 'yidongjingling.voice-mode'
const VOICE_EVENTS_STORAGE_KEY = 'yidongjingling.voice-events'
const ENABLED_EVENTS_STORAGE_KEY = 'yidongjingling.enabled-events'

export function resolveVoiceMode(): VoiceMode {
  try {
    const raw = localStorage.getItem(VOICE_MODE_STORAGE_KEY)
    if (raw === 'all' || raw === 'muted' || raw === 'strongOnly') return raw
  } catch {
    // 无 localStorage 时默认播全部
  }
  return 'all'
}

export function resolveVoiceEvents(): Map<string, boolean> {
  return readBooleanMap(VOICE_EVENTS_STORAGE_KEY)
}

export function resolveEnabledEvents(): Map<string, boolean> {
  return readBooleanMap(ENABLED_EVENTS_STORAGE_KEY)
}

export function persistVoiceMode(mode: VoiceMode) {
  try {
    localStorage.setItem(VOICE_MODE_STORAGE_KEY, mode)
  } catch {
    // 持久化失败不阻塞
  }
}

export function persistVoiceEvents(events: Map<string, boolean>) {
  writeBooleanMap(VOICE_EVENTS_STORAGE_KEY, events)
}

export function persistEnabledEvents(events: Map<string, boolean>) {
  writeBooleanMap(ENABLED_EVENTS_STORAGE_KEY, events)
}

function readBooleanMap(key: string): Map<string, boolean> {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return new Map()
    const parsed = JSON.parse(raw) as Record<string, boolean>
    return new Map(Object.entries(parsed).map(([name, enabled]) => [name, Boolean(enabled)]))
  } catch {
    return new Map()
  }
}

function writeBooleanMap(key: string, events: Map<string, boolean>) {
  try {
    const payload: Record<string, boolean> = {}
    for (const [name, enabled] of events) payload[name] = enabled
    localStorage.setItem(key, JSON.stringify(payload))
  } catch {
    // 持久化失败不阻塞
  }
}

export { sectorsOf }

export const l1EventRealtimeBridge = new L1EventRealtimeBridge({
  monitorService: hotStockEventMonitorService,
  voiceSink: events => hotStockEventSpeechService.announceL1Events(events),
})
