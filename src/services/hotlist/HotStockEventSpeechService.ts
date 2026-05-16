import type { HotStockAbnormalEvent } from './hotStockEventTypes'

type SpeechFetcher = typeof fetch
type SpeechMode = 'local' | 'offline'

export interface HotStockEventSpeechServiceOptions {
  fetcher?: SpeechFetcher | null
  maxEventsPerSpeech?: number
  flushDelayMs?: number
  rate?: number
  volume?: number
}

export interface HotStockEventSpeechStatus {
  mode: SpeechMode
  supported: boolean
  queueLength: number
  engine?: string
}

const LOCAL_SPEAK_ENDPOINT = '/api/local-voice/speak'
const LOCAL_TEST_ENDPOINT = '/api/local-voice/test'
const LOCAL_STATUS_ENDPOINT = '/api/local-voice/status'

const EVENT_PRIORITIES: Partial<Record<HotStockAbnormalEvent['type'], number>> = {
  10001: 100,
  10003: 95,
  10007: 90,
  10005: 80,
  10014: 75,
  10012: 70,
  10002: 65,
  10004: 60,
  10008: 55,
  10006: 50,
  10009: 40,
  10010: 35,
}

export class HotStockEventSpeechService {
  private readonly fetcher: SpeechFetcher | null
  private readonly maxEventsPerSpeech: number
  private readonly flushDelayMs: number
  private initialized = false
  private enabled = true
  private rate: number
  private volume: number
  private spokenIds = new Set<string>()
  private pendingEvents: HotStockAbnormalEvent[] = []
  private flushTimer: ReturnType<typeof setTimeout> | null = null
  private status: HotStockEventSpeechStatus = {
    mode: 'offline',
    supported: false,
    queueLength: 0,
  }

  constructor(options: HotStockEventSpeechServiceOptions = {}) {
    this.fetcher = options.fetcher === undefined ? getBrowserFetcher() : options.fetcher
    this.maxEventsPerSpeech = options.maxEventsPerSpeech ?? 3
    this.flushDelayMs = options.flushDelayMs ?? 3_000
    this.rate = normalizeRate(options.rate)
    this.volume = normalizeVolume(options.volume)
  }

  isSupported(): boolean {
    return this.status.supported
  }

  getStatus(): HotStockEventSpeechStatus {
    return { ...this.status }
  }

  async refreshStatus(): Promise<HotStockEventSpeechStatus> {
    if (!this.fetcher) {
      this.status = buildOfflineStatus()
      return this.getStatus()
    }

    try {
      const response = await this.fetcher(LOCAL_STATUS_ENDPOINT)
      if (!response.ok) throw new Error(`local voice status failed: ${response.status}`)
      const payload = await response.json() as {
        supported?: boolean
        queueLength?: number
        engine?: string
      }
      if (payload.supported) {
        this.status = {
          mode: 'local',
          supported: true,
          queueLength: Number(payload.queueLength || 0),
          engine: payload.engine || 'unknown',
        }
        return this.getStatus()
      }
    } catch {
      // VoiceWorker is the only speech path; keep offline when proxy or worker is unavailable.
    }

    this.status = buildOfflineStatus()
    return this.getStatus()
  }

  setEnabled(enabled: boolean) {
    this.enabled = enabled
    if (!enabled) this.stop()
  }

  setVoiceOptions(options: { rate?: number; volume?: number }) {
    if (options.rate !== undefined) this.rate = normalizeRate(options.rate)
    if (options.volume !== undefined) this.volume = normalizeVolume(options.volume)
  }

  getVoiceOptions() {
    return {
      rate: this.rate,
      volume: this.volume,
    }
  }

  isEnabled(): boolean {
    return this.enabled
  }

