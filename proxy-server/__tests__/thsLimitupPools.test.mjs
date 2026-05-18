import assert from 'node:assert/strict'
import test, { mock } from 'node:test'

import { createProxyApp } from '../app.js'

function listen(app) {
  return new Promise((resolve) => {
    const server = app.listen(0, () => {
      const address = server.address()
      resolve({ server, baseUrl: `http://127.0.0.1:${address.port}` })
    })
  })
}

test('ths limitup pools aggregates all pool requests with stable keys', async () => {
  const requestedUrls = []
  const plainClient = {
    async get(url) {
      requestedUrls.push(url)
      if (url.includes('get_limit_up_stocks')) {
        return { data: { data: { stock_list: [{ stock_code: '600001' }], page_info: { total: 1 } } } }
      }
      if (url.includes('get_drawdown_stocks')) {
        return { data: { data: { stock_list: [{ stock_code: '600002' }], page_info: { total: 1 } } } }
      }
      return { data: { data: { info: [{ code: '600003' }], page: { total: 1 } } } }
    },
  }
  const app = createProxyApp({
    logRequests: false,
    clients: { client: plainClient, plainClient },
  })
  const { server, baseUrl } = await listen(app)

  try {
    const response = await fetch(`${baseUrl}/api/limitup/ths/pools?date=20260515`)
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.equal(body.source, 'limitup-ths-pools')
    assert.equal(body.date, '20260515')
    assert.equal(body.degraded, false)
    assert.deepEqual(Object.keys(body.pools), [
      'one',
      'two',
      'three',
      'four',
      'high',
      'failed',
      'rushing',
      'drawdown',
    ])
    assert.equal(body.pools.one.cate, 'limit_up_one')
    assert.deepEqual(body.pools.one.items, [{ stock_code: '600001' }])
    assert.deepEqual(body.pools.failed.items, [{ code: '600003' }])
    assert.equal(requestedUrls.length, 8)
    assert.ok(requestedUrls.every((url) => new URL(url).searchParams.get('date') === '20260515'))
  } finally {
    server.close()
  }
})

test('ths limitup pools defaults date by Asia Shanghai calendar day', async () => {
  const requestedUrls = []
  const plainClient = {
    async get(url) {
      requestedUrls.push(url)
      return { data: { data: { stock_list: [], page_info: { total: 0 } } } }
    },
  }
  mock.timers.enable({ apis: ['Date'], now: new Date('2026-05-17T18:30:00.000Z') })
  const app = createProxyApp({
    logRequests: false,
    clients: { client: plainClient, plainClient },
  })
  const { server, baseUrl } = await listen(app)

  try {
    const response = await fetch(`${baseUrl}/api/limitup/ths/pools`)
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(body.date, '20260518')
    assert.ok(requestedUrls.every((url) => new URL(url).searchParams.get('date') === '20260518'))
  } finally {
    mock.timers.reset()
    server.close()
  }
})

test('ths limitup pools degrades individual failed pools only', async () => {
  const plainClient = {
    async get(url) {
      if (url.includes('open_limit_pool')) {
        const error = new Error('open pool unavailable')
        error.code = 'ECONNRESET'
        throw error
      }
      return { data: { data: { stock_list: [], info: [], page_info: { total: 0 }, page: { total: 0 } } } }
    },
  }
  const app = createProxyApp({
    logRequests: false,
    clients: { client: plainClient, plainClient },
  })
  const { server, baseUrl } = await listen(app)

  try {
    const response = await fetch(`${baseUrl}/api/limitup/ths/pools?date=20260515`)
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(body.ok, false)
    assert.equal(body.degraded, true)
    assert.equal(body.pools.one.ok, true)
    assert.equal(body.pools.failed.ok, false)
    assert.equal(body.pools.failed.errorCode, 'upstream_network_error')
    assert.deepEqual(body.pools.failed.items, [])
    assert.deepEqual(body.errors.map((item) => item.pool), ['failed'])
  } finally {
    server.close()
  }
})
