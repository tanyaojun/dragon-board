import { debugLog } from '@/utils/logger'
import type {
  Depth10Book,
  DepthLevel,
  QuotePatch,
  RealtimeStreamStatus,
  TickTrade,
} from '../types'
import { AppEvents } from '../types'
import { isTradingTime } from '../utils/time'
import { normalizeStockCode } from '../utils/common'
import { EventManager } from '../utils/eventManager'
import { refreshScheduler } from './refresh/RefreshTaskRuntime'

type QuotePayload = {
  type: string
  serverTs?: number
  subscribedCount?: number
  intervalMs?: number
  items?: any[]
}

type QuotePatchLike = Partial<QuotePatch> & { code: string }

type TickBatchPayload = {
  type: string
  serverTs?: number
  intervalMs?: number
  items?: any[]
}

type HeartbeatPayload = {
  type: string
  serverTs?: number
  subscribedCount?: number
  tdxConnected?: boolean
  intervalMs?: number
  tradingSession?: boolean
  l2?: any
}

type FullStateEventPayload = {
  quotes: QuotePatchLike[]
  depth: Depth10Book[]
  serverTs: number
  subscribedCount: number
}

type QuotePatchEventPayload = {
  items: QuotePatchLike[]
  serverTs: number
  intervalMs: number
}

type DepthPatchEventPayload = {
  items: Depth10Book[]
  serverTs: number
  intervalMs: number
}

type TickBatchEventPayload = {
  items: Array<{ code: string; items: TickTrade[] }>
  serverTs: number
  intervalMs: number
}

const HEARTBEAT_INTERVAL_HINT_MS = 5000
const TRADING_HEARTBEAT_INTERVAL_HINT_MS = 1000
const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000]
const RECONNECT_GRACE_MIN_MS = 8000
const WS_STATUS_DEBUG = (import.meta as any)?.env?.VITE_TDX_L2_WS_DEBUG === '1'
const MAX_TICKS_PER_CODE = 300
const MAX_TICK_AGE_MS = 60_000

