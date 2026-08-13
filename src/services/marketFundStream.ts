import { FUND_SOURCE } from '@/config/fundSources'
import { AppEvents } from '@/types'
import { normalizeStockCode } from '@/utils/common'
import { EventManager } from '@/utils/eventManager'

/**
 * 行情主页主力资金流订阅（前端只消费）。
 *
 * 后端链路（quant-board）：
 *   akshare 同花顺个股资金流全市场批量抓取（单次约 5000+ 只）
 *     → MarketFundScheduler 周期刷新 + 启动预热（写入 Redis TTL，跨进程/跨重启共享）
 *     → ThemeFundCache（进程内 last-good 兜底）→ MarketFundStream（fund_full_state / fund_patch）
 *     → ws://127.0.0.1:8000/api/market/fund-stream
 *
 * 本服务只负责建立订阅并把增量行转成 QUOTE_PATCH 事件；数据获取与入库
 * 全部在后端完成。行字段合同：moneyFlowSource=ths_main_monitor、
 * zlje（主力净额，单位元）、version（单调递增）、tradingDate/sessionDate。
 */
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
  private priorityCodes: string[] = []
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectAttempts = 0
  private versions = new Map<string, number>()

  /**
   * 订阅展示池（codes）与 P0 可见行（priorityCodes，热榜排序前 N 只）。
   * priorityCodes 会随订阅消息上报，后端 ThsFundRefreshScheduler 据此做
   * P0/P1 分级刷新（P0 默认 30 秒优先校准）。
   */
  setSubscription(codes: string[], priorityCodes?: string[]): void {
    this.codes = [...new Set(codes.map(normalizeStockCode).filter(Boolean))].sort()
    this.priorityCodes = (priorityCodes || [])
      .map(normalizeStockCode)
      .filter((code): code is string => Boolean(code) && this.codes.includes(code))
      .slice(0, 100)
    if (!this.codes.length) {
      // P1-1（2026-08-11 审计）：空订阅（平台临时加载失败/热榜暂空）不主动断开——
      // 保留连接等待恢复；registry 层也会跳过空上报，避免清空后端订阅池。
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
    // P3-5（2026-08-11 审计）：清理旧的 CONNECTING 连接——若该连接永久挂起，
    // 新订阅永远不会发出（依赖 open 事件而 open 不会触发）
    if (this.socket && this.socket.readyState === WebSocket.CONNECTING) {
      try {
        this.socket.close()
      } catch {
        // ignore
      }
    }
    this.socket = new WebSocket(defaultUrl())
    this.socket.addEventListener('open', () => {
      this.reconnectAttempts = 0
      this.sendSubscription()
    })
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
      // P3-1（2026-08-11 审计）：指数退避重连（2s→4s→8s→10s 上限），
      // 避免后端长时间不可用时恒定 2s 空连
      const delay = Math.min(2000 * 2 ** this.reconnectAttempts, 10_000)
      this.reconnectAttempts += 1
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null
        this.connect()
      }, delay)
    })
  }

  private sendSubscription(): void {
    const message: Record<string, string[]> = { codes: this.codes }
    if (this.priorityCodes.length) message.priorityCodes = this.priorityCodes
    this.socket?.send(JSON.stringify(message))
  }

  private handlePayload(payload: any): void {
    if (!['fund_full_state', 'fund_patch'].includes(String(payload?.type))) return
    if (payload?.type === 'fund_full_state') {
      // 全量快照意味着服务端版本序列可能重置（Redis 清空/后端重启/数据源切换），
      // 清空本地版本记录——否则重置后的小 version 会被乱序保护永久丢弃，
      // 导致前端一直显示旧数据源（ths_main_monitor）的行
      this.versions.clear()
    }
    const rows = (Array.isArray(payload?.items) ? payload.items : [])
      .map((row: any) => this.normalizeRow(row))
      .filter(Boolean)
    if (!rows.length) return
    EventManager.emit(AppEvents.WEBSOCKET.QUOTE_PATCH, { items: rows, serverTs: Date.now(), intervalMs: 0 })
  }

  private normalizeRow(row: any): Record<string, unknown> | null {
    // 2026-08-12：接受 akshare 同花顺网页估算行（数据源已切换）与 THS L2 行；
    // 此前只收 ths_main_monitor 导致前端一直显示旧 L2 数据
    const source = String(row?.moneyFlowSource || '')
    if (source !== FUND_SOURCE.THS_MAIN_MONITOR && source !== FUND_SOURCE.AKSHARE_THS_INDIVIDUAL)
      return null
    const code = normalizeStockCode(String(row?.code || ''))
    const version = Number(row?.version)
    const zlje = Number(row?.zlje)
    if (!code || !Number.isFinite(version) || !Number.isFinite(zlje)) return null
    const prev = this.versions.get(code)
    if (prev !== undefined && version < prev) {
      // P2-2（2026-08-11 审计）：乱序/回退的旧版本直接丢弃，不覆盖新值
      // （服务端 version 重置由 fund_full_state 清空本地记录兜底）
      return null
    }
    if (prev === version) {
      // 重复推送：跳过，避免重复 QUOTE_PATCH / 量比刷新
      return null
    }
    this.versions.set(code, version)
    return { ...row, code }
  }
}

export const marketFundStreamService = new MarketFundStreamService()
