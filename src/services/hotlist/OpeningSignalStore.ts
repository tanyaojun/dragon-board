import { readonly, ref } from 'vue'
import { openingSignalClient, type OpeningCanonicalSignal } from './OpeningSignalClient'

export class OpeningSignalStore {
  private readonly signalsByCodeRef = ref<Map<string, OpeningCanonicalSignal>>(new Map())
  private refreshTimer: ReturnType<typeof setInterval> | null = null

  constructor(
    private readonly options: {
      intervalMs?: number
      fetchTodaySignals?: typeof openingSignalClient.fetchTodaySignals
    } = {},
  ) {}

  get signalsByCode() {
    return readonly(this.signalsByCodeRef)
  }

  async refresh() {
    const fetchTodaySignals = this.options.fetchTodaySignals ||
      openingSignalClient.fetchTodaySignals.bind(openingSignalClient)
    this.signalsByCodeRef.value = await fetchTodaySignals()
  }

  start() {
    if (this.refreshTimer) return
    void this.refresh()
    this.refreshTimer = setInterval(() => {
      void this.refresh()
    }, this.options.intervalMs ?? 10_000)
  }

  stop() {
    if (!this.refreshTimer) return
    clearInterval(this.refreshTimer)
    this.refreshTimer = null
  }
}

export const openingSignalStore = new OpeningSignalStore()
