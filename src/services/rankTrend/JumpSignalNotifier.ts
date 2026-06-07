import { candidateJournalService } from '@/services/candidate/CandidateJournalService'
import { isTradingTime } from '@/utils/time'
import type { JumpSignalResult } from './jumpSignalService'

const FEISHU_ENDPOINT = '/api/notifications/jump-signal'
const NOTIFY_COOLDOWN_MS = 600_000 // 10 分钟冷却，同股票同信号类型不重复推送
const ASYNC_TIMEOUT_MS = 8000 // 异步操作超时，避免阻塞信号刷新

interface NotifyEvent {
  code: string
  name: string
  signalType: 'entry' | 'exit'
  price: number
  changePct: number
  reason: string
  confidence: number
  timestamp: number
}

/**
 * 跳跃信号通知器 —— 入场/出场时自动写入候选池并推送飞书消息。
 * 参考异动精灵的架构：前端检测信号 → proxy-server 负责飞书 webhook 签名和发送。
 *
 * 冷却只作用于飞书推送。候选池写入有自身的 findOpenCandidate 去重，不额外冷却。
 */
export class JumpSignalNotifier {
  private lastFeishuNotify = new Map<string, number>() // key: "code:signalType" -> timestamp

  /** 入场信号：自动加入候选池 + 飞书推送 */
  async notifyEntry(stock: Record<string, any>, result: JumpSignalResult): Promise<void> {
    const code = String(stock?.code || '')
    if (!code) return

    const price = Number(stock?.price || stock?.lastTradePrice || 0)
    const changePct = Number(stock?.change || 0)

    // 候选池写入：不设冷却，依赖 addCandidateFromStock 内置的 findOpenCandidate 去重
    this.safeAsync(async () => {
      try {
        await candidateJournalService.addCandidateFromStock(
          { ...stock, code },
          { addToFavorites: true, source: 'jump-signal' },
        )
      } catch (err) {
        console.warn('[JumpSignal] 候选池写入失败:', err instanceof Error ? err.message : String(err))
      }
    })

    this.sendFeishu({
      code,
      name: String(stock?.name || ''),
      signalType: 'entry',
      price,
      changePct,
      reason: '',
      confidence: Number(result?.jump?.confidence ?? 0),
      timestamp: Date.now(),
    })
  }

  /** 出场信号：更新候选池状态 + 飞书推送 */
  async notifyExit(stock: Record<string, any>, result: JumpSignalResult): Promise<void> {
    const code = String(stock?.code || '')
    if (!code) return

    const price = Number(stock?.price || stock?.lastTradePrice || 0)
    const changePct = Number(stock?.change || 0)
    const exitReason = result?.exitReason || ''

    // 候选池状态更新：不设冷却，依赖 getOpenCandidateForStock 查重
    this.safeAsync(async () => {
      try {
        const existing = await candidateJournalService.getOpenCandidateForStock(code)
        if (existing) {
          await candidateJournalService.saveCandidateReview(existing.id, {
            reviewOutcome: exitReason.includes('止盈') ? 'success' : 'failed',
            modelResult: 'unknown',
            executionResult: 'auto_exit',
            reviewNotes: `[自动出场] ${exitReason}`,
            exitPrice: price > 0 ? price : undefined,
            exitTime: new Date().toISOString(),
          })
        }
      } catch (err) {
        console.warn('[JumpSignal] 候选池状态更新失败:', err instanceof Error ? err.message : String(err))
      }
    })

    this.sendFeishu({
      code,
      name: String(stock?.name || ''),
      signalType: 'exit',
      price,
      changePct,
      reason: exitReason,
      confidence: 0,
      timestamp: Date.now(),
    })
  }

  private isCoolingDown(code: string, signalType: string): boolean {
    const key = `${code}:${signalType}`
    const last = this.lastFeishuNotify.get(key)
    return last != null && Date.now() - last < NOTIFY_COOLDOWN_MS
  }

  private markNotified(code: string, signalType: string): void {
    this.lastFeishuNotify.set(`${code}:${signalType}`, Date.now())
  }

  private sendFeishu(event: NotifyEvent): void {
    if (!isTradingTime()) return
    if (this.isCoolingDown(event.code, event.signalType)) return
    this.markNotified(event.code, event.signalType)
    if (typeof globalThis.fetch !== 'function') return

    globalThis.fetch(FEISHU_ENDPOINT, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ source: 'rank-trend-jump', events: [event] }),
      signal: AbortSignal.timeout(ASYNC_TIMEOUT_MS),
    }).catch((err) => {
      console.warn('[JumpSignal] 飞书推送失败:', err instanceof Error ? err.message : String(err))
    })
  }

  private safeAsync(fn: () => Promise<void>): void {
    fn().catch((err) => {
      console.warn('[JumpSignal] 异步操作异常:', err instanceof Error ? err.message : String(err))
    })
  }
}

export const jumpSignalNotifier = new JumpSignalNotifier()
