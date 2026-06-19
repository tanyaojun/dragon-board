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

function thsPayload() {
  return {
    errorcode: 0,
    msg: 'ok',
    title: {
      stockcode: '002297',
      stockname: '博云新材',
      price: '28.36',
    },
    list: [
      {
        nature: '主力主买',
        volume: '566手',
        avgprice: '28.36',
        money: '80万',
        ctime: '13:13:12',
      },
    ],
    pricechange: [],
  }
}

test('THS big-order detail validates stock code and returns source payload', async () => {
  let now = 1_750_000_000_000
  const calls = []
  const app = createProxyApp({
    logRequests: false,
    runtimeCache: new ProcessMemoryCache({ now: () => now }),
    now: () => now,
    clients: {
      client: {},
      plainClient: {
        get: async (url, config) => {
          calls.push({ url: String(url), config })
          return { data: thsPayload() }
        },
      },
    },
  })

  const { server, baseUrl } = await listen(app)
  try {
    const invalid = await fetch(`${baseUrl}/api/big-order/ths-detail?stockCode=abc`)
    assert.equal(invalid.status, 400)
    assert.equal((await invalid.json()).errorCode, 'invalid_stock_code')

    const response = await fetch(`${baseUrl}/api/big-order/ths-detail?stockCode=002297`)
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.equal(body.source, 'ths-big-order-detail')
    assert.equal(body.stockCode, '002297')
    assert.equal(body.fetchedAt, now)
    assert.equal(body.servedAt, now)
    assert.equal(body.data.title.stockname, '博云新材')
    assert.equal(body.data.list[0].nature, '主力主买')
    assert.equal(body.data.dragonMeta.cache.hit, false)
    assert.equal(calls.length, 1)

    const upstream = new URL(calls[0].url)
    assert.equal(upstream.origin + upstream.pathname, 'https://vaserviece.10jqka.com.cn/Level2/index.php')
    assert.equal(upstream.searchParams.get('op'), 'mainMonitorDetail')
    assert.equal(upstream.searchParams.get('stockcode'), '002297')
    assert.match(calls[0].config.headers['User-Agent'], /Mozilla\/5\.0/)
    assert.equal(calls[0].config.headers.Referer, 'https://vaserviece.10jqka.com.cn/')
    assert.equal(calls[0].config.headers.Accept, 'application/json,text/plain,*/*')
  } finally {
    server.close()
  }
})

test('process memory cache hits, coalesces misses, and returns stale on loader failure', async () => {
  let now = 1_750_000_000_000
  const cache = new ProcessMemoryCache({ now: () => now })
  let calls = 0
  let release
  const gate = new Promise((resolve) => {
    release = resolve
  })
  const loader = async () => {
    calls += 1
    await gate
    return { value: calls }
  }
  const options = { ttlSeconds: 5, staleTtlSeconds: 30 }

  const first = cache.remember('same-key', options, loader)
  const concurrent = cache.remember('same-key', options, loader)
  release()
  const [firstResult, concurrentResult] = await Promise.all([first, concurrent])

  assert.equal(calls, 1)
  assert.equal(firstResult.cache.hit, false)
  assert.equal(concurrentResult.value.value, 1)

  const hit = await cache.remember('same-key', options, async () => ({ value: 2 }))
  assert.equal(hit.cache.hit, true)
  assert.equal(calls, 1)

  now += 6_000
  const stale = await cache.remember('same-key', options, async () => {
    throw new Error('upstream unavailable')
  })
  assert.equal(stale.cache.hit, true)
  assert.equal(stale.cache.stale, true)

  now += 30_000
  await assert.rejects(
    cache.remember('same-key', options, async () => {
      throw new Error('still unavailable')
    }),
    /still unavailable/,
  )
})

