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
    if (previous && compareSignalPriority(signal, previous) <= 0) return []
    this.emittedSignals.set(key, signal)

    return [{ event: toHotStockEvent(signal), signal }]
  }
}

function compareSignalPriority(left: OpeningWeakToStrongSignal, right: OpeningWeakToStrongSignal): number {
  const outcomeDiff = intradayOutcomePriority(left) - intradayOutcomePriority(right)
  if (outcomeDiff !== 0) return outcomeDiff

  const confidenceDiff = confidencePriority(left.confidence) - confidencePriority(right.confidence)
  if (confidenceDiff !== 0) return confidenceDiff
  return (left.score || 0) - (right.score || 0)
}

function intradayOutcomePriority(signal: OpeningWeakToStrongSignal): number {
  if (signal.intradayStatus === 'failed' || signal.intradayOutcome === 'failed_open_dump') return 4
  if (signal.intradayStatus === 'confirmed' || signal.intradayOutcome === 'confirmed_strong') return 3
  if (signal.intradayStatus === 'watch' || signal.intradayOutcome === 'watch_only') return 2
  if (signal.intradayStatus === 'pending' || signal.intradayOutcome === 'pending') return 1
  if (signal.intradayStatus === 'preopen_candidate' || signal.intradayOutcome === 'preopen_candidate') {
    return 0
  }
  return 0
}

function confidencePriority(value: OpeningWeakToStrongSignal['confidence']): number {
  if (value === 'critical') return 3
  if (value === 'strong') return 2
  if (value === 'watch') return 1
  return 0
}

function toHotStockEvent(signal: OpeningWeakToStrongSignal): HotStockAbnormalEvent {
  const timestamp = Date.parse(signal.triggerAt)
  const stage = openingActionStage(signal)
  const id = `opening_weak_to_strong:${tradingDate(signal.triggerAt)}:${signal.code}:${stage}`
  const typeName = stage === 'preopen_candidate' ? '竞价弱转强候选' : '竞价弱转强'
  return {
    category: 'stock',
    id,
    eventType: OPENING_WEAK_TO_STRONG_EVENT_TYPE,
    type: OPENING_WEAK_TO_STRONG_EVENT_TYPE,
    typeName,
    direction: 'up',
    severity: signal.confidence === 'watch' ? 'normal' : 'important',
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
  if (signal.intradayStatus === 'preopen_candidate' || signal.intradayOutcome === 'preopen_candidate') {
    return 'preopen_candidate'
  }
  if (signal.intradayStatus === 'confirmed' || signal.intradayOutcome === 'confirmed_strong') {
    return 'confirmed'
  }
  if (signal.intradayStatus === 'failed' || signal.intradayOutcome === 'failed_open_dump') {
    return 'failed'
  }
  if (signal.intradayStatus === 'watch' || signal.intradayOutcome === 'watch_only') {
    return 'watch'
  }
  return 'pending'
}

function tradingDate(timestamp: string): string {
  return timestamp.slice(0, 10)
}
