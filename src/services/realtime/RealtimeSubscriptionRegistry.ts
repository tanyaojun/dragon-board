import { webSocketService } from '../websocket'

export interface RealtimeSubscriptionRegistryOptions {
  apply: (codes: string[]) => void
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
  private readonly ownerCodes = new Map<string, string[]>()
  private readonly listeners = new Set<RealtimeSubscriptionListener>()
  private lastSignature = ''

  constructor(options: RealtimeSubscriptionRegistryOptions) {
    this.apply = options.apply
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

  getOwnerCodes(owner: string): string[] {
    return [...(this.ownerCodes.get(owner.trim()) || [])]
  }

  getMergedCodes(): string[] {
    return normalizeCodes([...this.ownerCodes.values()].flat())
  }

  subscribe(listener: RealtimeSubscriptionListener): () => void {
    this.listeners.add(listener)
    listener(this.getMergedCodes())
    return () => this.listeners.delete(listener)
  }

  private flush() {
    const codes = this.getMergedCodes()
    const signature = codes.join(',')
    if (signature === this.lastSignature) return
    this.lastSignature = signature
    this.apply(codes)
    this.listeners.forEach(listener => listener([...codes]))
  }
}

export const realtimeSubscriptionRegistry = new RealtimeSubscriptionRegistry({
  apply: codes => webSocketService.setHotPool(codes),
})
