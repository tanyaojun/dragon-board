import { webSocketService } from '../websocket'
import { themeFundStreamService } from '../themeFundStream'

export interface RealtimeSubscriptionRegistryOptions {
  apply: (codes: string[]) => void
  applyFunds?: (marketCodes: string[], priorityCodes: string[]) => void
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
  private readonly applyFunds: (marketCodes: string[], priorityCodes: string[]) => void
  private readonly ownerCodes = new Map<string, string[]>()
  private readonly fundOwnerCodes = new Map<string, string[]>()
  private readonly listeners = new Set<RealtimeSubscriptionListener>()
  private lastSignature = ''
  private lastFundSignature = ''

  constructor(options: RealtimeSubscriptionRegistryOptions) {
    this.apply = options.apply
    this.applyFunds = options.applyFunds || ((marketCodes) => options.apply(marketCodes))
  }

  setOwnerCodes(owner: string, codes: readonly unknown[]) {
    const key = owner.trim()
    if (!key) return
    this.ownerCodes.set(key, normalizeCodes(codes))
    this.flush()
  }

  clearOwner(owner: string) {
    if (!this.ownerCodes.delete(owner.trim())) return
    this.flush()
  }

  setFundOwnerCodes(owner: string, codes: readonly unknown[]) {
    const key = owner.trim()
    if (!key) return
    this.fundOwnerCodes.set(key, normalizeCodes(codes))
    this.flush()
  }

  clearFundOwner(owner: string) {
    if (!this.fundOwnerCodes.delete(owner.trim())) return
    this.flush()
  }

  getOwnerCodes(owner: string): string[] {
    return [...(this.ownerCodes.get(owner.trim()) || [])]
  }

  getMergedCodes(): string[] {
    return normalizeCodes([...this.ownerCodes.values()].flat())
  }

  getMergedFundCodes(): string[] {
    return normalizeCodes([
      ...this.ownerCodes.values(),
      ...this.fundOwnerCodes.values(),
    ].flat())
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
    const priorityCodes = normalizeCodes([...this.fundOwnerCodes.values()].flat())
    const fundSignature = `${signature}|${priorityCodes.join(',')}`
    if (fundSignature !== this.lastFundSignature) {
      this.lastFundSignature = fundSignature
      this.applyFunds(codes, priorityCodes)
    }
  }
}

export const realtimeSubscriptionRegistry = new RealtimeSubscriptionRegistry({
  apply: codes => {
    webSocketService.setHotPool(codes)
  },
  applyFunds: (marketCodes, priorityCodes) => {
    themeFundStreamService.setSubscription(marketCodes, priorityCodes)
  },
})
