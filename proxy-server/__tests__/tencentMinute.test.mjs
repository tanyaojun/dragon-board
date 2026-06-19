import assert from 'node:assert/strict'
import test from 'node:test'

import { createProxyApp } from '../app.js'
import { ProcessMemoryCache } from '../helpers/proxyCache.js'

function listen(app) {
  return new Promise((resolve) => {
    const server = app.listen(0, '127.0.0.1', () => {
      const address = server.address()
      resolve({ server, baseUrl: `http://127.0.0.1:${address.port}` })
    })
  })
}

function minutePayload() {
  return {
    code: 0,
    msg: '',
    data: {
      sz002297: {
        data: {
          date: '20260618',
          data: [
            '0930 25.70 11848 30449360.00',
            '0931 26.25 71011 184435426.43',
          ],
        },
      },
    },
  }
}

test('tencent minute route normalizes cumulative turnover rows', async () => {
  let upstreamUrl = ''
  const app = createProxyApp({
    logRequests: false,
    runtimeCache: new ProcessMemoryCache(),
    clients: {
      client: {},
      plainClient: {
        get: async (url) => {
          upstreamUrl = String(url)
          return { data: minutePayload() }
        },
      },
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/quotes/tencent/minute?code=002297`)
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.match(upstreamUrl, /code=sz002297/)
    assert.equal(body.ok, true)
    assert.equal(body.stockCode, '002297')
    assert.equal(body.data.date, '20260618')
    assert.deepEqual(body.data.points[1], {
      time: '0931',
      price: 26.25,
      cumulativeVolume: 71011,
      cumulativeAmount: 184435426.43,
    })
    assert.equal(body.data.dragonMeta.cache.store, 'memory')
  } finally {
    server.close()
  }
})

test('tencent minute route rejects malformed stock codes', async () => {
  let upstreamCalls = 0
  const app = createProxyApp({
    logRequests: false,
    clients: {
      client: {},
      plainClient: { get: async () => { upstreamCalls += 1 } },
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/quotes/tencent/minute?code=abc`)
    const body = await response.json()
    assert.equal(response.status, 400)
    assert.equal(body.errorCode, 'invalid_stock_code')
    assert.equal(upstreamCalls, 0)
  } finally {
    server.close()
  }
})

test('tencent minute route degrades malformed upstream structures', async () => {
  const app = createProxyApp({
    logRequests: false,
    clients: {
      client: {},
      plainClient: { get: async () => ({ data: { code: 0, data: {} } }) },
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/quotes/tencent/minute?code=002297`)
    const body = await response.json()
    assert.equal(response.status, 200)
    assert.equal(body.ok, false)
    assert.equal(body.degraded, true)
    assert.equal(body.source, 'quotes-tencent-minute')
  } finally {
    server.close()
  }
})

test('tencent minute route serves cache hits and stale data', async () => {
  let now = 1_750_000_000_000
  let upstreamCalls = 0
  let fail = false
  const app = createProxyApp({
    logRequests: false,
    now: () => now,
    runtimeCache: new ProcessMemoryCache({ now: () => now }),
    clients: {
      client: {},
      plainClient: {
        get: async () => {
          upstreamCalls += 1
          if (fail) throw new Error('blocked')
          return { data: minutePayload() }
        },
      },
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    const url = `${baseUrl}/api/quotes/tencent/minute?code=002297`
    const first = await (await fetch(url)).json()
    const hit = await (await fetch(url)).json()
    assert.equal(upstreamCalls, 1)
    assert.equal(first.data.dragonMeta.cache.hit, false)
    assert.equal(hit.data.dragonMeta.cache.hit, true)

    now += 6_000
    fail = true
    const stale = await (await fetch(url)).json()
    assert.equal(stale.ok, true)
    assert.equal(stale.data.dragonMeta.cache.stale, true)
  } finally {
    server.close()
  }
})
