import assert from 'node:assert/strict'

import { __notificationRouteInternals } from './notifications.js'

const {
  createFeishuEventRadarClient,
  formatEventRadarMessage,
  normalizeEventRadarEvents,
} = __notificationRouteInternals

const event = {
  id: '10001-600386-20260518102314',
  typeName: '封涨停板',
  timestamp: Date.parse('2026-05-18T10:23:14+08:00'),
  code: '600386',
  name: '北巴传媒',
  changePct: 0.101,
  price: 4.36,
  relatedPlates: ['广告传媒', '北京国资', '汽车服务'],
  matchedCandidate: true,
}

const normalized = normalizeEventRadarEvents([event, { ...event, id: 'dup' }], 5)
assert.equal(normalized.length, 1)
assert.equal(normalized[0].code, '600386')
assert.equal(normalized[0].changePct, 0.101)

const message = formatEventRadarMessage(normalized, {
  source: 'hot-stock-event-radar',
  now: () => Date.parse('2026-05-18T10:24:00+08:00'),
})
assert.equal(message.msg_type, 'post')
assert.equal(message.content.post.zh_cn.title, '异动雷达 · 10:24:00')
assert.deepEqual(message.content.post.zh_cn.content[0].map((part) => part.text).join(''), '北巴传媒 600386 · 封涨停板 · +10.10%')
assert.deepEqual(message.content.post.zh_cn.content[1].map((part) => part.text).join(''), '板块：广告传媒 / 北京国资 / 汽车服务')

const calls = []
const client = createFeishuEventRadarClient({
  readConfig: (name) => ({
    FEISHU_EVENT_RADAR_ENABLED: 'true',
    FEISHU_EVENT_RADAR_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/test',
    FEISHU_EVENT_RADAR_SECRET: 'secret',
    FEISHU_EVENT_RADAR_COOLDOWN_MS: '180000',
  })[name] || '',
  fetcher: async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) })
    return {
      ok: true,
      status: 200,
      json: async () => ({ StatusCode: 0, msg: 'ok' }),
    }
  },
  now: () => Date.parse('2026-05-18T10:24:00+08:00'),
})

assert.deepEqual(client.status(), {
  enabled: true,
  configured: true,
  webhookConfigured: true,
  secretConfigured: true,
})

const first = await client.sendEvents([event])
assert.equal(first.ok, true)
assert.equal(first.sent, 1)
assert.equal(calls.length, 1)
assert.equal(calls[0].body.timestamp, '1779071040')
assert.match(calls[0].body.sign, /^[A-Za-z0-9+/]+=*$/)
assert.equal(calls[0].body.msg_type, 'post')

const second = await client.sendEvents([event])
assert.equal(second.ok, true)
assert.equal(second.sent, 0)
assert.equal(second.skipped, 1)
assert.equal(calls.length, 1)

const disabled = createFeishuEventRadarClient({
  readConfig: () => '',
  fetcher: async () => {
    throw new Error('should not send')
  },
})
assert.deepEqual(disabled.status(), {
  enabled: false,
  configured: false,
  webhookConfigured: false,
  secretConfigured: false,
})

console.log('notifications route internals ok')
