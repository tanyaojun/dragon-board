import crypto from 'node:crypto'

import { sendBadRequest } from '../helpers/response.js'

const DEFAULT_COOLDOWN_MS = 180_000
const DEFAULT_MAX_EVENTS = 5
const MAX_TITLE_LENGTH = 80
const MAX_TEXT_LENGTH = 120

export function registerNotificationRoutes(app, context = {}) {
  const client = context.feishuEventRadar || createFeishuEventRadarClient(context)

  app.get('/api/notifications/event-radar/status', (req, res) => {
    res.json({
      ok: true,
      source: 'event-radar-feishu',
      ...client.status(),
    })
  })

  app.post('/api/notifications/event-radar/test', async (req, res) => {
    try {
      const result = await client.sendText('异动雷达测试消息')
      res.json({
        ok: true,
        source: 'event-radar-feishu',
        ...result,
      })
    } catch (error) {
      res.status(503).json(buildNotificationError(error))
    }
  })

  app.post('/api/notifications/event-radar/events', async (req, res) => {
    const events = Array.isArray(req.body?.events) ? req.body.events : []
    if (!events.length) {
      sendBadRequest(res, 'event_radar_events_empty', 'event radar events are empty')
      return
    }

    try {
      const result = await client.sendEvents(events, {
        source: normalizeText(req.body?.source, 50) || 'hot-stock-event-radar',
      })
      res.json({
        ok: true,
        source: 'event-radar-feishu',
        ...result,
      })
    } catch (error) {
      res.status(503).json(buildNotificationError(error))
    }
  })
}

export function createFeishuEventRadarClient(options = {}) {
  const readConfig = options.readConfig || (() => '')
  const fetcher = options.fetcher || globalThis.fetch?.bind(globalThis)
  const now = options.now || Date.now
  const cooldownMap = new Map()

  function status() {
    const enabled = readBoolean(readConfig('FEISHU_EVENT_RADAR_ENABLED'))
    const webhookConfigured = Boolean(readConfig('FEISHU_EVENT_RADAR_WEBHOOK'))
    const secretConfigured = Boolean(readConfig('FEISHU_EVENT_RADAR_SECRET'))
    return {
      enabled,
      configured: enabled && webhookConfigured && secretConfigured,
      webhookConfigured,
      secretConfigured,
    }
  }

  function assertReady() {
    if (!fetcher) throw new Error('fetch is not available')
    const current = status()
    if (!current.enabled) throw new Error('FEISHU_EVENT_RADAR_ENABLED is not true')
    if (!current.webhookConfigured) throw new Error('FEISHU_EVENT_RADAR_WEBHOOK is not configured')
    if (!current.secretConfigured) throw new Error('FEISHU_EVENT_RADAR_SECRET is not configured')
  }

  async function sendPayload(payload) {
    assertReady()
    const webhook = readConfig('FEISHU_EVENT_RADAR_WEBHOOK')
    const secret = readConfig('FEISHU_EVENT_RADAR_SECRET')
    const timestamp = Math.floor(now() / 1000).toString()
    const response = await fetcher(webhook, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        timestamp,
        sign: createFeishuSignature(timestamp, secret),
        ...payload,
      }),
    })
    const body = await safeJson(response)
    if (!response.ok || isFeishuError(body)) {
      throw new Error(body?.msg || body?.message || `feishu webhook failed: ${response.status}`)
    }
    return body || {}
  }

  return {
    status,
    async sendText(text) {
      await sendPayload({
        msg_type: 'text',
        content: {
          text: normalizeText(text, MAX_TEXT_LENGTH) || '异动雷达测试消息',
        },
      })
      return { ok: true, sent: 1, skipped: 0 }
    },
    async sendEvents(events, options = {}) {
      const maxEvents = readPositiveInt(readConfig('FEISHU_EVENT_RADAR_MAX_EVENTS_PER_PUSH'), DEFAULT_MAX_EVENTS)
      const normalized = normalizeEventRadarEvents(events, maxEvents)
      const freshEvents = filterFreshEvents(normalized, cooldownMap, now(), readCooldownMs(readConfig))
      if (!freshEvents.length) {
        return { ok: true, sent: 0, skipped: normalized.length }
      }

      await sendPayload(formatEventRadarMessage(freshEvents, { ...options, now }))
      rememberEvents(freshEvents, cooldownMap, now())
      return { ok: true, sent: freshEvents.length, skipped: normalized.length - freshEvents.length }
    },
  }
}

export function createFeishuSignature(timestamp, secret) {
  const stringToSign = `${timestamp}\n${secret}`
  return crypto.createHmac('sha256', stringToSign).update('').digest('base64')
}

