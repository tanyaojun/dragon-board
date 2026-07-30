import { AppEvents } from '@/types'
import { normalizeStockCode } from '@/utils/common'
import { EventManager } from '@/utils/eventManager'

function defaultUrl(): string {
  const configured = (import.meta as any)?.env?.VITE_MARKET_FUND_WS_URL
  if (typeof configured === 'string' && configured.trim()) return configured.trim()
  return typeof window !== 'undefined' && window.location?.protocol === 'https:'
    ? 'wss://127.0.0.1:8000/api/market/fund-stream'
    : 'ws://127.0.0.1:8000/api/market/fund-stream'
}

export class MarketFundStreamService {
  private socket: WebSocket | null = null
  private codes: string[] = []
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private versions = new Map<string, number>()

  setSubscription(codes: string[]): void {
    this.codes = [...new Set(codes.map(normalizeStockCode).filter(Boolean))].sort()
    if (!this.codes.length) {
      this.disconnect()
      return
    }
    if (!this.socket || this.socket.readyState > WebSocket.OPEN) this.connect()
    else if (this.socket.readyState === WebSocket.OPEN) this.sendSubscription()
  }

  disconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    this.socket?.close()
    this.socket = null
  }

  private connect(): void {
    if (typeof window === 'undefined' || !this.codes.length) return
    this.socket = new WebSocket(defaultUrl())
    this.socket.addEventListener('open', () => this.sendSubscription())
    this.socket.addEventListener('message', event => {
      try {
        this.handlePayload(JSON.parse(String(event.data)))
      } catch {
        // Keep last-good rows when a frame is malformed.
      }
    })
    this.socket.addEventListener('close', () => {
      this.socket = null
      if (!this.codes.length || this.reconnectTimer) return
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null
        this.connect()
      }, 2000)
    })
  }

  private sendSubscription(): void {
    this.socket?.send(JSON.stringify({ codes: this.codes }))
  }

  private handlePayload(payload: any): void {
    if (!['fund_full_state', 'fund_patch'].includes(String(payload?.type))) return
    const rows = (Array.isArray(payload?.items) ? payload.items : [])
      .map((row: any) => this.normalizeRow(row))
      .filter(Boolean)
    if (!rows.length) return
    EventManager.emit(AppEvents.WEBSOCKET.QUOTE_PATCH, { items: rows, serverTs: Date.now(), intervalMs: 0 })
  }

  private normalizeRow(row: any): Record<string, unknown> | null {
    if (row?.moneyFlowSource !== 'ths_main_monitor') return null
    const code = normalizeStockCode(String(row?.code || ''))
    const version = Number(row?.version)
    const zlje = Number(row?.zlje)
    if (!code || !Number.isFinite(version) || !Number.isFinite(zlje)) return null
    if (version < (this.versions.get(code) || 0)) return null
    this.versions.set(code, version)
    return { ...row, code }
  }
}

export const marketFundStreamService = new MarketFundStreamService()
