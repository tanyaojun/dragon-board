import { createFeishuSignature } from './notifications.js'

const DEFAULT_COOLDOWN_MS = 600_000 // 10 分钟冷却，避免重复推送
const COOLDOWN_CLEANUP_INTERVAL_MS = 1_800_000 // 30 分钟清理一次过期冷却条目

export function registerJumpSignalRoutes(app, context = {}) {
  const readConfig = context.readConfig || (() => '')
  const fetcher = context.fetchImpl || globalThis.fetch?.bind(globalThis)
  const nowFn = context.now || Date.now
  const cooldownMap = new Map()

  // 定期清理过期冷却条目，防止内存泄漏
  const cleanupTimer = setInterval(() => {
    const cutoff = nowFn() - DEFAULT_COOLDOWN_MS * 2
    for (const [key, timestamp] of cooldownMap) {
      if (timestamp < cutoff) cooldownMap.delete(key)
    }
  }, COOLDOWN_CLEANUP_INTERVAL_MS)
  if (cleanupTimer.unref) cleanupTimer.unref()

  app.post('/api/notifications/jump-signal', async (req, res) => {
    const events = Array.isArray(req.body?.events) ? req.body.events : []
    if (!events.length) {
      res.status(400).json({ ok: false, message: 'jump signal events empty' })
      return
    }

    const enabled = readConfig('FEISHU_EVENT_RADAR_ENABLED')
    const webhook = readConfig('FEISHU_EVENT_RADAR_WEBHOOK')
    const secret = readConfig('FEISHU_EVENT_RADAR_SECRET')

    if (!enabled || enabled === '0' || enabled === 'false' || !webhook || !secret) {
      res.json({ ok: true, sent: 0, skipped: events.length, reason: 'feishu not configured' })
      return
    }

    const now = nowFn()
    const fresh = []
    for (const event of events) {
      const key = `${event.code || ''}:${event.signalType || ''}`
      const last = cooldownMap.get(key)
      if (last && now - last < DEFAULT_COOLDOWN_MS) continue
      cooldownMap.set(key, now)
      fresh.push(event)
    }

    if (!fresh.length) {
      res.json({ ok: true, sent: 0, skipped: events.length, reason: 'cooldown' })
      return
    }

    try {
      for (const event of fresh) {
        const text = formatJumpSignalMessage(event)
        await sendFeishuText(webhook, secret, text, fetcher, nowFn)
      }
      res.json({ ok: true, sent: fresh.length, skipped: events.length - fresh.length })
    } catch (error) {
      res.status(503).json({ ok: false, message: error.message || 'feishu send failed' })
    }
  })
}

function formatJumpSignalMessage(event) {
  const { code, name, signalType, price, changePct, reason, confidence } = event
  const label = signalType === 'entry' ? '▲ 入场' : '▼ 出场'
  const displayName = name || code || '--'
  const displayCode = code || '--'
  const displayPrice = Number(price) > 0 ? ` ¥${Number(price).toFixed(2)}` : ''
  const displayChange = Number(changePct) !== 0 ? ` ${Number(changePct) > 0 ? '+' : ''}${Number(changePct).toFixed(2)}%` : ''
  const displayConfidence = signalType === 'entry' && confidence != null ? ` 置信度${Number(confidence).toFixed(0)}%` : ''
  const displayReason = signalType === 'exit' && reason ? ` 原因：${reason}` : ''

  return `【RankTrend跳跃${label}】${displayName}(${displayCode})${displayPrice}${displayChange}${displayConfidence}${displayReason}`
}

async function sendFeishuText(webhook, secret, text, fetcher, nowFn) {
  const timestamp = Math.floor((nowFn || Date.now)() / 1000).toString()
  const response = await fetcher(webhook, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      timestamp,
      sign: createFeishuSignature(timestamp, secret),
      msg_type: 'text',
      content: {
        text: text.slice(0, 200),
      },
    }),
  })
  const body = await safeJson(response)
  if (!response.ok || (body && (body.code || body.StatusCode))) {
    throw new Error(body?.msg || body?.message || `feishu webhook failed: ${response.status}`)
  }
  return body || {}
}

async function safeJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}
