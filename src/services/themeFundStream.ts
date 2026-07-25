import { AppEvents } from '@/types'
import { normalizeStockCode } from '@/utils/common'
import { EventManager } from '@/utils/eventManager'

type FundRow = {
  code?: unknown
  version?: unknown
  moneyFlowSource?: unknown
  [key: string]: unknown
}

function defaultUrl(): string {
  const configured = (import.meta as any)?.env?.VITE_THEME_FUND_WS_URL
  if (typeof configured === 'string' && configured.trim()) return configured.trim()
  return typeof window !== 'undefined' && window.location?.protocol === 'https:'
    ? 'wss://127.0.0.1:8000/api/themes/fund-stream'
    : 'ws://127.0.0.1:8000/api/themes/fund-stream'
}

export class ThemeFundStreamService {
  private socket: WebSocket | null = null
  private marketCodes: string[] = []
  private priorityCodes: string[] = []
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private versions = new Map<string, number>()

  setSubscription(marketCodes: string[], priorityCodes: string[]): void {
    this.marketCodes = [...new Set(marketCodes.map(normalizeStockCode).filter(Boolean))].sort()
    this.priorityCodes = [...new Set(priorityCodes.map(normalizeStockCode).filter(Boolean))].sort()
    if (!this.marketCodes.length && !this.priorityCodes.length) {
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
    if (typeof window === 'undefined' || (!this.marketCodes.length && !this.priorityCodes.length)) return
    this.socket = new WebSocket(defaultUrl())
    this.socket.addEventListener('open', () => this.sendSubscription())
    this.socket.addEventListener('message', event => {
      try {
        this.handlePayload(JSON.parse(String(event.data)))
      } catch {
        // Ignore malformed frames and keep the last-good rows.
      }
    })
    this.socket.addEventListener('close', () => {
      this.socket = null
      if ((!this.marketCodes.length && !this.priorityCodes.length) || this.reconnectTimer) return
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null
        this.connect()
      }, 2000)
    })
  }

  private sendSubscription(): void {
    this.socket?.send(JSON.stringify({
      marketCodes: this.marketCodes,
      priorityCodes: this.priorityCodes,
    }))
  }

  private handlePayload(payload: any): void {
    const type = String(payload?.type)
    if (!['fund_full_state', 'fund_patch'].includes(type)) return
    const rows = (Array.isArray(payload?.items) ? payload.items : [])
      .map((row: FundRow) => this.normalizeRow(row))
      .filter(Boolean)
    if (!rows.length) return
    EventManager.emit(AppEvents.WEBSOCKET.QUOTE_PATCH, {
      items: rows,
      serverTs: Date.now(),
      intervalMs: 0,
    })
  }

  private normalizeRow(row: FundRow): Record<string, unknown> | null {
    if (row?.moneyFlowSource !== 'ths_main_monitor') return null
    const code = normalizeStockCode(String(row.code || ''))
    const version = Number(row.version)
    if (!code || !Number.isFinite(version)) return null
    if (version < (this.versions.get(code) || 0)) return null
    this.versions.set(code, version)
    return { ...row, code }
  }
}

export const themeFundStreamService = new ThemeFundStreamService()