function toNumber(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function toOptionalNumber(value: unknown): number | undefined {
  if (value === undefined || value === null || value === '') return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function toStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined
  const items = value
    .map(item => String(item || '').trim())
    .filter(Boolean)
  return items.length ? items : undefined
}

function buildDefaultUrl(): string {
  const envUrl = (import.meta as any)?.env?.VITE_TDX_L2_WS_URL
  if (typeof envUrl === 'string' && envUrl.trim()) return envUrl.trim()

  if (typeof window !== 'undefined' && window.location?.protocol === 'https:') {
    return 'wss://127.0.0.1:8765/ws/quotes'
  }

  return 'ws://127.0.0.1:8765/ws/quotes'
}

function normalizeDepthSide(items: any[]): DepthLevel[] {
  return (Array.isArray(items) ? items : [])
    .slice(0, 10)
    .map((level) => {
      if (Array.isArray(level)) {
        return {
          price: toNumber(level[0]),
          volume: toNumber(level[1]),
        }
      }

      return {
        price: toNumber(level?.price),
        volume: toNumber(level?.volume),
      }
    })
    .filter((level) => level.price > 0 || level.volume > 0)
}

function normalizeQuotePatch(item: any): QuotePatch | null {
  const code = normalizeStockCode(item?.code || item?.symbol)
  if (!code) return null

  const lastPrice = toNumber(item?.lastPrice ?? item?.price ?? item?.f2)
  const changePct = toNumber(item?.changePct ?? item?.change ?? item?.f3)
  const speed = toOptionalNumber(item?.speed ?? item?.riseSpeed ?? item?.speedPct)
  const amount = toNumber(item?.amount ?? item?.turnover ?? item?.f6)
  const volume = toNumber(item?.volume ?? item?.f5)
  const turnoverRate = toOptionalNumber(item?.turnoverRate ?? item?.f8)
  const tdxBuyVolume = toOptionalNumber(item?.tdxBuyVolume ?? item?.buyVolume ?? item?.bVol ?? item?.b_vol)
  const tdxSellVolume = toOptionalNumber(item?.tdxSellVolume ?? item?.sellVolume ?? item?.sVol ?? item?.s_vol)
  const tdxCurrentVolume = toOptionalNumber(item?.tdxCurrentVolume ?? item?.currentVolume ?? item?.curVol ?? item?.cur_vol)
  const zlje = toOptionalNumber(item?.zlje)
  const zljzb = toOptionalNumber(item?.zljzb)
  const cddje = toOptionalNumber(item?.cddje)
  const cddjzb = toOptionalNumber(item?.cddjzb)
  const previousWeakScore = toOptionalNumber(item?.previousWeakScore)
  const previousWeakSignals = toStringArray(item?.previousWeakSignals)
  const previousWeakSource = typeof item?.previousWeakSource === 'string'
    ? item.previousWeakSource.trim()
    : ''

  const patch: QuotePatch = {
    code,
    name: typeof item?.name === 'string' && item.name.trim() ? item.name.trim() : undefined,
    lastPrice,
    changePct,
    changeAmount: toNumber(item?.changeAmount),
    speed,
    volume,
    amount,
    turnoverRate,
    open: toNumber(item?.open),
    high: toNumber(item?.high),
    low: toNumber(item?.low),
    preClose: toNumber(item?.preClose),
    capturedAt: typeof item?.capturedAt === 'string' ? item.capturedAt : undefined,
    bridgeTs: typeof item?.bridgeTs === 'string' ? item.bridgeTs : undefined,
    lastPriceSource: typeof item?.lastPriceSource === 'string' ? item.lastPriceSource : undefined,
    sampleKind: typeof item?.sampleKind === 'string' ? item.sampleKind : undefined,
    openingForcedSample: item?.openingForcedSample === true,
    requestedCount: toOptionalNumber(item?.requestedCount),
    receivedCount: toOptionalNumber(item?.receivedCount),
    elapsedMs: toOptionalNumber(item?.elapsedMs),
    slowBatches: toOptionalNumber(item?.slowBatches),
    truncatedBatches: toOptionalNumber(item?.truncatedBatches),
    previousWeakScore,
    previousWeakSignals,
    previousWeakSource: previousWeakSource || undefined,
    sourceTs: toNumber(item?.sourceTs ?? item?.timestamp),
    seq: toNumber(item?.seq),
  }

  if (tdxBuyVolume !== undefined) patch.tdxBuyVolume = tdxBuyVolume
  if (tdxSellVolume !== undefined) patch.tdxSellVolume = tdxSellVolume
  if (tdxCurrentVolume !== undefined) patch.tdxCurrentVolume = tdxCurrentVolume
  if (zlje !== undefined) patch.zlje = zlje
  if (zljzb !== undefined) patch.zljzb = zljzb
  if (cddje !== undefined) patch.cddje = cddje
  if (cddjzb !== undefined) patch.cddjzb = cddjzb
  if (typeof item?.moneyFlowSource === 'string') patch.moneyFlowSource = item.moneyFlowSource
  if (typeof item?.moneyFlowEstimated === 'boolean') patch.moneyFlowEstimated = item.moneyFlowEstimated
  if (typeof item?.capitalFlowSource === 'string') patch.capitalFlowSource = item.capitalFlowSource
  if (typeof item?.capitalFlowConfidence === 'string') patch.capitalFlowConfidence = item.capitalFlowConfidence

  return patch
}

function normalizeDepth10Book(item: any): Depth10Book | null {
  const code = normalizeStockCode(item?.code || item?.symbol)
  if (!code) return null

  const bids = normalizeDepthSide(item?.bids)
  const asks = normalizeDepthSide(item?.asks)

  if (!bids.length && !asks.length) return null

  return {
    code,
    bids,
    asks,
    sourceTs: toNumber(item?.sourceTs ?? item?.timestamp),
    seq: toNumber(item?.seq),
    timestamp: Date.now(),
    provider: typeof item?.provider === 'string' ? item.provider : undefined,
    depthLevelCount: toNumber(item?.depthLevelCount),
  }
}

function normalizeTickTrade(code: string, item: any): TickTrade | null {
  if (!code) return null
  const normalizedCode = normalizeStockCode(code)
  if (!normalizedCode) return null
  const price = toNumber(item?.price)
  const volume = toNumber(item?.volume)
  const inferredAmount = price > 0 && volume > 0 ? price * volume * 100 : 0
  let amount = toNumber(item?.amount)
  if (inferredAmount > 0 && (amount <= 0 || amount < inferredAmount * 0.2)) {
    amount = inferredAmount
  }

  return {
    code: normalizedCode,
    price,
    volume,
    amount,
    side: item?.side === 'buy' || item?.side === 'sell' ? item.side : 'neutral',
    tradeTime: typeof item?.tradeTime === 'string' ? item.tradeTime : String(item?.ts || ''),
    sourceTs: toNumber(item?.sourceTs ?? item?.timestamp),
    timestamp: Date.now(),
    provider: typeof item?.provider === 'string' ? item.provider : undefined,
  }
}

class RealTimeWebSocketService {
  private socket: WebSocket | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private staleCheckRegistered = false
  private manuallyClosed = false
  private reconnectGraceUntil = 0
  private heartbeatIntervalHintMs = isTradingTime()
    ? TRADING_HEARTBEAT_INTERVAL_HINT_MS
    : HEARTBEAT_INTERVAL_HINT_MS
  private hotPoolCodes = new Set<string>()
  private latestQuotesByCode = new Map<string, QuotePatch>()
  private latestDepth10ByCode = new Map<string, Depth10Book>()
  private recentTicksByCode = new Map<string, TickTrade[]>()
  private state: RealtimeStreamStatus = {
    status: 'disconnected',
    subscribedCount: 0,
    lastMessageTime: null,
    lastHeartbeatTime: null,
    fallbackActive: false,
    tdxConnected: false,
    reconnectAttempts: 0,
    transport: 'idle',
    url: buildDefaultUrl(),
  }
  private lastStatusDebugSignature = ''

  constructor() {
    this.startStaleMonitor()
  }

  connect(): void {
    if (typeof window === 'undefined') return
    if (
      this.socket &&
      (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)
    ) {
      return
    }

    this.manuallyClosed = false
    const preserveRealtimePrimary = this.shouldPreserveRealtimePrimary()
    this.updateStatus({
      status: preserveRealtimePrimary ? 'connected' : this.state.fallbackActive ? 'fallback' : 'connecting',
      transport: preserveRealtimePrimary ? 'ws' : this.state.fallbackActive ? 'http' : 'ws',
      fallbackActive: preserveRealtimePrimary ? false : this.state.fallbackActive,
    })
    EventManager.emit(AppEvents.WEBSOCKET.STATUS_CHANGED, this.getStatus())

    try {
      this.socket = new WebSocket(this.state.url)
      this.socket.addEventListener('open', this.handleOpen)
      this.socket.addEventListener('message', this.handleMessage)
      this.socket.addEventListener('close', this.handleClose)
      this.socket.addEventListener('error', this.handleError)
    } catch (error) {
      console.error('[WebSocket] 连接创建失败:', error)
      this.scheduleReconnect()
    }
  }

  disconnect(): void {
    this.manuallyClosed = true
    this.clearReconnectGraceWindow()
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.teardownSocket()
    this.updateStatus({
      status: 'disconnected',
      transport: 'idle',
      fallbackActive: false,
    })
    EventManager.emit(AppEvents.WEBSOCKET.STATUS_CHANGED, this.getStatus())
  }

  setHotPool(codes: string[]): void {
    const normalized = new Set(codes.map((code) => normalizeStockCode(code)).filter(Boolean))
    this.hotPoolCodes = normalized

    this.updateStatus({ subscribedCount: normalized.size })
    EventManager.emit(AppEvents.WEBSOCKET.SUBSCRIPTION_UPDATED, Array.from(normalized))

    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      this.connect()
      return
    }

    this.sendHotPool()
  }

  getStatus(): RealtimeStreamStatus {
    return { ...this.state }
  }

  isConnected(): boolean {
    return this.state.status === 'connected'
  }

  hasFreshData(maxAgeMs?: number): boolean {
    const effectiveMaxAgeMs = maxAgeMs ?? this.connectionStaleThresholdMs()
    const lastActivityTime = Math.max(this.state.lastMessageTime || 0, this.state.lastHeartbeatTime || 0)
    return Boolean(lastActivityTime && Date.now() - lastActivityTime <= effectiveMaxAgeMs)
  }

  getSubscribedStocks(): string[] {
    return Array.from(this.hotPoolCodes)
  }

  getLastMessageTime(): number | null {
    return this.state.lastMessageTime
  }

  getLatestQuote(code: string): QuotePatch | null {
    return this.latestQuotesByCode.get(normalizeStockCode(code)) || null
  }

  getQuotesBatch(codes: string[]): Map<string, QuotePatch> {
    const result = new Map<string, QuotePatch>()
    codes.forEach((code) => {
      const normalizedCode = normalizeStockCode(code)
      const quote = this.latestQuotesByCode.get(normalizedCode)
      if (quote) result.set(normalizedCode, quote)
    })
    return result
  }

  getDepth10(code: string): Depth10Book | null {
    return this.latestDepth10ByCode.get(normalizeStockCode(code)) || null
  }

  getRecentTicks(code: string): TickTrade[] {
    const ticks = this.recentTicksByCode.get(normalizeStockCode(code))
    return Array.isArray(ticks) ? [...ticks] : []
  }

  private handleOpen = () => {
    this.clearReconnectGraceWindow()
    this.updateStatus({
      status: 'connected',
      fallbackActive: false,
      transport: 'ws',
      reconnectAttempts: 0,
    })

    this.sendHotPool()
    EventManager.emit(AppEvents.WEBSOCKET.STATUS_CHANGED, this.getStatus())
  }

  private handleMessage = (event: MessageEvent) => {
    const payload = this.parsePayload(event.data)
    if (!payload || typeof payload.type !== 'string') return

    this.clearReconnectGraceWindow()
    const serverTs = toNumber(payload.serverTs) || Date.now()
    this.updateStatus({
      lastMessageTime: Date.now(),
      transport: 'ws',
      status: 'connected',
    })

    switch (payload.type) {
      case 'full_state':
        this.handleFullState(payload as QuotePayload, serverTs)
        break
      case 'quote_patch':
        this.handleQuotePatch(payload as QuotePayload, serverTs)
        break
      case 'depth_patch':
        this.handleDepthPatch(payload as QuotePayload, serverTs)
        break
      case 'ticks_batch':
        this.handleTicksBatch(payload as TickBatchPayload, serverTs)
        break
      case 'money_flow_patch':
        // 资金字段只接受 QuantBoard 的统一资金流。
        break
      case 'l2_status':
        this.handleL2Status(payload as QuotePayload, serverTs)
        break
      case 'heartbeat':
        this.handleHeartbeat(payload as HeartbeatPayload, serverTs)
        break
      default:
        console.warn('[WebSocket] 未识别消息类型:', payload.type)
    }
  }

  private handleClose = () => {
    this.teardownSocket()
    if (this.manuallyClosed) return

    if (this.shouldPreserveRealtimePrimary()) {
      this.beginReconnectGraceWindow()
      this.updateStatus({
        status: 'connected',
        fallbackActive: false,
        transport: 'ws',
      })
    } else {
      this.updateStatus({
        status: 'fallback',
        fallbackActive: true,
        transport: 'http',
      })
    }
    EventManager.emit(AppEvents.WEBSOCKET.STATUS_CHANGED, this.getStatus())
    this.scheduleReconnect()
  }

  private handleError = () => {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.close()
      return
    }

    if (this.shouldPreserveRealtimePrimary()) {
      this.beginReconnectGraceWindow()
      this.updateStatus({
        status: 'connected',
        fallbackActive: false,
        transport: 'ws',
      })
    } else {
      this.updateStatus({
        status: 'fallback',
        fallbackActive: true,
        transport: 'http',
      })
    }
    EventManager.emit(AppEvents.WEBSOCKET.STATUS_CHANGED, this.getStatus())
    this.scheduleReconnect()
  }

  private handleFullState(payload: QuotePayload, serverTs: number) {
    const quoteSource = Array.isArray((payload as any).quotes)
      ? (payload as any).quotes
      : Array.isArray(payload.items)
        ? payload.items
        : []
    const depthSource = Array.isArray((payload as any).depth)
      ? (payload as any).depth
      : Array.isArray(payload.items)
        ? payload.items
        : []
    const quotes = quoteSource.map(normalizeQuotePatch).filter(Boolean) as QuotePatch[]
    const depth = depthSource.map(normalizeDepth10Book).filter(Boolean) as Depth10Book[]

    quotes.forEach((quote) => this.latestQuotesByCode.set(quote.code, quote))
    depth.forEach((book) => this.latestDepth10ByCode.set(book.code, book))

    this.updateStatus({
      subscribedCount: toNumber(payload.subscribedCount) || this.hotPoolCodes.size,
      tdxConnected: true,
      l2: this.normalizeL2Status((payload as any).l2) || this.state.l2,
    })

    const eventPayload: FullStateEventPayload = {
      quotes,
      depth,
      serverTs,
      subscribedCount: this.state.subscribedCount,
    }

    EventManager.emit(AppEvents.WEBSOCKET.FULL_STATE, eventPayload)
    EventManager.emit(AppEvents.WEBSOCKET.STATUS_CHANGED, this.getStatus())
  }

  private handleQuotePatch(payload: QuotePayload, serverTs: number) {
    const items = (Array.isArray(payload.items) ? payload.items : [])
      .map(normalizeQuotePatch)
      .filter(Boolean) as QuotePatch[]

    items.forEach((quote) => this.latestQuotesByCode.set(quote.code, quote))

    const eventPayload: QuotePatchEventPayload = {
      items,
      serverTs,
      intervalMs: toNumber(payload.intervalMs) || 100,
    }

    EventManager.emit(AppEvents.WEBSOCKET.QUOTE_PATCH, eventPayload)
  }

  private handleL2Status(payload: QuotePayload, serverTs: number) {
    void serverTs
    const l2 = this.normalizeL2Status((payload as any).l2 || payload)
    if (!l2) return
    this.updateStatus({ l2 })
    EventManager.emit(AppEvents.WEBSOCKET.STATUS_CHANGED, this.getStatus())
  }

  private handleDepthPatch(payload: QuotePayload, serverTs: number) {
    const items = (Array.isArray(payload.items) ? payload.items : [])
      .map(normalizeDepth10Book)
      .filter(Boolean) as Depth10Book[]

    items.forEach((book) => this.latestDepth10ByCode.set(book.code, book))

    const eventPayload: DepthPatchEventPayload = {
      items,
      serverTs,
      intervalMs: toNumber(payload.intervalMs) || 100,
    }

    EventManager.emit(AppEvents.WEBSOCKET.DEPTH_PATCH, eventPayload)
  }

  private handleTicksBatch(payload: TickBatchPayload, serverTs: number) {
    const normalizedItems: Array<{ code: string; items: TickTrade[] }> = []

    ;(Array.isArray(payload.items) ? payload.items : []).forEach((group: any) => {
      const code = normalizeStockCode(group?.code)
      if (!code) return

      const items = (Array.isArray(group?.items) ? group.items : [])
        .map((item: any) => normalizeTickTrade(code, item))
        .filter(Boolean) as TickTrade[]

      if (!items.length) return
      this.pushTicks(code, items)
      normalizedItems.push({ code, items })

      const latestTick = items[items.length - 1]
      if (latestTick) {
        EventManager.emit(AppEvents.WEBSOCKET.TICK, {
          code,
          price: latestTick.price,
          volume: latestTick.volume,
          amount: latestTick.amount,
          time: latestTick.tradeTime,
          side: latestTick.side,
        })
      }
    })

    const eventPayload: TickBatchEventPayload = {
      items: normalizedItems,
      serverTs,
      intervalMs: toNumber(payload.intervalMs) || 100,
    }

    EventManager.emit(AppEvents.WEBSOCKET.TICKS_BATCH, eventPayload)
  }

  private handleHeartbeat(payload: HeartbeatPayload, serverTs: number) {
    const intervalMs = toNumber(payload.intervalMs)
    if (intervalMs >= 250) {
      this.heartbeatIntervalHintMs = intervalMs
    }

    this.updateStatus({
      lastHeartbeatTime: Date.now(),
      subscribedCount: toNumber(payload.subscribedCount) || this.hotPoolCodes.size,
      tdxConnected: payload.tdxConnected !== false,
      fallbackActive: false,
      transport: 'ws',
      status: 'connected',
      l2: this.normalizeL2Status(payload.l2) || this.state.l2,
    })

    EventManager.emit(AppEvents.WEBSOCKET.HEARTBEAT, {
      serverTs,
      intervalMs: this.heartbeatIntervalHintMs,
      tradingSession: payload.tradingSession === true,
      subscribedCount: this.state.subscribedCount,
      tdxConnected: this.state.tdxConnected,
    })
    EventManager.emit(AppEvents.WEBSOCKET.STATUS_CHANGED, this.getStatus())
  }

  private connectionStaleThresholdMs(): number {
    return this.heartbeatIntervalHintMs * 2 + 1500
  }

  isPrimaryActive(): boolean {
    return !this.state.fallbackActive && (this.hasFreshData() || this.isReconnectGraceActive())
  }

  isTdxRealtimeHealthy(): boolean {
    return this.isPrimaryActive() && this.state.tdxConnected !== false
  }

  private shouldPreserveRealtimePrimary(): boolean {
    return this.isPrimaryActive()
  }

  private reconnectGraceWindowMs(): number {
    return Math.max(this.connectionStaleThresholdMs(), RECONNECT_GRACE_MIN_MS)
  }

  private beginReconnectGraceWindow() {
    this.reconnectGraceUntil = Math.max(this.reconnectGraceUntil, Date.now() + this.reconnectGraceWindowMs())
  }

  private clearReconnectGraceWindow() {
    this.reconnectGraceUntil = 0
  }

  private isReconnectGraceActive(): boolean {
    return this.reconnectGraceUntil > Date.now()
  }

  private pushTicks(code: string, ticks: TickTrade[]) {
    const existing = this.recentTicksByCode.get(code) || []
    const now = Date.now()
    const merged = existing
      .filter((item) => now - item.timestamp <= MAX_TICK_AGE_MS)
      .concat(ticks)
      .slice(-MAX_TICKS_PER_CODE)

    this.recentTicksByCode.set(code, merged)
  }

  private sendHotPool() {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return

    this.socket.send(
      JSON.stringify({
        type: 'set_hot_pool',
        codes: Array.from(this.hotPoolCodes),
      }),
    )
  }

  private updateStatus(patch: Partial<RealtimeStreamStatus>) {
    const previous = this.state
    this.state = {
      ...this.state,
      ...patch,
    }

    const signature = [
      this.state.status,
      this.state.transport,
      this.state.fallbackActive ? 'fallback' : 'primary',
      this.state.tdxConnected ? 'tdx' : 'notdx',
    ].join('|')

    if (WS_STATUS_DEBUG && signature !== this.lastStatusDebugSignature) {
      this.lastStatusDebugSignature = signature
      debugLog('[WebSocket] 状态切换:', {
        from: previous,
        to: this.state,
        heartbeatIntervalHintMs: this.heartbeatIntervalHintMs,
        now: new Date().toLocaleTimeString(),
      })
    }
  }

  private normalizeL2Status(value: any): RealtimeStreamStatus['l2'] | null {
    if (!value || typeof value !== 'object') return null
    return {
      provider: typeof value.provider === 'string' ? value.provider : undefined,
      enabled: typeof value.enabled === 'boolean' ? value.enabled : undefined,
      status: typeof value.status === 'string' ? value.status : undefined,
      message: typeof value.message === 'string' ? value.message : undefined,
      lastProbeTs: toOptionalNumber(value.lastProbeTs),
      lastDataTs: toOptionalNumber(value.lastDataTs),
      subscribedCount: toOptionalNumber(value.subscribedCount),
      depthLevelCount: toOptionalNumber(value.depthLevelCount),
      fallbackActive: typeof value.fallbackActive === 'boolean' ? value.fallbackActive : undefined,
    }
  }

  private scheduleReconnect() {
    if (this.manuallyClosed || this.reconnectTimer) return

    const attempt = Math.min(this.state.reconnectAttempts, RECONNECT_DELAYS_MS.length - 1)
    const delay = RECONNECT_DELAYS_MS[attempt]

    this.updateStatus({
      reconnectAttempts: this.state.reconnectAttempts + 1,
    })

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }

  private startStaleMonitor() {
    if (this.staleCheckRegistered) return
    refreshScheduler.registerRunner('websocket.staleCheck', () => this.runStaleCheck())
    refreshScheduler.startTask('websocket.staleCheck', 500)
    this.staleCheckRegistered = true
  }

  private stopStaleMonitor() {
    refreshScheduler.stopTask('websocket.staleCheck')
    this.staleCheckRegistered = false
  }

  private runStaleCheck() {
    if (this.state.status !== 'connected') return
    const lastActivityTime = Math.max(this.state.lastMessageTime || 0, this.state.lastHeartbeatTime || 0)
    if (!lastActivityTime) return

    const age = Date.now() - lastActivityTime
    if (age <= this.connectionStaleThresholdMs()) return
    if (this.isReconnectGraceActive()) return

    this.updateStatus({
      status: 'stale',
      fallbackActive: true,
      transport: 'http',
    })
    EventManager.emit(AppEvents.WEBSOCKET.STATUS_CHANGED, this.getStatus())

    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.close()
    }
  }

  private parsePayload(data: unknown): Record<string, unknown> | null {
    if (typeof data !== 'string') return null

    try {
      return JSON.parse(data) as Record<string, unknown>
    } catch (error) {
      console.warn('[WebSocket] 消息解析失败:', error)
      return null
    }
  }

  private teardownSocket() {
    if (!this.socket) return
    this.socket.removeEventListener('open', this.handleOpen)
    this.socket.removeEventListener('message', this.handleMessage)
    this.socket.removeEventListener('close', this.handleClose)
    this.socket.removeEventListener('error', this.handleError)
    try {
      this.socket.close()
    } catch {}
    this.socket = null
  }
}

export const webSocketService = new RealTimeWebSocketService()

if (typeof window !== 'undefined') {
  ;(window as any).webSocketService = webSocketService
}
