import type { HotStockAbnormalEvent, HotStockEventFetcher } from './hotStockEventTypes'

function eventKey(event: HotStockAbnormalEvent): string {
  return `${event.category}:${event.type}:${event.code || event.sectorName}:${event.timestamp}`
}

export class CompositeHotStockEventFeed implements HotStockEventFetcher {
  constructor(private readonly feeds: HotStockEventFetcher[]) {}

  async fetchEvents(): Promise<HotStockAbnormalEvent[]> {
    const results = await Promise.allSettled(this.feeds.map(feed => feed.fetchEvents()))
    const events: HotStockAbnormalEvent[] = []
    const errors: unknown[] = []
    let successCount = 0

    for (const result of results) {
      if (result.status === 'fulfilled') {
        successCount += 1
        events.push(...result.value)
      } else {
        errors.push(result.reason)
      }
    }

    if (!successCount && errors.length) {
      throw errors[0]
    }

    const byKey = new Map<string, HotStockAbnormalEvent>()
    for (const event of events) {
      const key = eventKey(event)
      if (!byKey.has(key)) byKey.set(key, event)
    }

    return [...byKey.values()].sort((a, b) => b.timestamp - a.timestamp)
  }
}
