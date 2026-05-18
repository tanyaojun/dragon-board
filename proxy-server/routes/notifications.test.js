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
assert.equal(message.content.post.zh_cn.title, '异动雷达 · 10:24:00 · 1条')
assert.deepEqual(message.content.post.zh_cn.content[0].map((part) => part.text).join(''), '【封涨停板】1条')
assert.deepEqual(message.content.post.zh_cn.content[1].map((part) => part.text).join(''), '1. 北巴传媒 600386  +10.10%')
assert.deepEqual(message.content.post.zh_cn.content[2].map((part) => part.text).join(''), '   板块：广告传媒 / 北京国资 / 汽车服务')

const groupedMessage = formatEventRadarMessage(
  [
    event,
    {
      id: '10003-002858-20260518102344',
      typeName: '打开涨停板',
      timestamp: Date.parse('2026-05-18T10:23:44+08:00'),
      code: '002858',
      name: '力盛体育',
      changePct: -0.0994,
      relatedPlates: ['VR&AR', '人工智能'],
    },
  ],
  { now: () => Date.parse('2026-05-18T10:25:00+08:00') },
)
const groupedLines = groupedMessage.content.post.zh_cn.content.map((line) => line.map((part) => part.text).join(''))
assert.equal(groupedMessage.content.post.zh_cn.title, '异动雷达 · 10:25:00 · 2条')
assert.deepEqual(groupedLines.slice(0, 7), [
  '【打开涨停板】1条',
  '1. 力盛体育 002858  -9.94%',
  '   板块：VR&AR / 人工智能',
  '',
  '【封涨停板】1条',
  '1. 北巴传媒 600386  +10.10%',
  '   板块：广告传媒 / 北京国资 / 汽车服务',
])

const calls = []
let scheduledBatch = null
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
  setTimeoutFn: (callback, intervalMs) => {
    scheduledBatch = { callback, intervalMs }
    return 42
  },
})

assert.deepEqual(client.status(), {
  enabled: true,
  configured: true,
  webhookConfigured: true,
  secretConfigured: true,
  batchWindowMs: 300000,
  pendingCount: 0,
})

const backgroundStatus = { running: true, initialized: true, lastFetchedCount: 3 }
const statusPayload = {
  ok: true,
  source: 'event-radar-feishu',
  ...client.status(),
  background: backgroundStatus,
}
assert.deepEqual(statusPayload.background, backgroundStatus)

const first = await client.sendEvents([event])
assert.equal(first.ok, true)
assert.equal(first.queued, 1)
assert.equal(first.sent, 0)
assert.equal(calls.length, 0)
assert.equal(client.status().pendingCount, 1)
assert.equal(scheduledBatch.intervalMs, 300000)

const flushed = await scheduledBatch.callback()
assert.equal(flushed.ok, true)
assert.equal(flushed.sent, 1)
assert.equal(calls.length, 1)
assert.equal(client.status().pendingCount, 0)
assert.equal(calls[0].body.timestamp, '1779071040')
assert.match(calls[0].body.sign, /^[A-Za-z0-9+/]+=*$/)
assert.equal(calls[0].body.msg_type, 'post')

const second = await client.sendEvents([event])
assert.equal(second.ok, true)
assert.equal(second.sent, 0)
assert.equal(second.skipped, 1)
assert.equal(calls.length, 1)
client.stopBatch()

const batchCalls = []
const batchClient = createFeishuEventRadarClient({
  readConfig: (name) => ({
    FEISHU_EVENT_RADAR_ENABLED: 'true',
    FEISHU_EVENT_RADAR_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/test',
    FEISHU_EVENT_RADAR_SECRET: 'secret',
  })[name] || '',
  fetcher: async (_url, init) => {
    batchCalls.push(JSON.parse(init.body))
    return {
      ok: true,
      status: 200,
      json: async () => ({ StatusCode: 0, msg: 'ok' }),
    }
  },
  now: () => Date.parse('2026-05-18T10:30:00+08:00'),
  setTimeoutFn: () => 77,
  clearTimeoutFn: () => {},
})
await batchClient.sendEvents([
  event,
  { ...event, id: 'b2', code: '000002', name: '样本二', typeName: '大幅拉升' },
  { ...event, id: 'b3', code: '000003', name: '样本三', typeName: '大幅拉升' },
])
await batchClient.sendEvents([
  { ...event, id: 'b4', code: '000004', name: '样本四', typeName: '打开涨停板' },
  { ...event, id: 'b5', code: '000005', name: '样本五', typeName: '打开涨停板' },
  { ...event, id: 'b6', code: '000006', name: '样本六', typeName: '快速跳水' },
])
const batchFlush = await batchClient.flushPending()
assert.equal(batchFlush.sent, 6)
assert.equal(batchCalls.length, 1)
assert.equal(batchCalls[0].content.post.zh_cn.title, '异动雷达 · 10:30:00 · 6条')
batchClient.stopBatch()

const disabled = createFeishuEventRadarClient({
  readConfig: () => '',
  setTimeoutFn: () => 1,
  fetcher: async () => {
    throw new Error('should not send')
  },
})
assert.deepEqual(disabled.status(), {
  enabled: false,
  configured: false,
  webhookConfigured: false,
  secretConfigured: false,
  batchWindowMs: 300000,
  pendingCount: 0,
})
await assert.rejects(() => disabled.sendEvents([event]), /FEISHU_EVENT_RADAR_ENABLED is not true/)

console.log('notifications route internals ok')
