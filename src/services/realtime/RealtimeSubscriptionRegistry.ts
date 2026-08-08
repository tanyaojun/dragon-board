import { webSocketService } from '../websocket'
import { marketFundStreamService } from '../marketFundStream'

export interface RealtimeSubscriptionRegistryOptions {
  apply: (codes: string[]) => void
  applyMarketFunds?: (codes: string[], priorityCodes?: string[]) => void
}

export type RealtimeSubscriptionListener = (codes: string[]) => void

function normalizeRealtimeStockCode(value: unknown): string {
  const raw = String(value || '').trim().toUpperCase()
  if (!raw) return ''

  const withoutSuffix = raw.replace(/\.(?:SZ|SS|SH|BJ)$/i, '')
  const withoutPrefix = withoutSuffix.replace(/^(?:SZ|SS|SH|BJ)/i, '')
  const digits = withoutPrefix.replace(/\D/g, '')
  return /^\d{6}$/.test(digits) ? digits : ''
}

function normalizeCodes(codes: readonly unknown[]): string[] {
  return [...new Set(codes.map(normalizeRealtimeStockCode).filter(Boolean))].sort()
}

export class RealtimeSubscriptionRegistry {
  private readonly apply: (codes: string[]) => void
  private readonly applyMarketFunds: (codes: string[], priorityCodes?: string[]) => void
  private readonly ownerCodes = new Map<string, string[]>()
  private readonly ownerPriorityCodes = new Map<string, string[]>()
  private readonly listeners = new Set<RealtimeSubscriptionListener>()
  private lastSignature = ''
  private lastMarketFundSignature = ''
  private lastMarketFundPrioritySignature = ''

  constructor(options: RealtimeSubscriptionRegistryOptions) {
    this.apply = options.apply
    this.applyMarketFunds = options.applyMarketFunds || (() => undefined)
  }

  setOwnerCodes(owner: string, codes: readonly unknown[], priorityCodes?: readonly unknown[]) {
    const key = owner.trim()
    if (!key) return
    this.ownerCodes.set(key, normalizeCodes(codes))
    if (priorityCodes !== undefined) this.ownerPriorityCodes.set(key, normalizeCodes(priorityCodes))
    else this.ownerPriorityCodes.delete(key)
    this.flush()
  }

  clearOwner(owner: string) {
    const key = owner.trim()
    const removedCodes = this.ownerCodes.delete(key)
    const removedPriority = this.ownerPriorityCodes.delete(key)
    if (!removedCodes && !removedPriority) return
    this.flush()
  }

  getOwnerCodes(owner: string): string[] {
    return [...(this.ownerCodes.get(owner.trim()) || [])]
  }

  getOwnerPriorityCodes(owner: string): string[] {
    return [...(this.ownerPriorityCodes.get(owner.trim()) || [])]
  }

  getMergedCodes(): string[] {
    return normalizeCodes([...this.ownerCodes.values()].flat())
  }

  getMergedPriorityCodes(): string[] {
    return normalizeCodes([...this.ownerPriorityCodes.values()].flat())
  }

  subscribe(listener: RealtimeSubscriptionListener): () => void {
    this.listeners.add(listener)
    listener(this.getMergedCodes())
    return () => this.listeners.delete(listener)
  }

  private flush() {
    const codes = this.getMergedCodes()
    const signature = codes.join(',')
    if (signature !== this.lastSignature) {
      this.lastSignature = signature
      this.apply(codes)
      this.listeners.forEach(listener => listener([...codes]))
    }
    const marketFundCodes = this.getOwnerCodes('dataLoader.hotlist')
    const marketFundPriority = this.getOwnerPriorityCodes('dataLoader.hotlist')
    const marketFundSignature = marketFundCodes.join(',')
    const marketFundPrioritySignature = marketFundPriority.join(',')
    if (
      marketFundSignature !== this.lastMarketFundSignature ||
      marketFundPrioritySignature !== this.lastMarketFundPrioritySignature
    ) {
      this.lastMarketFundSignature = marketFundSignature
      this.lastMarketFundPrioritySignature = marketFundPrioritySignature
      this.applyMarketFunds(marketFundCodes, marketFundPriority)
    }
  }
}

export const realtimeSubscriptionRegistry = new RealtimeSubscriptionRegistry({
  apply: codes => {
    webSocketService.setHotPool(codes)
  },
  applyMarketFunds: (codes, priorityCodes) =>
    marketFundStreamService.setSubscription(codes, priorityCodes),
})
