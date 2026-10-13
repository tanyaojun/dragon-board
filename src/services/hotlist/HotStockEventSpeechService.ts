/**
 * 异动语音服务：与 tools/YiDongJingLing/Speech/SpeechAnnouncer.cs 语义一致（语音零丢失原则）。
 * - 每条事件独立成句（含完整细节），不合并播报、不同股压缩——用户裁决：丢龙头涨停信息不可接受；
 * - Critical 事件抢占：POST /stop 清空 VoiceWorker 队列后立即播报；
 * - 播报与停止经 gate 串行化，防止 /stop 清队后播报循环继续填队；
 * - 语音文本由 EventDeduper.buildSpeechItems 生成（与 C# BuildSpeechItems 逐字一致）。
 */
import { buildSpeechItems } from './EventDeduper'
import { OPENING_WEAK_TO_STRONG_EVENT_TYPE } from './hotStockEventTypes'
import type { HotStockAbnormalEvent } from './hotStockEventTypes'
import type { L1EventRecord } from './l1EventCatalog'

type SpeechFetcher = typeof fetch
type SpeechMode = 'local' | 'offline'

export interface HotStockEventSpeechServiceOptions {
  fetcher?: SpeechFetcher | null
  rate?: number
  volume?: number
  voice?: string
}

export interface HotStockEventSpeechStatus {
  mode: SpeechMode
  supported: boolean
  queueLength: number
  engine?: string
  voice?: string
  voices?: SapiVoiceOption[]
}

export interface SapiVoiceOption {
  name: string
  culture?: string
  gender?: string
}

const LOCAL_SPEAK_ENDPOINT = '/api/local-voice/speak'
const LOCAL_TEST_ENDPOINT = '/api/local-voice/test'
const LOCAL_STATUS_ENDPOINT = '/api/local-voice/status'
const LOCAL_STOP_ENDPOINT = '/api/local-voice/stop'

export class HotStockEventSpeechService {
  private readonly fetcher: SpeechFetcher | null
  private initialized = false
  private enabled = true
  private rate: number
  private volume: number
  private voice?: string
  private spokenKeys = new Set<string>()
  /** gate：串行化播报批次与停止/抢占，镜像 C# SemaphoreSlim(1,1)。 */
  private gate: Promise<unknown> = Promise.resolve()
  private status: HotStockEventSpeechStatus = {
    mode: 'offline',
    supported: false,
    queueLength: 0,
  }

