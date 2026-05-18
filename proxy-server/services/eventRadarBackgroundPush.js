import { createFeishuEventRadarClient } from '../routes/notifications.js'

const DEFAULT_INTERVAL_MS = 30_000
const DEFAULT_COUNT = 100
const DEFAULT_TYPES = [
  10001,
  10005,
  10003,
  10007,
  10002,
  10006,
  10004,
  10008,
  10012,
  10014,
  10009,
  10010,
]

const EVENT_TYPE_NAMES = {
  10001: '封涨停板',
  10005: '逼近涨停',
  10003: '打开涨停板',
  10007: '即将打开涨停',
  10002: '封跌停板',
  10006: '逼近跌停',
  10004: '打开跌停板',
  10008: '即将打开跌停',
  10012: '新股开板',
  10014: '新股开板回封',
  10009: '大幅拉升',
  10010: '快速跳水',
}

export function createEventRadarBackgroundWorker(options = {}) {
  const readConfig = options.readConfig || (() => '')
  const notifier = options.notifier || createFeishuEventRadarClient({ readConfig })
  const fetchEvents = options.fetchEvents || createXuangubaoEventFetcher(options)
  const now = options.now || Date.now
  const setIntervalFn = options.setIntervalFn || setInterval
  const clearIntervalFn = options.clearIntervalFn || clearInterval

  let timer = null
  let running = false
  let initialized = false
  let inFlight = false
  let lastRunAt = null
  let lastSuccessAt = null
  let lastError = null
  let lastFetchedCount = 0
  let lastSentCount = 0
  let lastQueuedCount = 0
  let successCount = 0
  let failureCount = 0
  let knownEventKeys = new Set()

  function status() {
    const notifierStatus = notifier.status()
    return {
      ...notifierStatus,
      backgroundEnabled: notifierStatus.configured,
      running,
      initialized,
      intervalMs: readIntervalMs(readConfig),
      lastRunAt,
      lastSuccessAt,
      lastError,
      lastFetchedCount,
      lastSentCount,
      lastQueuedCount,
      successCount,
      failureCount,
    }
  }

  async function runOnce() {
    if (inFlight) return { ok: false, skipped: true, reason: 'in_flight', sent: 0 }
    inFlight = true
    lastRunAt = now()
    lastError = null

    try {
      const events = normalizeEvents(await fetchEvents())
      lastFetchedCount = events.length
      const nextKeys = new Set(events.map(eventKey))
      const freshEvents = events.filter((event) => !knownEventKeys.has(eventKey(event)))

      if (!initialized) {
        knownEventKeys = nextKeys
        initialized = true
        lastSentCount = 0
        lastSuccessAt = now()
        successCount += 1
        return { ok: true, baseline: true, fetched: events.length, sent: 0, skipped: events.length }
      }

      let queued = 0
      if (freshEvents.length) {
        const result = await notifier.sendEvents(freshEvents, { source: 'proxy-background-event-radar' })
        queued = Number(result?.queued || result?.sent || 0)
      }
      knownEventKeys = new Set([...knownEventKeys, ...nextKeys])
      lastQueuedCount = queued
      lastSuccessAt = now()
      successCount += 1
      return {
        ok: true,
        baseline: false,
        fetched: events.length,
        queued,
        sent: 0,
        skipped: events.length - freshEvents.length,
      }
    } catch (error) {
      lastError = error?.message || String(error)
      failureCount += 1
      return { ok: false, baseline: false, fetched: lastFetchedCount, sent: 0, error: lastError }
    } finally {
      inFlight = false
    }
  }

  function start() {
    if (running) return true
    if (!notifier.status().configured) return false
    running = true
    void runOnce()
    timer = setIntervalFn(() => {
      void runOnce()
    }, readIntervalMs(readConfig))
    return true
  }

  function stop() {
    if (!running) return
    if (timer !== null) clearIntervalFn(timer)
    timer = null
    running = false
  }

  return {
    runOnce,
    start,
    stop,
    status,
  }
}

