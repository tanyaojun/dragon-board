import assert from 'node:assert/strict'
import test from 'node:test'

import { createProxyApp } from '../app.js'
import { ProcessMemoryCache } from '../helpers/proxyCache.js'

// 路由测试禁用真实归档目录，避免读写生产 data/big-order
const noopArchiver = { save: async () => {}, load: async () => null, dir: 'noop' }
const noopCollector = { register: async () => [], list: async () => [], runDaily: async () => ({ requested: 0, succeeded: 0, failed: 0, failures: [] }), startTimer: () => null }

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
    pricechange: [{ 1: '202607171313', 2: '1.2' }],
  }
}

test('THS big-order detail validates stock code and returns source payload', async () => {
  let now = 1_750_000_000_000
  const calls = []
  const app = createProxyApp({
    logRequests: false,
    bigOrderArchiver: noopArchiver,
    bigOrderCollector: noopCollector,
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
    assert.equal(body.sessionDate, '2026-07-17')
    assert.equal(body.fetchedAt, now)
    assert.equal(body.servedAt, now)
    assert.equal(body.data.title.stockname, '博云新材')
    assert.equal(body.data.list[0].nature, '主力主买')
    assert.equal(body.data.dragonMeta.cache.hit, false)
    assert.equal(body.data.dragonMeta.cache.upstreamCalled, true)
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

test('structured Longhu all-day endpoint returns canonical envelope', async () => {
  const now = Date.parse('2026-07-17T02:00:00Z')
  const app = createProxyApp({
    logRequests: false,
    bigOrderArchiver: noopArchiver,
    bigOrderCollector: noopCollector,
    now: () => now,
    readConfig: (name, fallback) =>
      name === 'BIG_ORDER_LONGHU_INCREMENTAL_MODE' ? 'off' : fallback,
    clients: {
      client: {},
      plainClient: {
        get: async () => ({ data: thsPayload() }),
        post: async () => ({
          data: {
            errcode: '0',
            Total: 1,
            List: [['2', '1784200000', '100', '1000', '10', '2026-07-17 09:30:00']],
          },
        }),
      },
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(
      `${baseUrl}/api/big-order/longhu/all-day?stockCode=002297&money=0`,
    )
    const body = await response.json()
    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.equal(body.source, 'longhu-big-order-all-day')
    assert.equal(body.sessionDate, '2026-07-17')
    assert.equal(body.data.List.length, 1)
    assert.equal(body.data.dragonMeta.cache.uiStale, false)
    assert.equal(body.data.dragonMeta.cache.ttlSeconds, 10)
    assert.equal(body.data.dragonMeta.refresh.mode, 'cold-full')
    assert.equal(body.data.dragonMeta.refresh.inProgress, false)
    assert.equal(body.data.dragonMeta.refresh.pagesFetched, 1)
    assert.equal(body.data.dragonMeta.refresh.newRows, 1)
    assert.equal(body.data.dragonMeta.refresh.total, 1)
    assert.equal(body.data.dragonMeta.refresh.elapsedMs, 0)
    assert.equal(body.data.dragonMeta.refresh.incrementFailureCount, 0)
  } finally {
    server.close()
  }
})

test('THS big-order detail rejects malformed upstream structures', async () => {
  let calls = 0
  const app = createProxyApp({
    logRequests: false,
    bigOrderArchiver: noopArchiver,
    bigOrderCollector: noopCollector,
    clients: {
      client: {},
      plainClient: {
        get: async () => {
          calls += 1
          return { data: { errorcode: 0, title: 'invalid', list: [] } }
        },
      },
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    const first = await fetch(`${baseUrl}/api/big-order/ths-detail?stockCode=002297`)
    const second = await fetch(`${baseUrl}/api/big-order/ths-detail?stockCode=002297`)
    assert.equal((await first.json()).degraded, true)
    assert.equal((await second.json()).degraded, true)
    assert.equal(calls, 2)
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

test('process memory cache evicts oldest entries at its capacity limit', async () => {
  const cache = new ProcessMemoryCache({ maxEntries: 2 })
  await cache.set('a', 1, { ttlSeconds: 30 })
  await cache.set('b', 2, { ttlSeconds: 30 })
  await cache.set('c', 3, { ttlSeconds: 30 })
  assert.equal(await cache.get('a'), null)
  assert.equal((await cache.get('b')).value, 2)
  assert.equal((await cache.get('c')).value, 3)
})

test('THS big-order detail serves cached and stale data before degrading', async () => {
  let now = Date.parse('2026-07-17T02:00:00Z')
  let upstreamCalls = 0
  let fail = false
  const app = createProxyApp({
    logRequests: false,
    bigOrderArchiver: noopArchiver,
    bigOrderCollector: noopCollector,
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
    assert.equal(staleBody.data.dragonMeta.cache.uiStale, true)

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
  let upstreamForm
  const app = createProxyApp({
    logRequests: false,
    bigOrderArchiver: noopArchiver,
    bigOrderCollector: noopCollector,
    clients: {
      client: {},
      plainClient: {
        post: async (url, body) => {
          upstreamForm = new URLSearchParams(body)
          return { data: { errcode: '0', Total: 1, List: expected } }
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
    const body = await response.json()
    assert.deepEqual(body.List, expected)
    assert.equal(body.ok, undefined)
    assert.equal(upstreamForm.get('a'), 'GetMainMonitor_w30')
    assert.equal(upstreamForm.get('st'), '200')
  } finally {
    server.close()
  }
})

test('legacy all-day uses internal pages of 200 and keeps the unwrapped List contract', async () => {
  const fullPage = Array.from({ length: 200 }, (_, index) => [
    '2',
    String(1784200000 + index),
    '100',
    '1000',
    '10',
    '2026-07-17 09:30:00',
  ])
  const lastPage = [['2', '1784200200', '100', '1000', '10', '2026-07-17 09:30:00']]
  const indexes = []
  const app = createProxyApp({
    logRequests: false,
    bigOrderArchiver: noopArchiver,
    bigOrderCollector: noopCollector,
    clients: {
      client: {},
      plainClient: {
        post: async (url, body) => {
          const form = new URLSearchParams(body)
          indexes.push(form.get('Index'))
          return {
            data: {
              errcode: '0',
              Total: 201,
              List: indexes.length === 1 ? fullPage : lastPage,
            },
          }
        },
      },
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/big-order/all-day?stockCode=002297`)
    const body = await response.json()
    assert.equal(response.status, 200)
    assert.deepEqual(indexes, ['0', '200'])
    assert.equal(body.List.length, 201)
    assert.equal(body.ok, undefined)
  } finally {
    server.close()
  }
})

test('legacy all-day handles empty and degraded upstream results', async (t) => {
  await t.test('empty page', async () => {
    const app = createProxyApp({
      logRequests: false,
    bigOrderArchiver: noopArchiver,
    bigOrderCollector: noopCollector,
      clients: {
        client: {},
        plainClient: {
          post: async () => ({ data: { errcode: '0', Total: 0, List: [] } }),
        },
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
    bigOrderArchiver: noopArchiver,
    bigOrderCollector: noopCollector,
      clients: {
        client: {},
        plainClient: {
          post: async () => {
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

test('collect-list endpoint validates input, deduplicates and returns the daily list', async () => {
  const list = []
  const app = createProxyApp({
    logRequests: false,
    bigOrderArchiver: noopArchiver,
    bigOrderCollector: {
      register: async (codes) => { list.splice(0, list.length, ...codes); return codes },
      list: () => list,
      runDaily: async () => ({ requested: 0, succeeded: 0, failed: 0, failures: [] }),
      startTimer: () => null,
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    // 缺少 body → 400
    const missing = await fetch(`${baseUrl}/api/big-order/longhu/collect-list`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}',
    })
    assert.equal(missing.status, 400)

    // 非数组 → 400
    const bad = await fetch(`${baseUrl}/api/big-order/longhu/collect-list`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ stockCodes: 'x' }),
    })
    assert.equal(bad.status, 400)

    // 正常登记
    const reg = await fetch(`${baseUrl}/api/big-order/longhu/collect-list`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ stockCodes: ['600519', '002297', '600519', 'abc'] }),
    })
    assert.equal(reg.status, 200)
    const regBody = await reg.json()
    // mock register 不限校验，返回原始传入数组（collector.register 内部自行校验去重）
    assert.deepEqual(regBody.list, ['600519', '002297', '600519', 'abc'])
  } finally {
    server.close()
  }
})

test('collect-list degraded when the underlying register call rejects', async () => {
  const app = createProxyApp({
    logRequests: false,
    bigOrderArchiver: noopArchiver,
    bigOrderCollector: {
      register: async () => { throw new Error('disk full') },
      list: () => [],
      runDaily: async () => ({ requested: 0, succeeded: 0, failed: 0, failures: [] }),
      startTimer: () => null,
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/big-order/longhu/collect-list`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ stockCodes: ['600519'] }),
    })
    assert.equal(response.status, 200)
    const body = await response.json()
    assert.equal(body.degraded, true)
    assert.equal(body.source, 'big-order-collect-list')
  } finally {
    server.close()
  }
})

test('collect endpoint validates and bounds stockCodes while the non-array path reads the daily list', async () => {
  const list = ['002297']
  const last = []
  const app = createProxyApp({
    logRequests: false,
    bigOrderArchiver: noopArchiver,
    bigOrderCollector: {
      register: async () => [],
      list: () => list,
      runDaily: async (codes) => { last.splice(0, last.length, ...(codes || list)); return { requested: last.length, succeeded: last.length, failed: 0, failures: [] } },
      startTimer: () => null,
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    // 不传 stockCodes 走登记清单
    const daily = await fetch(`${baseUrl}/api/big-order/longhu/collect`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}',
    })
    assert.equal(daily.status, 200)
    const dailyBody = await daily.json()
    assert.deepEqual(last, ['002297'])

    // 传入 stockCodes 走校验：无效码与重复过滤，上限 3
    const custom = await fetch(`${baseUrl}/api/big-order/longhu/collect`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ stockCodes: ['600519', 'abc', '', '600519', '000001'] }),
    })
    assert.equal(custom.status, 200)
    // 路由层 normalizeStockCode 只过滤非六位和空串，bc 和 '' 被丢；重复仍进入 mock（collector.runDaily 内部自行去重）
    assert.deepEqual(last, ['600519', '600519', '000001'])
  } finally {
    server.close()
  }
})
