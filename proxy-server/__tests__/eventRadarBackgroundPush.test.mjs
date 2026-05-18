import assert from 'node:assert/strict'
import test from 'node:test'

import { createEventRadarBackgroundWorker } from '../services/eventRadarBackgroundPush.js'

function enabledConfig(name) {
  return {
    FEISHU_EVENT_RADAR_ENABLED: 'true',
    FEISHU_EVENT_RADAR_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/test',
    FEISHU_EVENT_RADAR_SECRET: 'secret',
  }[name] || ''
}

function makeRawEvent(overrides = {}) {
  return {
    id: overrides.id || 'event-a',
    event_type: overrides.event_type || 10001,
    event_type_name: overrides.event_type_name || '封涨停板',
    event_timestamp: overrides.event_timestamp || 1779071040,
    stock_code: overrides.stock_code || '600386',
    stock_name: overrides.stock_name || '北巴传媒',
    change_percent: overrides.change_percent ?? 10.1,
    related_plates: overrides.related_plates || [{ plate_name: '广告传媒' }],
  }
}

test('event radar background worker builds a baseline on first run without sending', async () => {
  const sent = []
  const worker = createEventRadarBackgroundWorker({
    readConfig: enabledConfig,
    fetchEvents: async () => [makeRawEvent({ id: 'event-a' })],
    notifier: {
      status: () => ({
        enabled: true,
        configured: true,
        webhookConfigured: true,
        secretConfigured: true,
      }),
      sendEvents: async (events) => sent.push(events),
    },
    now: () => Date.parse('2026-05-18T10:24:00+08:00'),
  })

  const result = await worker.runOnce()

  assert.equal(result.ok, true)
  assert.equal(result.baseline, true)
  assert.equal(result.sent, 0)
  assert.equal(sent.length, 0)
  assert.equal(worker.status().initialized, true)
  assert.equal(worker.status().lastFetchedCount, 1)
})

test('event radar background worker queues only new stock events after baseline', async () => {
  const sent = []
  let run = 0
  const worker = createEventRadarBackgroundWorker({
    readConfig: enabledConfig,
    fetchEvents: async () => {
      run += 1
      if (run === 1) return [makeRawEvent({ id: 'event-a', stock_code: '600386' })]
      if (run === 2) {
        return [
          makeRawEvent({ id: 'event-a', stock_code: '600386' }),
          makeRawEvent({ id: 'event-b', stock_code: '000002', stock_name: '万科A', event_type_name: '大幅拉升' }),
        ]
      }
      return [
        makeRawEvent({ id: 'event-a', stock_code: '600386' }),
        makeRawEvent({ id: 'event-b', stock_code: '000002', stock_name: '万科A', event_type_name: '大幅拉升' }),
        makeRawEvent({ id: 'event-c', stock_code: '002858', stock_name: '力盛体育', event_type_name: '打开涨停板' }),
        makeRawEvent({ id: 'sector-a', stock_code: '', event_type: 11000, event_type_name: '板块拉升' }),
      ]
    },
    notifier: {
      status: () => ({
        enabled: true,
        configured: true,
        webhookConfigured: true,
        secretConfigured: true,
      }),
      sendEvents: async (events) => {
        sent.push(events)
        return { ok: true, queued: events.length, sent: 0, skipped: 0 }
      },
    },
    now: () => Date.parse('2026-05-18T10:24:00+08:00'),
  })

  await worker.runOnce()
  const second = await worker.runOnce()
  const third = await worker.runOnce()

  assert.equal(second.ok, true)
  assert.equal(second.baseline, false)
  assert.equal(second.sent, 0)
  assert.equal(second.queued, 1)
  assert.equal(third.queued, 1)
  assert.equal(sent.length, 2)
  assert.deepEqual(sent.flat().map((event) => event.code), ['000002', '002858'])
  assert.equal(sent[0][0].typeName, '大幅拉升')
})

test('event radar background worker start and stop manage the polling timer', () => {
  let scheduled = null
  let cleared = null
  const worker = createEventRadarBackgroundWorker({
    readConfig: (name) => ({
      ...Object.fromEntries(['FEISHU_EVENT_RADAR_ENABLED', 'FEISHU_EVENT_RADAR_WEBHOOK', 'FEISHU_EVENT_RADAR_SECRET'].map((key) => [key, enabledConfig(key)])),
      FEISHU_EVENT_RADAR_BACKGROUND_INTERVAL_MS: '15000',
    })[name] || '',
    fetchEvents: async () => [],
    notifier: {
      status: () => ({
        enabled: true,
        configured: true,
        webhookConfigured: true,
        secretConfigured: true,
      }),
      sendEvents: async () => ({ ok: true, sent: 0, skipped: 0 }),
    },
    setIntervalFn: (callback, intervalMs) => {
      scheduled = { callback, intervalMs }
      return 42
    },
    clearIntervalFn: (timer) => {
      cleared = timer
    },
  })

  assert.equal(worker.start(), true)
  assert.equal(scheduled.intervalMs, 15000)
  assert.equal(worker.status().running, true)

  worker.stop()

  assert.equal(cleared, 42)
  assert.equal(worker.status().running, false)
})

test('event radar background worker does not start when Feishu is not configured', () => {
  let scheduled = false
  const worker = createEventRadarBackgroundWorker({
    readConfig: () => '',
    fetchEvents: async () => [],
    notifier: {
      status: () => ({
        enabled: false,
        configured: false,
        webhookConfigured: false,
        secretConfigured: false,
      }),
      sendEvents: async () => {
        throw new Error('should not send')
      },
    },
    setIntervalFn: () => {
      scheduled = true
      return 1
    },
  })

  assert.equal(worker.start(), false)
  assert.equal(scheduled, false)
  assert.equal(worker.status().enabled, false)
  assert.equal(worker.status().running, false)
})
