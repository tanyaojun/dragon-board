import assert from 'node:assert/strict'

import { __jumpSignalRouteInternals } from './jumpSignalNotifications.js'

const {
  formatJumpSignalEventRadarMessage,
  createJumpSignalNotifierClient,
} = __jumpSignalRouteInternals

const entryEvent = {
  code: '002552',
  name: '宝鼎科技',
  signalType: 'entry',
  price: 10.35,
  changePct: 3.5,
  reason: '排名持续跳跃，动量与 MACD 金叉共振',
  confidence: 92,
  timestamp: Date.parse('2026-06-07T14:36:00+08:00'),
}

const exitEvent = {
  code: '603516',
  name: '淳中科技',
  signalType: 'exit',
  price: 42.18,
  changePct: -2.4,
  reason: 'MACD 死叉',
  confidence: 0,
  timestamp: Date.parse('2026-06-07T14:37:00+08:00'),
}

const candidatePoolEvent = {
  ...entryEvent,
  signalLabel: '候选池触发',
  reason: 'fusion 策略命中，已自动写入候选池',
}

const message = formatJumpSignalEventRadarMessage([entryEvent, exitEvent], {
  now: () => Date.parse('2026-06-07T14:38:00+08:00'),
})

assert.equal(message.msg_type, 'post')
assert.equal(message.content.post.zh_cn.title, '异动雷达 · 14:38:00 · 2条')
assert.deepEqual(
  message.content.post.zh_cn.content.map((line) => line.map((part) => part.text).join('')),
  [
    '【排名趋势买入】1条',
    '1. 宝鼎科技 002552  +3.50%',
    '   原因：排名持续跳跃，动量与 MACD 金叉共振',
    '',
    '【排名趋势卖出】1条',
    '1. 淳中科技 603516  -2.40%',
    '   原因：MACD 死叉',
  ],
)

const candidateMessage = formatJumpSignalEventRadarMessage([candidatePoolEvent], {
  now: () => Date.parse('2026-06-07T14:38:00+08:00'),
})

assert.deepEqual(
  candidateMessage.content.post.zh_cn.content.map((line) => line.map((part) => part.text).join('')),
  [
    '【候选池触发】1条',
    '1. 宝鼎科技 002552  +3.50%',
    '   原因：fusion 策略命中，已自动写入候选池',
  ],
)

const fetchCalls = []
const client = createJumpSignalNotifierClient({
  readConfig: (name) =>
    (
      {
        FEISHU_EVENT_RADAR_ENABLED: 'true',
        FEISHU_EVENT_RADAR_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/test',
        FEISHU_EVENT_RADAR_SECRET: 'secret',
      }
    )[name] || '',
  fetcher: async (_url, init) => {
    fetchCalls.push(JSON.parse(init.body))
    return {
      ok: true,
      status: 200,
      json: async () => ({ StatusCode: 0, msg: 'ok' }),
    }
  },
  now: () => Date.parse('2026-06-07T19:21:59+08:00'),
})

const skipped = await client.sendEvents([entryEvent])
assert.equal(skipped.ok, true)
assert.equal(skipped.sent, 0)
assert.equal(skipped.skipped, 1)
assert.equal(skipped.reason, 'outside-trading-time')
assert.equal(fetchCalls.length, 0)

const holidayClient = createJumpSignalNotifierClient({
  readConfig: (name) =>
    (
      {
        FEISHU_EVENT_RADAR_ENABLED: 'true',
        FEISHU_EVENT_RADAR_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/test',
        FEISHU_EVENT_RADAR_SECRET: 'secret',
      }
    )[name] || '',
  fetcher: async (_url, init) => {
    fetchCalls.push(JSON.parse(init.body))
    return {
      ok: true,
      status: 200,
      json: async () => ({ StatusCode: 0, msg: 'ok' }),
    }
  },
  now: () => Date.parse('2026-10-02T10:00:00+08:00'),
})

const holidaySkipped = await holidayClient.sendEvents([entryEvent])
assert.equal(holidaySkipped.ok, true)
assert.equal(holidaySkipped.sent, 0)
assert.equal(holidaySkipped.skipped, 1)
assert.equal(holidaySkipped.reason, 'outside-trading-time')
assert.equal(fetchCalls.length, 0)

console.log('jump signal notification route internals ok')
