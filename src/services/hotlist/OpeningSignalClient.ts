import type { OpeningWeakToStrongSignal } from './openingWeakToStrongTypes'

export interface OpeningCanonicalSignal extends Partial<OpeningWeakToStrongSignal> {
  code: string
  signalType: 'opening_weak_to_strong'
  tradingDate?: string
  dryRun?: boolean
}

export interface OpeningSignalRecord {
  canonicalSignal: OpeningCanonicalSignal
  sources?: string[]
}

export interface OpeningSignalPostResponse {
  ok: boolean
  accepted?: boolean
  isNew?: boolean
  dedupeAction?: 'created' | 'merged' | 'upgraded' | 'cached'
  voiceOwner?: 'web' | 'desktop' | 'none'
  canonicalSignal?: OpeningCanonicalSignal
  sources?: string[]
}

type OpeningSignalFetcher = typeof fetch

export class OpeningSignalClient {
  private readonly fetcher: OpeningSignalFetcher

  constructor(options: { fetcher?: OpeningSignalFetcher } = {}) {
    this.fetcher = options.fetcher || getBrowserFetcher()
  }

  async fetchTodaySignals(tradingDate?: string): Promise<Map<string, OpeningCanonicalSignal>> {
    const query = tradingDate ? `?tradingDate=${encodeURIComponent(tradingDate)}` : ''
    const response = await this.fetcher(`/api/opening-signals/today${query}`)
    if (!response.ok) return new Map()

    const payload = await response.json() as { signals?: OpeningSignalRecord[] }
    const result = new Map<string, OpeningCanonicalSignal>()
    for (const item of Array.isArray(payload.signals) ? payload.signals : []) {
      const signal = item?.canonicalSignal
      if (signal?.signalType !== 'opening_weak_to_strong') continue
      if (signal.dryRun) continue
      if (/^\d{6}$/.test(signal.code)) result.set(signal.code, signal)
    }
    return result
  }

  async postSignal(
    source: 'web' | 'desktop',
    signal: OpeningCanonicalSignal,
  ): Promise<OpeningSignalPostResponse> {
    const response = await this.fetcher('/api/opening-signals', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ source, signal }),
    })
    if (!response.ok) {
      return { ok: false, accepted: false, voiceOwner: 'none' }
    }
    return await response.json() as OpeningSignalPostResponse
  }
}

export const openingSignalClient = new OpeningSignalClient()

function getBrowserFetcher(): OpeningSignalFetcher {
  if (typeof globalThis.fetch !== 'function') {
    return async () => new Response(null, { status: 503 })
  }
  return globalThis.fetch.bind(globalThis)
}