  async handleLatestAdded(events: HotStockAbnormalEvent[]) {
    if (!events.length) return

    if (!this.initialized) {
      events.forEach((event) => this.spokenIds.add(event.id))
      this.initialized = true
      return
    }

    const freshEvents = events.filter((event) => {
      if (this.spokenIds.has(event.id)) return false
      this.spokenIds.add(event.id)
      return true
    })
    if (!freshEvents.length) return

    this.pendingEvents.push(...freshEvents)
    if (this.flushDelayMs <= 0) {
      await this.flushPendingEvents()
      return
    }

    if (this.flushTimer) return
    this.flushTimer = setTimeout(() => {
      this.flushTimer = null
      void this.flushPendingEvents()
    }, this.flushDelayMs)
  }

  async speakTest() {
    if (!this.enabled) return
    await this.tryLocalTest()
  }

  stop() {
    if (this.flushTimer) {
      clearTimeout(this.flushTimer)
      this.flushTimer = null
    }
    this.pendingEvents = []
  }

  private async flushPendingEvents() {
    const events = compactByStockPriority(this.pendingEvents)
    this.pendingEvents = []
    if (!events.length) return
    await this.speakText(buildSpeechText(events, this.maxEventsPerSpeech))
  }

  private async speakText(text: string) {
    if (!this.enabled || !text) return false
    return this.tryLocalSpeak(text)
  }

  private async tryLocalSpeak(text: string): Promise<boolean> {
    if (!this.fetcher) return false
    try {
      const response = await this.fetcher(LOCAL_SPEAK_ENDPOINT, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text, rate: this.rate, volume: this.volume }),
      })
      if (!response.ok) return false
      this.status = { ...this.status, mode: 'local', supported: true }
      return true
    } catch {
      this.status = buildOfflineStatus()
      return false
    }
  }

  private async tryLocalTest(): Promise<boolean> {
    if (!this.fetcher) return false
    try {
      const response = await this.fetcher(LOCAL_TEST_ENDPOINT, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ rate: this.rate, volume: this.volume }),
      })
      if (!response.ok) return false
      this.status = { ...this.status, mode: 'local', supported: true }
      return true
    } catch {
      this.status = buildOfflineStatus()
      return false
    }
  }
}

function getBrowserFetcher(): SpeechFetcher | null {
  if (typeof globalThis.fetch !== 'function') return null
  return globalThis.fetch.bind(globalThis)
}

function buildSpeechText(events: HotStockAbnormalEvent[], maxEvents: number): string {
  const selected = events.slice(0, maxEvents)
  const phrases = selected.map((event) => `${event.name || event.code}${event.typeName}`)
  if (events.length === 1) {
    const event = events[0]
    return `热榜异动，${event.name || event.code}${event.typeName}，涨幅${formatPct(event.changePct)}`
  }
  return `新增${events.length}条热榜异动，${phrases.join('，')}`
}

function compactByStockPriority(events: HotStockAbnormalEvent[]): HotStockAbnormalEvent[] {
  const byCode = new Map<string, HotStockAbnormalEvent>()
  for (const event of events) {
    const key = event.code || event.id
    const previous = byCode.get(key)
    if (!previous || getEventPriority(event) > getEventPriority(previous)) {
      byCode.set(key, event)
    }
  }
  return [...byCode.values()].sort((a, b) => getEventPriority(b) - getEventPriority(a))
}

function getEventPriority(event: HotStockAbnormalEvent): number {
  return EVENT_PRIORITIES[event.type] ?? 0
}

function formatPct(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '未知'
  return `${value >= 0 ? '' : '负'}${Math.abs(value * 100).toFixed(2)}%`
}

function buildOfflineStatus(): HotStockEventSpeechStatus {
  return { mode: 'offline', supported: false, queueLength: 0 }
}

function normalizeRate(value: unknown): number {
  const rate = Number(value)
  if (!Number.isFinite(rate)) return 1
  return Math.round(Math.min(1.8, Math.max(0.6, rate)) * 100) / 100
}

function normalizeVolume(value: unknown): number {
  const volume = Number(value)
  if (!Number.isFinite(volume)) return 100
  return Math.round(Math.min(100, Math.max(0, volume)))
}

export const hotStockEventSpeechService = new HotStockEventSpeechService()
