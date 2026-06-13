import { createFeishuSignature } from './notifications.js'

const DEFAULT_COOLDOWN_MS = 600_000 // 10 分钟冷却，避免重复推送
const COOLDOWN_CLEANUP_INTERVAL_MS = 1_800_000 // 30 分钟清理一次过期冷却条目
const MAX_TITLE_LENGTH = 80
const SIGNAL_LABELS = { entry: '排名趋势买入', exit: '排名趋势卖出' }

export function registerJumpSignalRoutes(app, context = {}) {
  const client = createJumpSignalNotifierClient(context)

  app.post('/api/notifications/jump-signal', async (req, res) => {
    const source = String(req.body?.source || '')
    const events = Array.isArray(req.body?.events) ? req.body.events : []
    if (!events.length) {
      res.status(400).json({ ok: false, message: 'jump signal events empty' })
      return
    }

    try {
      const result = await client.sendEvents(events, { source })
      res.json(result)
    } catch (error) {
      res.status(503).json({ ok: false, message: error.message || 'feishu send failed' })
    }
  })
}

export function createJumpSignalNotifierClient(options = {}) {
  const readConfig = options.readConfig || (() => '')
  const fetcher = options.fetcher || options.fetchImpl || globalThis.fetch?.bind(globalThis)
  const nowFn = options.now || Date.now
  const cooldownMap = new Map()

  const cleanupTimer = setInterval(() => {
    const cutoff = nowFn() - DEFAULT_COOLDOWN_MS * 2
    for (const [key, timestamp] of cooldownMap) {
      if (timestamp < cutoff) cooldownMap.delete(key)
    }
  }, COOLDOWN_CLEANUP_INTERVAL_MS)
  if (cleanupTimer.unref) cleanupTimer.unref()

  return {
    async sendEvents(events, options = {}) {
      const source = String(options.source || '')
      if (source === 'rank-trend-jump') {
        return { ok: true, sent: 0, skipped: events.length, reason: 'legacy-source-disabled' }
      }

      const enabled = readConfig('FEISHU_EVENT_RADAR_ENABLED')
      const webhook = readConfig('FEISHU_EVENT_RADAR_WEBHOOK')
      const secret = readConfig('FEISHU_EVENT_RADAR_SECRET')

      if (!enabled || enabled === '0' || enabled === 'false' || !webhook || !secret) {
        return { ok: true, sent: 0, skipped: events.length, reason: 'feishu not configured' }
      }

      if (!isShanghaiTradingTime(nowFn())) {
        return { ok: true, sent: 0, skipped: events.length, reason: 'outside-trading-time' }
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
        return { ok: true, sent: 0, skipped: events.length, reason: 'cooldown' }
      }

      const payload = formatJumpSignalEventRadarMessage(fresh, { now: nowFn })
      await sendFeishuPost(webhook, secret, payload, fetcher, nowFn)
      return { ok: true, sent: fresh.length, skipped: events.length - fresh.length }
    },
  }
}

/**
 * 按信号类型分组，生成飞书 post 格式消息，与异动雷达模板一致。
 *
 * 输出示例：
 * 【排名趋势买入】2条
 * 1. 福达合金 603045  +5.00%
 * 2. 淳中科技 603516  +3.00%
 *
 * 【排名趋势卖出】1条
 * 1. 福达合金 603045  +10.00%
 */
export function formatJumpSignalEventRadarMessage(events, options = {}) {
  const now = (options.now || Date.now)()
  const groups = new Map()

  for (const event of events) {
    const label = String(event.signalLabel || SIGNAL_LABELS[event.signalType] || event.signalType || '未知')
    const group = groups.get(label) || []
    group.push(event)
    groups.set(label, group)
  }

  const content = []
  let groupIndex = 0
  for (const [label, groupEvents] of groups) {
    if (groupIndex > 0) content.push([{ tag: 'text', text: '' }])
    content.push([{ tag: 'text', text: `【${label}】${groupEvents.length}条` }])
    groupEvents.forEach((event, i) => {
      const line = formatJumpLine(i + 1, event)
      content.push([{ tag: 'text', text: line }])
      for (const detail of formatCandidatePoolSummaryDetails(event)) {
        content.push([{ tag: 'text', text: detail }])
      }
      if (event.reason) {
        content.push([{ tag: 'text', text: `   原因：${String(event.reason).slice(0, 60)}` }])
      }
      for (const detail of formatCandidatePoolRuleDetails(event)) {
        content.push([{ tag: 'text', text: detail }])
      }
    })
    groupIndex++
  }

  return {
    msg_type: 'post',
    content: {
      post: {
        zh_cn: {
          title: `异动雷达 · ${formatTime(now)} · ${events.length}条`.slice(0, MAX_TITLE_LENGTH),
          content,
        },
      },
    },
  }
}