test('THS big-order detail serves cached and stale data before degrading', async () => {
  let now = 1_750_000_000_000
  let upstreamCalls = 0
  let fail = false
  const app = createProxyApp({
    logRequests: false,
    runtimeCache: new ProcessMemoryCache({ now: () => now }),
    now: () => now,
    clients: {
      client: {},
      plainClient: {
        get: async () => {
          upstreamCalls += 1
          if (fail) throw new Error('blocked')
          return { data: thsPayload() }
        },
      },
    },
  })

  const { server, baseUrl } = await listen(app)
  try {
    const url = `${baseUrl}/api/big-order/ths-detail?stockCode=002297`
    const firstBody = await (await fetch(url)).json()
    const secondBody = await (await fetch(url)).json()
    assert.equal(upstreamCalls, 1)
    assert.equal(firstBody.data.dragonMeta.cache.hit, false)
    assert.equal(secondBody.data.dragonMeta.cache.hit, true)

    now += 31_000
    fail = true
    const staleResponse = await fetch(url)
    const staleBody = await staleResponse.json()
    assert.equal(staleResponse.status, 200)
    assert.equal(staleBody.data.dragonMeta.cache.stale, true)

    now += 180_000
    const degradedResponse = await fetch(url)
    const degradedBody = await degradedResponse.json()
    assert.equal(degradedResponse.status, 200)
    assert.equal(degradedBody.ok, false)
    assert.equal(degradedBody.degraded, true)
    assert.equal(degradedBody.source, 'ths-big-order-detail')
  } finally {
    server.close()
  }
})

test('legacy main-monitor keeps its unwrapped KPL response contract', async () => {
  const expected = [{ StockID: '002297', Money: 800000 }]
  let upstreamUrl = ''
  const app = createProxyApp({
    logRequests: false,
    clients: {
      client: {},
      plainClient: {
        get: async (url) => {
          upstreamUrl = String(url)
          return { data: { List: expected } }
        },
      },
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(
      `${baseUrl}/api/big-order/main-monitor?stockCode=002297&limit=10`,
    )
    assert.equal(response.status, 200)
    assert.deepEqual(await response.json(), { List: expected })
    assert.match(upstreamUrl, /[?&]a=GetMainMonitor_w30(?:&|$)/)
  } finally {
    server.close()
  }
})

test('legacy all-day stops on a short page and keeps the unwrapped List contract', async () => {
  const fullPage = Array.from({ length: 500 }, (_, index) => ({ id: index }))
  const lastPage = [{ id: 500 }]
  const indexes = []
  const app = createProxyApp({
    logRequests: false,
    clients: {
      client: {},
      plainClient: {
        get: async (url) => {
          const parsed = new URL(url)
          indexes.push(parsed.searchParams.get('Index'))
          return { data: { List: indexes.length === 1 ? fullPage : lastPage } }
        },
      },
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/big-order/all-day?stockCode=002297`)
    const body = await response.json()
    assert.equal(response.status, 200)
    assert.deepEqual(indexes, ['0', '500'])
    assert.equal(body.List.length, 501)
    assert.equal(body.ok, undefined)
  } finally {
    server.close()
  }
})

test('legacy all-day handles empty and degraded upstream results', async (t) => {
  await t.test('empty page', async () => {
    const app = createProxyApp({
      logRequests: false,
      clients: {
        client: {},
        plainClient: { get: async () => ({ data: { List: [] } }) },
      },
    })
    const { server, baseUrl } = await listen(app)
    try {
      const response = await fetch(`${baseUrl}/api/big-order/all-day?stockCode=002297`)
      assert.deepEqual(await response.json(), { List: [] })
    } finally {
      server.close()
    }
  })

  await t.test('upstream error', async () => {
    const app = createProxyApp({
      logRequests: false,
      clients: {
        client: {},
        plainClient: {
          get: async () => {
            throw new Error('legacy blocked')
          },
        },
      },
    })
    const { server, baseUrl } = await listen(app)
    try {
      const response = await fetch(`${baseUrl}/api/big-order/all-day?stockCode=002297`)
      const body = await response.json()
      assert.equal(response.status, 200)
      assert.equal(body.degraded, true)
      assert.deepEqual(body.data, { List: [] })
    } finally {
      server.close()
    }
  })
})
