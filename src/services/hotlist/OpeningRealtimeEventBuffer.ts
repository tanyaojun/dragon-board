import {
  OpeningAuctionStateStore,
  OpeningWeakToStrongDetector,
} from './OpeningWeakToStrongDetector'
import {
  OPENING_WEAK_TO_STRONG_EVENT_TYPE,
  type HotStockAbnormalEvent,
} from './hotStockEventTypes'
import type {
  OpeningWeakToStrongQuote,
  OpeningWeakToStrongRules,
  OpeningWeakToStrongSignal,
} from './openingWeakToStrongTypes'

export interface OpeningDerivedEvent {
  event: HotStockAbnormalEvent
  signal: OpeningWeakToStrongSignal
}

export interface OpeningRealtimeEventBufferOptions {
  rules: OpeningWeakToStrongRules
  ruleVersion: string
  now?: () => number
}

export class OpeningRealtimeEventBuffer {
  private readonly store: OpeningAuctionStateStore
  private readonly detector: OpeningWeakToStrongDetector
  private readonly emittedSignals = new Map<string, OpeningWeakToStrongSignal>()

  constructor(options: OpeningRealtimeEventBufferOptions) {
    this.store = new OpeningAuctionStateStore(options.rules)
    this.detector = new OpeningWeakToStrongDetector(options.rules, options.ruleVersion)
  }

  acceptQuote(quote: OpeningWeakToStrongQuote): HotStockAbnormalEvent[] {
    return this.acceptQuoteWithSignals(quote).map(item => item.event)
  }

  acceptQuoteWithSignals(quote: OpeningWeakToStrongQuote): OpeningDerivedEvent[] {
    this.store.capture(quote)
    const signal = this.detector.evaluate(quote, this.store.getBaseline(quote.code, quote.at))
    if (!signal?.triggered) return []

    const key = `${signal.ruleVersion}:${signal.code}:${tradingDate(signal.triggerAt)}`
    const previous = this.emittedSignals.get(key)
    const priorityDiff = previous ? compareSignalPriority(signal, previous) : 0
    if (previous && priorityDiff <= 0) {
      return []
    }
    this.emittedSignals.set(key, signal)

    return [{ event: toHotStockEvent(signal), signal }]
  }
}

function compareSignalPriority(left: OpeningWeakToStrongSignal, right: OpeningWeakToStrongSignal): number {
  return stagePriority(left) - stagePriority(right)
}

function stagePriority(signal: OpeningWeakToStrongSignal): number {
  switch (signal.stage) {
    case 'auctionConditionPassed':
    case 'auctionConditionFailed':
      return 1
    case 'gapAlert':
    case 'noGap':
      return 2
    case 'trendConfirm':
    case 'trendWeak':
      return 3
    case 'optionalFinalStatus':
      return 4
    default:
      return 0
  }
}

function toHotStockEvent(signal: OpeningWeakToStrongSignal): HotStockAbnormalEvent {
  const timestamp = Date.parse(signal.triggerAt)
  const stage = openingActionStage(signal)
  const id = `opening_weak_to_strong:${tradingDate(signal.triggerAt)}:${signal.code}:${stage}`
  const typeName = openingActionTypeName(stage)
  return {
    category: 'stock',
    id,
    eventType: OPENING_WEAK_TO_STRONG_EVENT_TYPE,
    type: OPENING_WEAK_TO_STRONG_EVENT_TYPE,
    typeName,
    direction: 'up',
    severity: 'important',
    timestamp: Number.isFinite(timestamp) ? timestamp : Date.now(),
    code: signal.code,
    name: signal.name,
    changePct: signal.firstWindowPct === undefined ? null : signal.firstWindowPct / 100,
    price: signal.firstWindowPrice ?? null,
    relatedPlates: [],
    sectorName: '',
    matchedHotStock: false,
    matchedCandidate: false,
    raw: {
      source: 'opening_weak_to_strong_v3',
      signal,
    },
  }
}

function openingActionStage(signal: OpeningWeakToStrongSignal): string {
  return signal.stage
}

function openingActionTypeName(stage: string): string {
  if (stage === 'auctionConditionPassed' || stage === 'auctionConditionFailed') {
    return '竞价弱转强候选'
  }
  if (stage === 'gapAlert') return '开盘承接转强'
  if (stage === 'trendConfirm') return '开盘反攻确认'
  if (stage === 'optionalFinalStatus') return '竞价弱转强复盘'
  return '竞价弱转强'
}

function tradingDate(timestamp: string): string {
  return timestamp.slice(0, 10)
}
