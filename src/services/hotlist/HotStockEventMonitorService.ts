import { dataLayer } from '../DataLayer'
import { refreshScheduler } from '../refresh/RefreshTaskRuntime'
import {
  XuangubaoAbnormalEventFeed,
} from './XuangubaoAbnormalEventFeed'
import {
  type HotStockAbnormalEvent,
  type HotStockEventDataLayer,
  type HotStockEventFetcher,
  type HotStockEventMonitorState,
  type HotStockEventRefreshResult,
  normalizeHotStockCode,
} from './hotStockEventTypes'

export interface HotStockEventMonitorOptions {
  feed?: HotStockEventFetcher
  dataLayer?: HotStockEventDataLayer
  intervalMs?: number
  maxEvents?: number
  now?: () => number
}

const DEFAULT_INTERVAL_MS = 30_000
const DEFAULT_MAX_EVENTS = 500

function isSameLocalDate(timestamp: number, now: number): boolean {
  const left = new Date(timestamp)
  const right = new Date(now)
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  )
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function collectCodes(value: unknown, codes: Set<string>) {
  if (!value) return
  if (Array.isArray(value)) {
    for (const item of value) collectCodes(item, codes)
    return
  }
  if (typeof value !== 'object') return

  const record = value as Record<string, unknown>
  const code = normalizeHotStockCode(record.code)
  if (code) codes.add(code)
}

function getCandidateCodes(review: ReturnType<HotStockEventDataLayer['getDragonReview']>): Set<string> {
  const codes = new Set<string>()
  if (!review) return codes

  const candidateReview = review as unknown as Record<string, unknown>
  collectCodes(candidateReview.candidates, codes)
  collectCodes(candidateReview.trueLeaders, codes)
  collectCodes(candidateReview.attentionBoard, codes)
  collectCodes(candidateReview.marketCore, codes)
  collectCodes(candidateReview.heightBoard, codes)

  return codes
}

function dedupeById(events: HotStockAbnormalEvent[]): HotStockAbnormalEvent[] {
  const byId = new Map<string, HotStockAbnormalEvent>()
  for (const event of events) {
    const previous = byId.get(event.id)
    if (!previous || event.timestamp > previous.timestamp) byId.set(event.id, event)
  }
  return [...byId.values()]
}

export class HotStockEventMonitorService {
  private feed: HotStockEventFetcher
  private readonly dataLayer: HotStockEventDataLayer
  private readonly intervalMs: number
  private readonly maxEvents: number
  private readonly now: () => number
  private running = false
  private events: HotStockAbnormalEvent[] = []
  private hotStockEvents: HotStockAbnormalEvent[] = []
  private otherStockEvents: HotStockAbnormalEvent[] = []
  private sectorEvents: HotStockAbnormalEvent[] = []
  private latestAdded: HotStockAbnormalEvent[] = []
  private latestHotStockAdded: HotStockAbnormalEvent[] = []
  private watchedCodes: string[] = []
  private lastUpdate: number | null = null
  private loading = false
  private error: string | null = null
  private subscribers = new Set<(state: HotStockEventMonitorState) => void>()

  constructor(options: HotStockEventMonitorOptions = {}) {
    this.feed = options.feed || new XuangubaoAbnormalEventFeed()
    this.dataLayer = options.dataLayer || dataLayer
    this.intervalMs = options.intervalMs || DEFAULT_INTERVAL_MS
    this.maxEvents = options.maxEvents || DEFAULT_MAX_EVENTS
    this.now = options.now || Date.now
  }

  setFeed(feed: HotStockEventFetcher) {
    this.feed = feed
  }

  getEvents(): HotStockAbnormalEvent[] {
    return [...this.events]
  }

  getState(): HotStockEventMonitorState {
    return {
      events: this.getEvents(),
      hotStockEvents: [...this.hotStockEvents],
      otherStockEvents: [...this.otherStockEvents],
      sectorEvents: [...this.sectorEvents],
      latestAdded: [...this.latestAdded],
      latestHotStockAdded: [...this.latestHotStockAdded],
      watchedCodes: [...this.watchedCodes],
      lastUpdate: this.lastUpdate,
      loading: this.loading,
      running: this.running,
      error: this.error,
    }
  }

