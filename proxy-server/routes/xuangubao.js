import { sendDegraded } from '../helpers/response.js'

const XUANGUBAO_EVENT_HOSTS = [
  'https://flash-api.xuangubao.com.cn/api/event/history',
  'https://flash-api.xuangubao.cn/api/event/history',
]

const DEFAULT_EVENT_TYPES = [
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
  11000,
  11001,
]

const EVENT_TYPE_SET = new Set(DEFAULT_EVENT_TYPES)
const DEFAULT_COUNT = 100
const MAX_COUNT = 200

function normalizeCount(value) {
  const count = Number.parseInt(String(value || ''), 10)
  if (!Number.isFinite(count) || count <= 0) return DEFAULT_COUNT
  return Math.min(count, MAX_COUNT)
}

function normalizeTypes(value) {
  const rawTypes = String(value || '')
    .split(',')
    .map((item) => Number.parseInt(item.trim(), 10))
    .filter((item) => Number.isFinite(item))

  const requestedTypes = rawTypes.filter((type) => EVENT_TYPE_SET.has(type))
  const types = requestedTypes.length ? requestedTypes : DEFAULT_EVENT_TYPES
  return Array.from(new Set(types))
}

function buildEventHistoryUrl(baseUrl, query) {
  const url = new URL(baseUrl)
  url.searchParams.set('count', String(normalizeCount(query.count)))
  url.searchParams.set('types', normalizeTypes(query.types).join(','))
  return url.toString()
}

function extractEvents(payload) {
  const source = payload?.data ?? payload
  const nestedEvents = [
    ...toArray(source?.stock_abnormal_event_data),
    ...toArray(source?.plate_abnormal_event_data),
    ...toArray(source?.stockAbnormalEventData),
    ...toArray(source?.plateAbnormalEventData),
  ]
  if (nestedEvents.length) return nestedEvents
  if (Array.isArray(source)) return source
  if (Array.isArray(source?.items)) return source.items
  if (Array.isArray(source?.list)) return source.list
  if (Array.isArray(source?.events)) return source.events
  if (Array.isArray(payload?.events)) return payload.events
  return []
}

function filterSupportedEvents(events) {
  return events.filter((event) => {
    const nested = event?.stock_abnormal_event_data
      || event?.plate_abnormal_event_data
      || event?.stockAbnormalEventData
      || event?.plateAbnormalEventData
      || {}
    const type = Number(event?.event_type ?? event?.eventType ?? event?.type
      ?? nested.event_type ?? nested.eventType ?? nested.type)
    return EVENT_TYPE_SET.has(type)
  })
}

function toArray(value) {
  return Array.isArray(value) ? value : []
}

export function registerXuangubaoRoutes(app, { plainClient }) {
  app.get('/api/xuangubao/events', async (req, res) => {
    let lastError = null

    for (const baseUrl of XUANGUBAO_EVENT_HOSTS) {
      try {
        const response = await plainClient.get(buildEventHistoryUrl(baseUrl, req.query), {
          timeout: 8000,
        })

        return res.json({
          ok: true,
          source: 'xuangubao-events',
          data: filterSupportedEvents(extractEvents(response.data)),
          upstreamCode: response.data?.code ?? response.status,
          timestamp: Date.now(),
        })
      } catch (error) {
        lastError = error
      }
    }

    return sendDegraded(res, {
      source: 'xuangubao-events',
      error: lastError || new Error('no xuangubao event source available'),
      fallbackData: [],
    })
  })
}