export function normalizeEventRadarEvents(events, limit = DEFAULT_MAX_EVENTS) {
  const byKey = new Map()
  for (const item of events) {
    if (!item || typeof item !== 'object') continue
    const code = normalizeStockCode(item.code)
    const typeName = normalizeText(item.typeName || item.eventType || item.type, 24)
    if (!code || !typeName) continue
    const timestamp = normalizeTimestamp(item.timestamp)
    const key = `${code}:${typeName}`
    const event = {
      id: normalizeText(item.id, 80) || `${key}:${timestamp}`,
      typeName,
      timestamp,
      code,
      name: normalizeText(item.name, 24) || code,
      changePct: normalizeFiniteNumber(item.changePct),
      price: normalizeFiniteNumber(item.price),
      relatedPlates: normalizePlateList(item.relatedPlates),
      matchedCandidate: Boolean(item.matchedCandidate),
    }
    const previous = byKey.get(key)
    if (!previous || event.timestamp > previous.timestamp) byKey.set(key, event)
  }

  return [...byKey.values()]
    .sort((a, b) => b.timestamp - a.timestamp)
    .slice(0, readPositiveInt(limit, DEFAULT_MAX_EVENTS))
}

export function formatEventRadarMessage(events, options = {}) {
  const now = options.now || Date.now
  const lines = normalizeEventRadarEvents(events, readPositiveInt(options.maxEvents, DEFAULT_MAX_EVENTS))
  const content = []

  for (const event of lines) {
    content.push([
      {
        tag: 'text',
        text: `${event.name} ${event.code} · ${event.typeName} · ${formatPct(event.changePct)}`,
      },
    ])
    if (event.relatedPlates.length) {
      content.push([
        {
          tag: 'text',
          text: `板块：${event.relatedPlates.join(' / ')}`,
        },
      ])
    }
    if (event.matchedCandidate) {
      content.push([{ tag: 'text', text: '标记：龙头复盘候选' }])
    }
  }

  return {
    msg_type: 'post',
    content: {
      post: {
        zh_cn: {
          title: normalizeText(`异动雷达 · ${formatTime(now())}`, MAX_TITLE_LENGTH),
          content,
        },
      },
    },
  }
}

function filterFreshEvents(events, cooldownMap, timestamp, cooldownMs) {
  return events.filter((event) => {
    const key = eventCooldownKey(event)
    const lastSentAt = cooldownMap.get(key)
    return !lastSentAt || timestamp - lastSentAt >= cooldownMs
  })
}

function rememberEvents(events, cooldownMap, timestamp) {
  for (const event of events) {
    cooldownMap.set(eventCooldownKey(event), timestamp)
  }
}

function eventCooldownKey(event) {
  return `${event.code}:${event.typeName}`
}

function readBoolean(value) {
  return ['1', 'true', 'yes', 'on'].includes(String(value || '').trim().toLowerCase())
}

function readPositiveInt(value, fallback) {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : fallback
}

function readCooldownMs(readConfig) {
  return readPositiveInt(readConfig('FEISHU_EVENT_RADAR_COOLDOWN_MS'), DEFAULT_COOLDOWN_MS)
}

function normalizeText(value, maxLength) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, maxLength)
}

function normalizeStockCode(value) {
  const code = String(value || '').replace(/\D/g, '')
  return /^\d{6}$/.test(code) ? code : ''
}

function normalizeTimestamp(value) {
  const timestamp = Number(value)
  return Number.isFinite(timestamp) && timestamp > 0 ? timestamp : Date.now()
}

function normalizeFiniteNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizePlateList(value) {
  if (!Array.isArray(value)) return []
  const seen = new Set()
  const result = []
  for (const item of value) {
    const text = normalizeText(item, 20)
    if (!text || seen.has(text)) continue
    seen.add(text)
    result.push(text)
    if (result.length >= 4) break
  }
  return result
}

function formatPct(value) {
  if (value === null || value === undefined) return '--'
  const pct = Math.abs(value) <= 1 ? value * 100 : value
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`
}

function formatTime(timestamp) {
  return new Date(timestamp).toLocaleTimeString('zh-CN', { hour12: false })
}

async function safeJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function isFeishuError(body) {
  if (!body || typeof body !== 'object') return false
  const statusCode = body.StatusCode ?? body.code
  return statusCode !== undefined && Number(statusCode) !== 0
}

function buildNotificationError(error) {
  return {
    ok: false,
    source: 'event-radar-feishu',
    errorCode: 'event_radar_feishu_unavailable',
    message: error?.message || 'event radar feishu notification failed',
  }
}

export const __notificationRouteInternals = {
  createFeishuEventRadarClient,
  createFeishuSignature,
  formatEventRadarMessage,
  normalizeEventRadarEvents,
}