function createXuangubaoEventFetcher(options) {
  const plainClient = options.plainClient || options.client
  if (!plainClient?.get) {
    return async () => []
  }
  return async () => {
    const url = new URL('https://flash-api.xuangubao.com.cn/api/event/history')
    url.searchParams.set('count', String(DEFAULT_COUNT))
    url.searchParams.set('types', DEFAULT_TYPES.join(','))
    const response = await plainClient.get(url.toString(), { timeout: 8000 })
    return extractRows(response.data)
  }
}

function extractRows(payload) {
  const source = payload?.data ?? payload
  const rows = [
    ...toArray(source?.stock_abnormal_event_data),
    ...toArray(source?.stockAbnormalEventData),
  ]
  if (rows.length) return rows
  if (Array.isArray(source)) return source
  if (Array.isArray(source?.items)) return source.items
  if (Array.isArray(source?.list)) return source.list
  if (Array.isArray(source?.events)) return source.events
  return []
}

function normalizeEvents(rows) {
  return rows
    .map(normalizeEvent)
    .filter(Boolean)
    .sort((a, b) => b.timestamp - a.timestamp)
}

function normalizeEvent(row) {
  const source = row?.stock_abnormal_event_data || row?.stockAbnormalEventData || row
  const type = Number(first(source, row, ['event_type', 'eventType', 'type']))
  const code = normalizeStockCode(first(source, row, ['stock_code', 'stockCode', 'code', 'symbol']))
  if (!DEFAULT_TYPES.includes(type) || !code) return null
  const timestamp = normalizeTimestamp(first(source, row, ['event_timestamp', 'created_at', 'timestamp', 'time']))
  return {
    id: normalizeText(first(source, row, ['id', 'event_id', 'eventId']), 80) || `${type}-${code}-${timestamp}`,
    typeName: normalizeText(first(source, row, ['event_type_name', 'type_name', 'typeName', 'title']), 24) || EVENT_TYPE_NAMES[type],
    timestamp,
    code,
    name: normalizeText(first(source, row, ['stock_name', 'stockName', 'name']), 24) || code,
    changePct: normalizePct(first(source, row, ['change_percent', 'change_pct', 'changePct', 'change', 'pcp'])),
    price: normalizeFiniteNumber(first(source, row, ['price', 'current_price', 'currentPrice', 'last', 'close'])),
    relatedPlates: normalizePlateList(first(source, row, ['related_plates', 'relatedPlates', 'plates'])),
    matchedCandidate: false,
  }
}

function eventKey(event) {
  return event.id || `${event.code}:${event.typeName}:${event.timestamp}`
}

function first(primary, fallback, keys) {
  for (const key of keys) {
    if (primary?.[key] !== undefined && primary[key] !== null) return primary[key]
    if (fallback?.[key] !== undefined && fallback[key] !== null) return fallback[key]
  }
  return undefined
}

function toArray(value) {
  return Array.isArray(value) ? value : []
}

function readIntervalMs(readConfig) {
  return readPositiveInt(readConfig('FEISHU_EVENT_RADAR_BACKGROUND_INTERVAL_MS'), DEFAULT_INTERVAL_MS)
}

function readPositiveInt(value, fallback) {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : fallback
}

function normalizeText(value, maxLength) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, maxLength)
}

function normalizeStockCode(value) {
  const code = String(value || '').replace(/\D/g, '')
  return /^\d{6}$/.test(code) ? code : ''
}

function normalizeTimestamp(value) {
  const number = Number(value)
  if (Number.isFinite(number) && number > 0) return number < 1_000_000_000_000 ? number * 1000 : number
  const parsed = Date.parse(String(value || ''))
  return Number.isFinite(parsed) ? parsed : Date.now()
}

function normalizeFiniteNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizePct(value) {
  const number = normalizeFiniteNumber(value)
  if (number === null) return null
  return Math.abs(number) > 1 ? number / 100 : number
}

function normalizePlateList(value) {
  if (!Array.isArray(value)) return []
  const result = []
  const seen = new Set()
  for (const item of value) {
    const text = normalizeText(
      typeof item === 'string' ? item : item?.plate_name || item?.plateName || item?.name,
      20,
    )
    if (!text || seen.has(text)) continue
    seen.add(text)
    result.push(text)
    if (result.length >= 4) break
  }
  return result
}
