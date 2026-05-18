import assert from 'node:assert/strict'
import test from 'node:test'

import { createProxyApp } from '../app.js'
import { createProxyRuntime } from '../runtime.js'

function listen(app) {
  return new Promise((resolve) => {
    const server = app.listen(0, '127.0.0.1', () => {
      const address = server.address()
      resolve({ server, baseUrl: `http://127.0.0.1:${address.port}` })
    })
  })
}

test('event radar notification status includes proxy background worker state', async () => {
  const app = createProxyApp({
    logRequests: false,
    readConfig: (name) => ({
      FEISHU_EVENT_RADAR_ENABLED: 'true',
      FEISHU_EVENT_RADAR_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/test',
      FEISHU_EVENT_RADAR_SECRET: 'secret',
    })[name] || '',
    eventRadarBackgroundWorker: {
      status: () => ({
        backgroundEnabled: true,
        running: true,
        initialized: true,
        intervalMs: 30000,
        lastFetchedCount: 2,
        lastSentCount: 1,
      }),
    },
  })
  const { server, baseUrl } = await listen(app)

  try {
    const response = await fetch(`${baseUrl}/api/notifications/event-radar/status`)
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.equal(body.configured, true)
    assert.deepEqual(body.background, {
      backgroundEnabled: true,
      running: true,
      initialized: true,
      intervalMs: 30000,
      lastFetchedCount: 2,
      lastSentCount: 1,
    })
  } finally {
    server.close()
  }
})

test('proxy runtime shares event radar cooldown state between background worker and http route', async () => {
  const webhookCalls = []
  let fetchRun = 0
  const backgroundEvents = [
    {
      id: 'event-a',
      event_type: 10001,
      event_type_name: '封涨停板',
      event_timestamp: 1778811000,
      stock_code: '600001',
      stock_name: '样本一',
      change_percent: 10.01,
    },
    {
      id: 'event-b',
      event_type: 10001,
      event_type_name: '封涨停板',
      event_timestamp: 1778811060,
      stock_code: '600002',
      stock_name: '样本二',
      change_percent: 10.02,
    },
  ]
  const plainClient = {
    get: async () => ({
      data: {
        data: {
          stock_abnormal_event_data: fetchRun++ === 0 ? [backgroundEvents[0]] : backgroundEvents,
        },
      },
    }),
  }

  const { app, eventRadarBackgroundWorker } = await createProxyRuntime({
    port: 0,
    logRequests: false,
    localEnv: {},
    readConfig: (name) => ({
      FEISHU_EVENT_RADAR_ENABLED: 'true',
      FEISHU_EVENT_RADAR_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/test',
      FEISHU_EVENT_RADAR_SECRET: 'secret',
      FEISHU_EVENT_RADAR_BACKGROUND_ENABLED: 'true',
    })[name] || '',
    cache: {},
    clients: { client: plainClient, plainClient },
    feishuFetcher: async (_url, init) => {
      webhookCalls.push(JSON.parse(init.body))
      return {
        ok: true,
        status: 200,
        json: async () => ({ StatusCode: 0, msg: 'ok' }),
      }
    },
  })
  const { server, baseUrl } = await listen(app)

  try {
    await eventRadarBackgroundWorker.runOnce()
    await eventRadarBackgroundWorker.runOnce()

    assert.equal(webhookCalls.length, 1)

    const response = await fetch(`${baseUrl}/api/notifications/event-radar/events`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        events: [
          {
            id: 'panel-event-b',
            typeName: '封涨停板',
            timestamp: 1778811060000,
            code: '600002',
            name: '样本二',
            changePct: 0.1002,
          },
        ],
      }),
    })
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.equal(body.sent, 0)
    assert.equal(webhookCalls.length, 1)
  } finally {
    server.close()
  }
})