  constructor(options: HotStockEventSpeechServiceOptions = {}) {
    this.fetcher = options.fetcher === undefined ? getBrowserFetcher() : options.fetcher
    this.rate = normalizeRate(options.rate)
    this.volume = normalizeVolume(options.volume)
    this.voice = normalizeVoice(options.voice)
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
        voice?: string
        voices?: SapiVoiceOption[]
      }
      if (payload.supported) {
        this.status = {
          mode: 'local',
          supported: true,
          queueLength: Number(payload.queueLength || 0),
          engine: payload.engine || 'unknown',
          voice: normalizeVoice(payload.voice),
          voices: normalizeVoices(payload.voices),
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
    if (!enabled) void this.stop()
  }

  setVoiceOptions(options: { rate?: number; volume?: number; voice?: string }) {
    if (options.rate !== undefined) this.rate = normalizeRate(options.rate)
    if (options.volume !== undefined) this.volume = normalizeVolume(options.volume)
    if (options.voice !== undefined) this.voice = normalizeVoice(options.voice)
  }

  getVoiceOptions() {
    return {
      rate: this.rate,
      volume: this.volume,
      voice: this.voice,
    }
  }

  isEnabled(): boolean {
    return this.enabled
  }

  /**
   * L1 事件语音入口（新）：接收已过 VoiceEvents/VoiceMode 过滤的本地事件，
   * Critical 抢占（stop→播报），普通批次按时间序逐条播报。
   */
  announceL1Events(events: readonly L1EventRecord[]) {
    if (!this.enabled || !events.length) return

    const freshEvents = events.filter(event => {
      const key = l1SpokenKey(event)
      if (this.spokenKeys.has(key)) return false
      this.spokenKeys.add(key)
      return true
    })
    if (!freshEvents.length) return
    if (!this.initialized) {
      // 首批只记录不播报（对齐 C# 面板启动后冷启动语义与旧行为）
      this.initialized = true
      return
    }

    this.enqueue(() => this.announceBatch(freshEvents))
  }

  /**
   * 旧入口兼容：接收 remote feed 事件（选股宝/同花顺）。同样零丢失逐条播报。
   * 事件需带 raw.l1（本地引擎事件走 announceL1Events）；远端事件按 名称+类型+涨幅 逐条成句。
   */
  async handleLatestAdded(events: HotStockAbnormalEvent[]) {
    if (!events.length) return

    const freshEvents = events.filter(event => {
      const key = `remote:${event.id}`
      if (this.spokenKeys.has(key)) return false
      this.spokenKeys.add(key)
      return true
    })
    if (!freshEvents.length) return
    if (!this.initialized) {
      this.initialized = true
      return
    }

    this.enqueue(() => this.announceRemoteBatch(freshEvents))
  }

  async speakTest() {
    if (!this.enabled) return
    await this.tryLocalTest()
  }

  async stop() {
    this.enqueue(async () => {
      await this.stopCore()
    })
  }

  /** 供测试/调用方等待在途批次播完。 */
  whenIdle(): Promise<unknown> {
    return this.gate
  }

  private enqueue(job: () => Promise<void>) {
    const run = this.gate.then(() => job()).catch((error) => {
      console.warn('[HotStockEventSpeechService] 播报批次失败:', error)
    })
    this.gate = run
    return run
  }

  private async announceBatch(events: readonly L1EventRecord[]) {
    const critical = events.filter(event => event.severity === 'critical')
    const rest = events
      .filter(event => event.severity !== 'critical')
      .sort((a, b) => a.timestamp - b.timestamp)

    if (critical.length) {
      // Critical 抢占：清空 VoiceWorker 队列后立即播报（gate 已持锁，串行化保证跨批次语义）
      await this.stopCore()
      for (const text of buildSpeechItems(critical)) {
        await this.speak(text)
      }
    }
    for (const text of buildSpeechItems(rest)) {
      await this.speak(text)
    }
  }

  private async announceRemoteBatch(events: readonly HotStockAbnormalEvent[]) {
    for (const event of [...events].sort((a, b) => a.timestamp - b.timestamp)) {
      await this.speak(buildRemoteSpeechText(event))
    }
  }

  private async speak(text: string) {
    if (!this.enabled || !text) return
    await this.tryLocalSpeak(text)
  }

  private async stopCore() {
    if (!this.fetcher) return
    try {
      await this.fetcher(LOCAL_STOP_ENDPOINT, { method: 'POST' })
    } catch {
      // worker 不可达时静默：下一次 speak 会走 EnsureWorker 路径
    }
  }

  private async tryLocalSpeak(text: string): Promise<boolean> {
    if (!this.fetcher) return false
    try {
      const response = await this.fetcher(LOCAL_SPEAK_ENDPOINT, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text, rate: this.rate, volume: this.volume, voice: this.voice }),
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
        body: JSON.stringify({ rate: this.rate, volume: this.volume, voice: this.voice }),
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

function l1SpokenKey(event: L1EventRecord): string {
  return `l1:${event.type}:${event.sector || event.code}:${event.timestamp}`
}

/**
 * 竞价弱转强语音门禁（保留既有语义）：只有 voiceEligible 且处于 gapAlert/trendConfirm
 * 阶段的事件可播；其余事件直接放行。
 */
export function isSpeechEligibleHotStockEvent(event: HotStockAbnormalEvent): boolean {
  if (event.type !== OPENING_WEAK_TO_STRONG_EVENT_TYPE) return true
  const raw = event.raw as {
    signal?: {
      stage?: string
      voiceEligible?: boolean
    }
  } | null
  const signal = raw?.signal
  return signal?.voiceEligible === true && (signal.stage === 'gapAlert' || signal.stage === 'trendConfirm')
}

/** 远端事件语音文本：与零丢失原则一致——每条独立成句，含涨幅细节。 */
export function buildRemoteSpeechText(event: HotStockAbnormalEvent): string {
  const displayName = event.name || event.code
  const pct = formatRemotePct(event.changePct)
  return pct ? `${displayName}，${event.typeName}，涨幅${pct}` : `${displayName}，${event.typeName}`
}

function formatRemotePct(value: number | null): string {
  // HotStockAbnormalEvent.changePct 全链路约定为比率（feed toRatio / 桥 toAbnormalEvent /100）
  // 恒 ×100，不做量纲启发式（≥100% 涨幅比率 1.2 会被误当百分数）
  if (value === null || !Number.isFinite(value)) return ''
  return `${trimZeros((value * 100).toFixed(2))}%`
}

function trimZeros(text: string): string {
  return text.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')
}

function getBrowserFetcher(): SpeechFetcher | null {
  if (typeof globalThis.fetch !== 'function') return null
  return globalThis.fetch.bind(globalThis)
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

function normalizeVoice(value: unknown): string | undefined {
  const voice = String(value || '').trim()
  return voice || undefined
}

function normalizeVoices(value: unknown): SapiVoiceOption[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => {
      if (!item || typeof item !== 'object') return null
      const voice = item as Partial<SapiVoiceOption>
      const name = normalizeVoice(voice.name)
      if (!name) return null
      const normalized: SapiVoiceOption = { name }
      const culture = normalizeVoice(voice.culture)
      const gender = normalizeVoice(voice.gender)
      if (culture) normalized.culture = culture
      if (gender) normalized.gender = gender
      return normalized
    })
    .filter((item): item is SapiVoiceOption => Boolean(item))
}

export function resolveSpeechVoiceSelection(
  currentVoice: string | undefined,
  statusVoice: string | undefined,
  voices: SapiVoiceOption[],
): string | undefined {
  const current = normalizeVoice(currentVoice)
  if (current && voices.some((voice) => voice.name === current)) return current

  const active = normalizeVoice(statusVoice)
  if (active && voices.some((voice) => voice.name === active)) return active

  return undefined
}

export const hotStockEventSpeechService = new HotStockEventSpeechService()
