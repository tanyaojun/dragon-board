import type { HotStockAbnormalEvent } from './hotStockEventTypes'

export interface HotStockEventSpeechServiceOptions {
  speechSynthesis?: SpeechSynthesis | null
  utteranceFactory?: (text: string) => SpeechSynthesisUtterance
  maxEventsPerSpeech?: number
}

export class HotStockEventSpeechService {
  private readonly speechSynthesis: SpeechSynthesis | null
  private readonly utteranceFactory: ((text: string) => SpeechSynthesisUtterance) | null
  private readonly maxEventsPerSpeech: number
  private initialized = false
  private enabled = true
  private spokenIds = new Set<string>()
  private queue: string[] = []
  private speaking = false

  constructor(options: HotStockEventSpeechServiceOptions = {}) {
    this.speechSynthesis = options.speechSynthesis ?? getBrowserSpeechSynthesis()
    this.utteranceFactory = options.utteranceFactory ?? getBrowserUtteranceFactory()
    this.maxEventsPerSpeech = options.maxEventsPerSpeech ?? 3
  }

  isSupported(): boolean {
    return Boolean(this.speechSynthesis && this.utteranceFactory)
  }

  setEnabled(enabled: boolean) {
    this.enabled = enabled
    if (!enabled) this.stop()
  }

  isEnabled(): boolean {
    return this.enabled
  }

  handleLatestAdded(events: HotStockAbnormalEvent[]) {
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

    this.enqueue(buildSpeechText(freshEvents, this.maxEventsPerSpeech))
  }

  speakTest() {
    this.enqueue('热榜异动语音测试，当前语音提醒正常')
  }

  stop() {
    this.queue = []
    this.speaking = false
    this.speechSynthesis?.cancel()
  }

  private enqueue(text: string) {
    if (!this.enabled || !this.isSupported() || !text) return false
    this.queue.push(text)
    this.speakNext()
    return true
  }

  private speakNext() {
    if (this.speaking) return
    const text = this.queue.shift()
    const utteranceFactory = this.utteranceFactory
    if (!text || !this.speechSynthesis || !utteranceFactory) return

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
      this.speakNext()
    }
    utterance.onerror = () => {
      this.speaking = false
      this.speakNext()
    }
    this.speechSynthesis.speak(utterance)
  }
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

function formatPct(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '未知'
  return `${value >= 0 ? '' : '负'}${Math.abs(value * 100).toFixed(2)}%`
}

export const hotStockEventSpeechService = new HotStockEventSpeechService()
