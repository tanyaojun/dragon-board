import { AppEvents, type QuotePatch } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { hotStockEventMonitorService } from './HotStockEventMonitorService'
import { OpeningRealtimeEventBuffer, type OpeningDerivedEvent } from './OpeningRealtimeEventBuffer'
import { openingSignalClient, type OpeningCanonicalSignal } from './OpeningSignalClient'
import type {
  OpeningWeakToStrongQuote,
  OpeningWeakToStrongRules,
  OpeningWeakToStrongSignal,
} from './openingWeakToStrongTypes'
import {
  DEFAULT_OPENING_WEAK_TO_STRONG_RULES,
  OPENING_WEAK_TO_STRONG_RULE_VERSION,
} from './openingWeakToStrongConfig'

export interface OpeningRealtimeEventBridgeOptions {
  rules?: OpeningWeakToStrongRules
  ruleVersion?: string
  source?: 'web'
  signalClient?: typeof openingSignalClient
  monitorService?: typeof hotStockEventMonitorService
  buffer?: OpeningRealtimeEventBuffer
}

export class OpeningRealtimeEventBridge {
  private readonly buffer: OpeningRealtimeEventBuffer
  private readonly source: 'web'
  private readonly signalClient: typeof openingSignalClient
  private readonly monitorService: typeof hotStockEventMonitorService
  private unsubscribers: Array<() => void> = []
  private started = false

  constructor(options: OpeningRealtimeEventBridgeOptions = {}) {
    this.buffer = options.buffer || new OpeningRealtimeEventBuffer({
      rules: options.rules || DEFAULT_OPENING_WEAK_TO_STRONG_RULES,
      ruleVersion: options.ruleVersion || OPENING_WEAK_TO_STRONG_RULE_VERSION,
    })
    this.source = options.source || 'web'
    this.signalClient = options.signalClient || openingSignalClient
    this.monitorService = options.monitorService || hotStockEventMonitorService
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
    ]
  }

  stop() {
    this.unsubscribers.forEach(unsubscribe => unsubscribe())
    this.unsubscribers = []
    this.started = false
  }

  acceptQuotes(quotes: QuotePatch[]) {
    for (const quote of quotes) {
      const openingQuote = toOpeningQuote(quote)
      if (!openingQuote) continue
      const derived = this.buffer.acceptQuoteWithSignals(openingQuote)
      if (derived.length) void this.publishDerivedEvents(derived)
    }
  }

  private async publishDerivedEvents(derived: OpeningDerivedEvent[]) {
    const eventsToShow = []
    for (const item of derived) {
      const signal = toOpeningSignalPayload(item.signal)
      const response = await this.signalClient.postSignal(this.source, signal)
      const voiceOwner = resolveVoiceOwner(signal, response)
      eventsToShow.push({
        ...item.event,
        raw: {
          ...(typeof item.event.raw === 'object' && item.event.raw ? item.event.raw : {}),
          signal,
          openingSignalPost: response,
          voiceOwner,
        },
      })
    }

    this.monitorService.acceptDerivedEvents(eventsToShow)
    await this.monitorService.refresh()
  }
}

function toOpeningQuote(quote: QuotePatch): OpeningWeakToStrongQuote | null {
  if (!quote?.code) return null
  if (quote.lastPriceSource && quote.lastPriceSource !== 'last') return null
  const at = timestampFromQuote(quote)
  return {
    code: quote.code,
    name: quote.name,
    at,
    lastPrice: Number(quote.lastPrice) || 0,
    preClose: Number(quote.preClose) || 0,
    open: Number(quote.open) || 0,
    amount: Number(quote.amount) || 0,
    volume: Number(quote.volume) || 0,
    limitUpPrice: Number((quote as QuotePatch & { limitUpPrice?: number }).limitUpPrice) ||
      deriveLimitUpPrice(quote.code, quote.name, Number(quote.preClose) || 0),
    capturedAt: quote.capturedAt,
    bridgeTs: quote.bridgeTs,
    openingForcedSample: quote.openingForcedSample,
    requestedCount: quote.requestedCount,
    receivedCount: quote.receivedCount,
    elapsedMs: quote.elapsedMs,
    slowBatches: quote.slowBatches,
    truncatedBatches: quote.truncatedBatches,
    previousWeakScore: quote.previousWeakScore,
    previousWeakSignals: quote.previousWeakSignals,
    previousWeakSource: quote.previousWeakSource,
  }
}

function resolveVoiceOwner(
  signal: OpeningCanonicalSignal,
  response: { ok: boolean; voiceOwner?: 'web' | 'desktop' | 'none' },
): 'web' | 'desktop' | 'none' {
  if (signal.dryRun) return 'none'
  const owner = response.voiceOwner
  if (!response.ok) {
    return 'web'
  }
  if (owner) return owner
  return 'web'
}

function deriveLimitUpPrice(code: string, name: string | undefined, preClose: number): number | undefined {
  if (!Number.isFinite(preClose) || preClose <= 0) return undefined
  const limitPct = resolveLimitPct(code, name)
  return Math.round(preClose * (1 + limitPct / 100) * 100) / 100
}

function resolveLimitPct(code: string, name: string | undefined): number {
  if (String(name || '').toUpperCase().includes('ST')) return 5
  if (code.startsWith('30') || code.startsWith('68')) return 20
  if (code.startsWith('8') || code.startsWith('4')) return 30
  return 10
}

function timestampFromQuote(quote: QuotePatch): string {
  if (quote.bridgeTs) return quote.bridgeTs
  if (quote.capturedAt) return quote.capturedAt
  const timestamp = Number(quote.sourceTs)
  return Number.isFinite(timestamp) && timestamp > 0
    ? new Date(timestamp).toISOString()
    : new Date().toISOString()
}

function toOpeningSignalPayload(signal: OpeningWeakToStrongSignal): OpeningCanonicalSignal {
  return {
    ...signal,
    tradingDate: signal.triggerAt.slice(0, 10),
    triggerAt: signal.triggerAt,
    dryRun: signal.dryRun ?? false,
  }
}

export const openingRealtimeEventBridge = new OpeningRealtimeEventBridge()