  subscribe(callback: (state: HotStockEventMonitorState) => void): () => void {
    this.subscribers.add(callback)
    callback(this.getState())
    return () => this.subscribers.delete(callback)
  }

  async refresh(): Promise<HotStockEventRefreshResult> {
    const watchedCodes = this.getWatchedCodes()
    this.watchedCodes = watchedCodes
    this.loading = true
    this.error = null
    this.notify()

    try {
      const previousIds = new Set(this.events.map(event => event.id))
      const previousHotStockIds = new Set(this.hotStockEvents.map(event => event.id))
      const watchedCodeSet = new Set(watchedCodes)
      const candidateCodes = getCandidateCodes(this.dataLayer.getDragonReview())
      const today = this.now()
      const allTodayEvents = dedupeById(await this.feed.fetchEvents())
        .map(event => ({
          ...event,
          category: event.category || 'stock',
          code: event.category === 'sector' ? '' : normalizeHotStockCode(event.code),
        }))
        .filter(event => isSameLocalDate(event.timestamp, today))
        .map(event => ({
          ...event,
          matchedHotStock: event.category === 'stock' && watchedCodeSet.has(event.code),
          matchedCandidate: event.category === 'stock' && candidateCodes.has(event.code),
        }))
        .sort((a, b) => b.timestamp - a.timestamp)

      const nextHotStockEvents = allTodayEvents
        .filter(event => event.category === 'stock' && event.matchedHotStock)
        .slice(0, this.maxEvents)
      const nextOtherStockEvents = allTodayEvents
        .filter(event => event.category === 'stock' && !event.matchedHotStock)
        .slice(0, this.maxEvents)
      const nextSectorEvents = allTodayEvents
        .filter(event => event.category === 'sector')
        .slice(0, this.maxEvents)
      const nextEvents = [...allTodayEvents].slice(0, this.maxEvents)

      this.events = nextEvents
      this.hotStockEvents = nextHotStockEvents
      this.otherStockEvents = nextOtherStockEvents
      this.sectorEvents = nextSectorEvents
      this.latestAdded = nextEvents.filter(event => !previousIds.has(event.id))
      this.latestHotStockAdded = nextHotStockEvents.filter(event => !previousHotStockIds.has(event.id))
      this.lastUpdate = this.now()
      this.loading = false
      this.notify()

      return {
        ok: true,
        added: this.latestAdded.length,
        events: this.getEvents(),
        hotStockEvents: [...this.hotStockEvents],
        otherStockEvents: [...this.otherStockEvents],
        sectorEvents: [...this.sectorEvents],
        watchedCodes,
      }
    } catch (error) {
      this.error = getErrorMessage(error)
      this.loading = false
      this.notify()
      return {
        ok: false,
        added: 0,
        events: this.getEvents(),
        hotStockEvents: [...this.hotStockEvents],
        otherStockEvents: [...this.otherStockEvents],
        sectorEvents: [...this.sectorEvents],
        watchedCodes,
        error: this.error,
      }
    }
  }

  start() {
    if (this.running) return
    refreshScheduler.registerRunner('hotStockEvent.monitor', async () => {
      await this.refresh()
    })
    refreshScheduler.startTask('hotStockEvent.monitor', this.intervalMs)
    this.running = true
  }

  stop() {
    if (!this.running) return
    refreshScheduler.stopTask('hotStockEvent.monitor')
    this.running = false
    this.notify()
  }

  private getWatchedCodes(): string[] {
    const codes = new Set<string>()
    for (const stock of this.dataLayer.getStocks() || []) {
      const code = normalizeHotStockCode(stock?.code)
      if (code) codes.add(code)
    }
    return [...codes]
  }

  private notify() {
    const state = this.getState()
    this.subscribers.forEach((callback) => callback(state))
  }
}

export const hotStockEventMonitorService = new HotStockEventMonitorService()