function formatCandidatePoolSummaryDetails(event) {
  const lines = []
  if (event.decisionLabel) {
    lines.push(`   入池判断：${String(event.decisionLabel)}`)
  }
  if (event.candidateTier) {
    lines.push(`   所处分层：${String(event.candidateTier)}`)
  }
  if (event.strategyState) {
    lines.push(`   策略状态：${formatCandidatePoolState(event.strategyState)}`)
  }
  if (event.lifecycleAction) {
    lines.push(`   生命周期：${String(event.lifecycleAction)}`)
  }
  if (event.decisionState) {
    lines.push(`   Live状态：${formatDecisionState(event.decisionState)}`)
  }
  if (event.decisionSummary) {
    lines.push(`   摘要：${String(event.decisionSummary).slice(0, 80)}`)
  }
  return lines
}

function formatCandidatePoolRuleDetails(event) {
  const lines = []
  const checks = Array.isArray(event.checks) ? event.checks : []
  if (checks.length) {
    lines.push('   规则矩阵关键项：')
    for (const check of checks.slice(0, 5)) {
      lines.push(
        `      ${check.label || check.key || '规则'}：${formatGateCheckStatus(check.status)} · 当前 ${formatValue(check.actual)} / 要求 ${formatValue(check.expected)}`,
      )
    }
  }
  if (event.source) {
    lines.push(`   来源：${String(event.source)}`)
  }
  return lines
}

function formatDecisionState(value) {
  if (value === 'auto_add') return '自动入池'
  if (value === 'watch_candidate') return '观察候选'
  if (value === 'blocked_candidate') return '被拒 / 阻断'
  if (value === 'not_candidate') return '未入池'
  return String(value || '未触发')
}

function formatCandidatePoolState(value) {
  if (value === 'idle') return '未触发'
  if (value === 'triggered_wait_entry') return '待入场'
  if (value === 'active_holding') return '策略持有中'
  if (value === 'exit_signaled') return '策略退出观察'
  if (value === 'closed') return '策略已关闭'
  return String(value || '未触发')
}

function formatGateCheckStatus(value) {
  if (value === 'pass') return '通过'
  if (value === 'warn') return '观察'
  if (value === 'fail') return '阻断'
  return '关闭'
}

function formatValue(value) {
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

function formatJumpLine(index, event) {
  const name = String(event.name || event.code || '--')
  const code = String(event.code || '--')
  const change = formatPct(Number(event.changePct))
  return `${index}. ${name} ${code}  ${change}`
}

function formatPct(value) {
  if (!Number.isFinite(value) || value === 0) return '0.00%'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

function formatTime(ts) {
  const d = new Date(ts)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${hh}:${mm}:${ss}`
}

async function sendFeishuPost(webhook, secret, payload, fetcher, nowFn) {
  const timestamp = Math.floor((nowFn || Date.now)() / 1000).toString()
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

function isShanghaiTradingTime(timestamp) {
  const date = new Date(timestamp)
  const dateKey = formatShanghaiDateKey(date)
  if (isShanghaiHoliday(dateKey)) return false
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date)
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  const weekday = byType.weekday
  if (weekday === 'Sat' || weekday === 'Sun') return false
  const minutes = Number(byType.hour || 0) * 60 + Number(byType.minute || 0)
  if (minutes >= 9 * 60 + 30 && minutes <= 11 * 60 + 30) return true
  if (minutes >= 13 * 60 && minutes <= 15 * 60) return true
  return false
}

function formatShanghaiDateKey(date) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date)
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${byType.year}-${byType.month}-${byType.day}`
}

function isShanghaiHoliday(dateKey) {
  return (
    (dateKey >= '2026-01-01' && dateKey <= '2026-01-03') ||
    (dateKey >= '2026-02-15' && dateKey <= '2026-02-23') ||
    (dateKey >= '2026-04-04' && dateKey <= '2026-04-06') ||
    (dateKey >= '2026-05-01' && dateKey <= '2026-05-05') ||
    (dateKey >= '2026-06-19' && dateKey <= '2026-06-21') ||
    (dateKey >= '2026-09-25' && dateKey <= '2026-09-27') ||
    (dateKey >= '2026-10-01' && dateKey <= '2026-10-07')
  )
}

export const __jumpSignalRouteInternals = {
  createJumpSignalNotifierClient,
  formatJumpSignalEventRadarMessage,
}
