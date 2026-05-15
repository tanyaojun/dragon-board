import type { HotStockAbnormalEvent } from './hotStockEventTypes'

type SpeechFetcher = typeof fetch
type SpeechMode = 'local' | 'browser' | 'unsupported'

export interface HotStockEventSpeechServiceOptions {
  fetcher?: SpeechFetcher | null
  speechSynthesis?: SpeechSynthesis | null
  utteranceFactory?: (text: string) => SpeechSynthesisUtterance
  maxEventsPerSpeech?: number
  flushDelayMs?: number
}

export interface HotStockEventSpeechStatus {
  mode: SpeechMode
  supported: boolean
  queueLength: number
}

const TEST_TEXT = '热榜异动语音测试，当前语音提醒正常'
const LOCAL_TEST_TEXT = '热榜异动本地语音测试，当前语音提醒正常'
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
  private readonly speechSynthesis: SpeechSynthesis | null
  private readonly utteranceFactory: ((text: string) => SpeechSynthesisUtterance) | null
  private readonly maxEventsPerSpeech: number
  private readonly flushDelayMs: number
  private initialized = false
  private enabled = true
  private spokenIds = new Set<string>()
  private queue: string[] = []
  private speaking = false
  private pendingEvents: HotStockAbnormalEvent[] = []
  private flushTimer: ReturnType<typeof setTimeout> | null = null
  private status: HotStockEventSpeechStatus = {
    mode: 'unsupported',
    supported: false,
    queueLength: 0,
  }

  constructor(options: HotStockEventSpeechServiceOptions = {}) {
    this.fetcher = options.fetcher === undefined ? getBrowserFetcher() : options.fetcher
    this.speechSynthesis = options.speechSynthesis ?? getBrowserSpeechSynthesis()
    this.utteranceFactory = options.utteranceFactory ?? getBrowserUtteranceFactory()
    this.maxEventsPerSpeech = options.maxEventsPerSpeech ?? 3
    this.flushDelayMs = options.flushDelayMs ?? 3_000
    this.status = this.buildFallbackStatus()
  }

  isSupported(): boolean {
    return this.status.supported
  }

  getStatus(): HotStockEventSpeechStatus {
    return { ...this.status }
  }

  async refreshStatus(): Promise<HotStockEventSpeechStatus> {
    if (!this.fetcher) {
      this.status = this.buildFallbackStatus()
      return this.getStatus()
    }

    try {
      const response = await this.fetcher(LOCAL_STATUS_ENDPOINT)
      if (!response.ok) throw new Error(`local voice status failed: ${response.status}`)
      const payload = await response.json() as { supported?: boolean; queueLength?: number }
      if (payload.supported) {
        this.status = {
          mode: 'local',
          supported: true,
          queueLength: Number(payload.queueLength || 0),
        }
        return this.getStatus()
      }
    } catch {
      // Browser fallback is intentional when local proxy is offline.
    }

    this.status = this.buildFallbackStatus()
    return this.getStatus()
  }

  setEnabled(enabled: boolean) {
    this.enabled = enabled
    if (!enabled) this.stop()
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
    if (await this.tryLocalTest()) return
    this.enqueueBrowser(TEST_TEXT)
  }

  stop() {
    if (this.flushTimer) {
      clearTimeout(this.flushTimer)
      this.flushTimer = null
    }
    this.pendingEvents = []
    this.queue = []
    this.speaking = false
    this.speechSynthesis?.cancel()
  }

  private async flushPendingEvents() {
    const events = compactByStockPriority(this.pendingEvents)
    this.pendingEvents = []
    if (!events.length) return
    await this.speakText(buildSpeechText(events, this.maxEventsPerSpeech))
  }

  private async speakText(text: string) {
    if (!this.enabled || !text) return false
    if (await this.tryLocalSpeak(text)) return true
    return this.enqueueBrowser(text)
  }

  private async tryLocalSpeak(text: string): Promise<boolean> {
    if (!this.fetcher) return false
    try {
      const response = await this.fetcher(LOCAL_SPEAK_ENDPOINT, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      if (!response.ok) return false
      this.status = { ...this.status, mode: 'local', supported: true }
      return true
    } catch {
      return false
    }
  }

  private async tryLocalTest(): Promise<boolean> {
    if (!this.fetcher) return false
    try {
      const response = await this.fetcher(LOCAL_TEST_ENDPOINT, { method: 'POST' })
      if (!response.ok) return false
      this.status = { ...this.status, mode: 'local', supported: true }
      return true
    } catch {
      return false
    }
  }

  private enqueueBrowser(text: string) {
    if (!this.enabled || !this.isBrowserSupported() || !text) return false
    this.status = { mode: 'browser', supported: true, queueLength: this.queue.length + 1 }
    this.queue.push(text)
    this.speakNext()
    return true
  }

  private isBrowserSupported(): boolean {
    return Boolean(this.speechSynthesis && this.utteranceFactory)
  }

  private buildFallbackStatus(): HotStockEventSpeechStatus {
    if (this.isBrowserSupported()) {
      return { mode: 'browser', supported: true, queueLength: this.queue.length }
    }
    return { mode: 'unsupported', supported: false, queueLength: 0 }
  }

  private speakNext() {
    if (this.speaking) return
    const text = this.queue.shift()
    const utteranceFactory = this.utteranceFactory
    if (!text || !this.speechSynthesis || !utteranceFactory) return

    this.status = { mode: 'browser', supported: true, queueLength: this.queue.length + 1 }
    this.speaking = true
    const utterance = utteranceFactory(text)
    utterance.lang = 'zh-CN'
    utterance.rate = 1
    utterance.pitch = 1
    utterance.volume = 1
    const voice = this.speechSynthesis.getVoices().find((item) =>
      item.lang.includes('zh') || item.lang.includes('cmn'),
    )
    utterance.voice = voice || null
    utterance.onend = () => {
      this.speaking = false
      this.status = { mode: 'browser', supported: true, queueLength: this.queue.length }
      this.speakNext()
    }
    utterance.onerror = () => {
      this.speaking = false
      this.status = this.buildFallbackStatus()
      this.speakNext()
    }
    this.speechSynthesis.speak(utterance)
  }
}

function getBrowserFetcher(): SpeechFetcher | null {
  if (typeof globalThis.fetch !== 'function') return null
  return globalThis.fetch.bind(globalThis)
}

function getBrowserSpeechSynthesis(): SpeechSynthesis | null {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return null
  return window.speechSynthesis
}

function getBrowserUtteranceFactory(): ((text: string) => SpeechSynthesisUtterance) | null {
  if (typeof SpeechSynthesisUtterance === 'undefined') return null
  return (text: string) => new SpeechSynthesisUtterance(text)
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

export const hotStockEventSpeechService = new HotStockEventSpeechService()
