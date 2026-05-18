import type { HotStockAbnormalEvent } from '@/services/hotlist/hotStockEventTypes'

type NotifierFetcher = typeof fetch

export interface EventRadarFeishuStatus {
  enabled: boolean
  configured: boolean
  webhookConfigured: boolean
  secretConfigured: boolean
  batchWindowMs?: number
  pendingCount?: number
  background?: EventRadarFeishuBackgroundStatus | null
  lastMessage?: string
  lastCheckedAt?: number
}

export interface EventRadarFeishuBackgroundStatus {
  backgroundEnabled: boolean
  running: boolean
  initialized: boolean
  intervalMs: number
  lastRunAt: number | null
  lastSuccessAt: number | null
  lastError: string | null
  lastFetchedCount: number
  lastSentCount: number
  successCount: number
  failureCount: number
}

export interface EventRadarFeishuNotifierOptions {
  fetcher?: NotifierFetcher | null
}

const STATUS_ENDPOINT = '/api/notifications/event-radar/status'
const EVENTS_ENDPOINT = '/api/notifications/event-radar/events'
const TEST_ENDPOINT = '/api/notifications/event-radar/test'

export class EventRadarFeishuNotifier {
  private readonly fetcher: NotifierFetcher | null
  private status: EventRadarFeishuStatus = {
    enabled: false,
    configured: false,
    webhookConfigured: false,
    secretConfigured: false,
  }

  constructor(options: EventRadarFeishuNotifierOptions = {}) {
    this.fetcher = options.fetcher === undefined ? getBrowserFetcher() : options.fetcher
  }

  getStatus(): EventRadarFeishuStatus {
    return { ...this.status }
  }

  async refreshStatus(): Promise<EventRadarFeishuStatus> {
    if (!this.fetcher) {
      this.status = {
        enabled: false,
        configured: false,
        webhookConfigured: false,
        secretConfigured: false,
        background: null,
        lastMessage: '浏览器 fetch 不可用',
        lastCheckedAt: Date.now(),
      }
      return this.getStatus()
    }

    try {
      const response = await this.fetcher(STATUS_ENDPOINT)
      const payload = await response.json()
      if (!response.ok || payload?.ok === false) {
        throw new Error(payload?.message || `飞书推送状态检查失败: ${response.status}`)
      }
      this.status = normalizeStatus(payload)
    } catch (error) {
      this.status = {
        ...this.status,
        configured: false,
        lastMessage: error instanceof Error ? error.message : '飞书推送状态检查失败',
        lastCheckedAt: Date.now(),
      }
    }

    return this.getStatus()
  }

  async sendEvents(events: HotStockAbnormalEvent[]) {
    if (!events.length || !this.fetcher) return { ok: false, sent: 0, skipped: events.length }
    const status = this.status.configured ? this.status : await this.refreshStatus()
    if (!status.configured) return { ok: false, sent: 0, skipped: events.length }

    const response = await this.fetcher(EVENTS_ENDPOINT, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        source: 'hot-stock-event-radar',
        events: events.map(toPayloadEvent),
      }),
    })
    const payload = await response.json()
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message || `飞书推送失败: ${response.status}`)
    }
    this.status = {
      ...this.status,
      lastMessage: `已推送 ${Number(payload.sent || 0)} 条`,
      lastCheckedAt: Date.now(),
    }
    return payload
  }

  async sendTest() {
    if (!this.fetcher) throw new Error('浏览器 fetch 不可用')
    const response = await this.fetcher(TEST_ENDPOINT, { method: 'POST' })
    const payload = await response.json()
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message || `飞书测试推送失败: ${response.status}`)
    }
    this.status = {
      ...(await this.refreshStatus()),
      lastMessage: '测试消息已发送',
      lastCheckedAt: Date.now(),
    }
    return payload
  }
}

function getBrowserFetcher(): NotifierFetcher | null {
  if (typeof globalThis.fetch !== 'function') return null
  return globalThis.fetch.bind(globalThis)
}

function normalizeStatus(payload: Record<string, unknown>): EventRadarFeishuStatus {
  return {
    enabled: Boolean(payload.enabled),
    configured: Boolean(payload.configured),
    webhookConfigured: Boolean(payload.webhookConfigured),
    secretConfigured: Boolean(payload.secretConfigured),
    batchWindowMs: Number(payload.batchWindowMs) || 0,
    pendingCount: Number(payload.pendingCount) || 0,
    background: normalizeBackgroundStatus(payload.background),
    lastMessage: typeof payload.message === 'string' ? payload.message : undefined,
    lastCheckedAt: Date.now(),
  }
}

function normalizeBackgroundStatus(value: unknown): EventRadarFeishuBackgroundStatus | null {
  if (!value || typeof value !== 'object') return null
  const payload = value as Record<string, unknown>
  return {
    backgroundEnabled: Boolean(payload.backgroundEnabled),
    running: Boolean(payload.running),
    initialized: Boolean(payload.initialized),
    intervalMs: Number(payload.intervalMs) || 0,
    lastRunAt: normalizeNullableNumber(payload.lastRunAt),
    lastSuccessAt: normalizeNullableNumber(payload.lastSuccessAt),
    lastError: typeof payload.lastError === 'string' ? payload.lastError : null,
    lastFetchedCount: Number(payload.lastFetchedCount) || 0,
    lastSentCount: Number(payload.lastSentCount) || 0,
    successCount: Number(payload.successCount) || 0,
    failureCount: Number(payload.failureCount) || 0,
  }
}

function normalizeNullableNumber(value: unknown): number | null {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? number : null
}

function toPayloadEvent(event: HotStockAbnormalEvent) {
  return {
    id: event.id,
    typeName: event.typeName,
    timestamp: event.timestamp,
    code: event.code,
    name: event.name,
    changePct: event.changePct,
    price: event.price,
    relatedPlates: event.relatedPlates,
    matchedCandidate: event.matchedCandidate,
  }
}

export const eventRadarFeishuNotifier = new EventRadarFeishuNotifier()
