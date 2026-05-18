import assert from 'node:assert/strict'
import test from 'node:test'

import { createProxyApp } from '../app.js'

function listen(app) {
  return new Promise((resolve) => {
    const server = app.listen(0, '127.0.0.1', () => {
      const address = server.address()
      resolve({ server, baseUrl: `http://127.0.0.1:${address.port}` })
    })
  })
}

class MemoryCache {
  constructor() {
    this.store = new Map()
    this.pending = new Map()
  }

  async get(key, { allowStale = false } = {}) {
    const entry = this.store.get(key)
    if (!entry) return null
    if (entry.stale && !allowStale) return null
    return entry
  }

  async set(key, value, options = {}) {
    this.store.set(key, {
      value,
      stale: Boolean(options.stale),
      meta: {
        ttlSeconds: options.ttlSeconds,
      },
    })
    return true
  }

  async remember(key, options, loader) {
    const cached = await this.get(key)
    if (cached) {
      return { value: cached.value, cache: { hit: true, stale: false, ttlSeconds: cached.meta.ttlSeconds } }
    }
    if (this.pending.has(key)) return this.pending.get(key)
    const pending = Promise.resolve()
      .then(loader)
      .then(async (value) => {
        await this.set(key, value, options)
        return { value, cache: { hit: false, stale: false, ttlSeconds: options.ttlSeconds } }
      })
      .catch(async (error) => {
        const stale = await this.get(key, { allowStale: true })
        if (stale) {
          return {
            value: stale.value,
            cache: {
              hit: true,
              stale: true,
              upstreamCalled: true,
              ttlSeconds: stale.meta.ttlSeconds,
            },
          }
        }
        throw error
      })
      .finally(() => {
        this.pending.delete(key)
      })
    this.pending.set(key, pending)
    return pending
  }
}

test('eastmoney hotlist is served from cache inside ttl', async () => {
  let upstreamCalls = 0
  const cache = new MemoryCache()
  const app = createProxyApp({
    logRequests: false,
    cache,
    clients: {
      client: {
        post: async () => {
          upstreamCalls += 1
          return { data: { data: [{ sc: 'SZ000001', sn: '平安银行' }] } }
        },
      },
      plainClient: {},
    },
  })

  const { server, baseUrl } = await listen(app)
  try {
    const first = await fetch(`${baseUrl}/api/eastmoney/hot`, { method: 'POST' })
    const second = await fetch(`${baseUrl}/api/eastmoney/hot`, { method: 'POST' })
    const firstBody = await first.json()
    const secondBody = await second.json()

    assert.equal(upstreamCalls, 1)
    assert.equal(firstBody.dragonMeta.cache.hit, false)
    assert.equal(secondBody.dragonMeta.cache.hit, true)
    assert.deepEqual(secondBody.data, [{ sc: 'SZ000001', sn: '平安银行' }])
  } finally {
    server.close()
  }
})

test('eastmoney quote cache key ignores code order', async () => {
  let upstreamCalls = 0
  const cache = new MemoryCache()
  const app = createProxyApp({
    logRequests: false,
    cache,
    clients: {
      client: {},
      plainClient: {
        get: async () => {
          upstreamCalls += 1
          return {
            data: {
              rc: 0,
              data: {
                diff: [
                  { f12: '000001', f14: '平安银行', f2: 10, f62: 100, f184: 1 },
                  { f12: '000002', f14: '万科A', f2: 11, f62: 200, f184: 2 },
                ],
              },
            },
          }
        },
      },
    },
  })

  const { server, baseUrl } = await listen(app)
  try {
    const first = await fetch(`${baseUrl}/api/quotes/eastmoney?codes=000001,000002`)
    const second = await fetch(`${baseUrl}/api/quotes/eastmoney?codes=000002,000001`)
    const firstBody = await first.json()
    const secondBody = await second.json()

    assert.equal(upstreamCalls, 1)
    assert.equal(firstBody.dragonMeta.cache.hit, false)
    assert.equal(secondBody.dragonMeta.cache.hit, true)
    assert.deepEqual(
      secondBody.data.diff.map((row) => row.f12),
      ['000002', '000001'],
    )
  } finally {
    server.close()
  }
})

test('tencent quote cache key ignores code order', async () => {
  let upstreamCalls = 0
  const cache = new MemoryCache()
  const app = createProxyApp({
    logRequests: false,
    cache,
    clients: {
      client: {},
      plainClient: {
        get: async () => {
          upstreamCalls += 1
          return {
            data: Buffer.from(
              [
                'v_sz000001="51~平安银行~000001~10.00~9.90~10.10~1000~0~0~100000~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~1.01~0~0~0~0~0~1.2~8~0~0~0~0~100~200~1.1~0~0";',
                'v_sz000002="51~万科A~000002~11.00~10.90~11.10~2000~0~0~200000~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0.92~0~0~0~0~0~1.4~9~0~0~0~0~110~220~1.2~0~0";',
              ].join('\n'),
              'utf8',
            ),
          }
        },
      },
    },
  })

  const { server, baseUrl } = await listen(app)
  try {
    const first = await fetch(`${baseUrl}/api/quotes/tencent?codes=000001,000002`)
    const second = await fetch(`${baseUrl}/api/quotes/tencent?codes=000002,000001`)
    const firstBody = await first.json()
    const secondBody = await second.json()

    assert.equal(upstreamCalls, 1)
    assert.equal(firstBody.dragonMeta.cache.hit, false)
    assert.equal(secondBody.dragonMeta.cache.hit, true)
    assert.deepEqual(
      secondBody.data.diff.map((row) => row.f12),
      ['000002', '000001'],
    )
  } finally {
    server.close()
  }
})

test('sina quote cache key ignores code order', async () => {
  let upstreamCalls = 0
  const cache = new MemoryCache()
  const app = createProxyApp({
    logRequests: false,
    cache,
    clients: {
      client: {},
      plainClient: {
        get: async () => {
          upstreamCalls += 1
          return {
            data: Buffer.from(
              [
                'var hq_str_sz000001="平安银行,10.00,9.90,10.10,10.20,9.80,10.09,10.10,1000,100000";',
                'var hq_str_sz000002="万科A,11.00,10.90,11.10,11.20,10.80,11.09,11.10,2000,200000";',
              ].join('\n'),
              'utf8',
            ),
          }
        },
      },
    },
  })

  const { server, baseUrl } = await listen(app)
  try {
    const first = await fetch(`${baseUrl}/api/quotes/sina?codes=000001,000002`)
    const second = await fetch(`${baseUrl}/api/quotes/sina?codes=000002,000001`)
    const firstBody = await first.json()
    const secondBody = await second.json()

    assert.equal(upstreamCalls, 1)
    assert.equal(firstBody.dragonMeta.cache.hit, false)
    assert.equal(secondBody.dragonMeta.cache.hit, true)
    assert.deepEqual(
      secondBody.data.diff.map((row) => row.f12).sort(),
      ['000001', '000002'],
    )
  } finally {
    server.close()
  }
})

test('eastmoney quote route returns stale cache when upstream fails', async () => {
  let upstreamCalls = 0
  const cache = new MemoryCache()
  await cache.set(
    'quotes:eastmoney:v1:000001',
    {
      rc: 0,
      data: { diff: [{ f12: '000001', f14: '平安银行', f2: 10, f62: 100, f184: 1 }] },
      dragonMeta: { source: 'eastmoney', route: 'ulist' },
    },
    { ttlSeconds: 30, stale: true },
  )
  const app = createProxyApp({
    logRequests: false,
    cache,
    clients: {
      client: {},
      plainClient: {
        get: async () => {
          upstreamCalls += 1
          throw new Error('blocked')
        },
      },
    },
  })

  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/quotes/eastmoney?codes=000001`)
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(upstreamCalls, 1)
    assert.equal(body.dragonMeta.cache.hit, true)
    assert.equal(body.dragonMeta.cache.stale, true)
    assert.equal(body.data.diff[0].f12, '000001')
  } finally {
    server.close()
  }
})

test('eastmoney hotlist returns stale cache when upstream fails', async () => {
  let upstreamCalls = 0
  const cache = new MemoryCache()
  await cache.set(
    'hotlist:eastmoney:v1',
    { data: [{ sc: 'SZ000001', sn: '平安银行' }] },
    { ttlSeconds: 120, stale: true },
  )
  const app = createProxyApp({
    logRequests: false,
    cache,
    clients: {
      client: {
        post: async () => {
          upstreamCalls += 1
          throw new Error('blocked')
        },
      },
      plainClient: {},
    },
  })

  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/eastmoney/hot`, { method: 'POST' })
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(upstreamCalls, 1)
    assert.equal(body.dragonMeta.cache.hit, true)
    assert.equal(body.dragonMeta.cache.stale, true)
    assert.deepEqual(body.data, [{ sc: 'SZ000001', sn: '平安银行' }])
  } finally {
    server.close()
  }
})

test('startup bundle is stored in and read from cache', async () => {
  const cache = new MemoryCache()
  const app = createProxyApp({
    logRequests: false,
    cache,
    clients: {
      client: {},
      plainClient: {},
    },
  })

  const bundle = {
    schemaVersion: 1,
    tradingDate: '2026-05-18',
    createdAt: Date.now(),
    platformData: {
      eastmoney: [{ code: '000001', name: '平安银行', rank: 1 }],
    },
    stocks: [{ code: '000001', name: '平安银行', rank: 1 }],
  }

  const { server, baseUrl } = await listen(app)
  try {
    const writeResponse = await fetch(`${baseUrl}/api/cache/startup-bundle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: 'default:2026-05-18', bundle }),
    })
    const writeBody = await writeResponse.json()
    const readResponse = await fetch(
      `${baseUrl}/api/cache/startup-bundle?key=default%3A2026-05-18`,
    )
    const readBody = await readResponse.json()

    assert.equal(writeResponse.status, 200)
    assert.equal(writeBody.ok, true)
    assert.equal(readResponse.status, 200)
    assert.equal(readBody.ok, true)
    assert.equal(readBody.dragonMeta.cache.hit, true)
    assert.deepEqual(readBody.data.stocks, bundle.stocks)
  } finally {
    server.close()
  }
})

test('startup bundle rejects unsafe cache keys without silently normalizing them', async () => {
  const cache = new MemoryCache()
  const app = createProxyApp({
    logRequests: false,
    cache,
    clients: {
      client: {},
      plainClient: {},
    },
  })
  const bundle = {
    schemaVersion: 1,
    tradingDate: '2026-05-18',
    createdAt: Date.now(),
    platformData: {
      eastmoney: [{ code: '000001', name: '平安银行', rank: 1 }],
    },
    stocks: [{ code: '000001', name: '平安银行', rank: 1 }],
  }

  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/cache/startup-bundle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: 'default/2026-05-18', bundle }),
    })
    const body = await response.json()

    assert.equal(response.status, 400)
    assert.equal(body.errorCode, 'invalid_cache_key')
    assert.equal(cache.store.size, 0)
  } finally {
    server.close()
  }
})

test('startup bundle rejects payloads whose trading date does not match the cache key', async () => {
  const cache = new MemoryCache()
  const app = createProxyApp({
    logRequests: false,
    cache,
    clients: {
      client: {},
      plainClient: {},
    },
  })
  const bundle = {
    schemaVersion: 1,
    tradingDate: '2026-05-17',
    createdAt: Date.now(),
    platformData: {
      eastmoney: [{ code: '000001', name: '平安银行', rank: 1 }],
    },
    stocks: [{ code: '000001', name: '平安银行', rank: 1 }],
  }

  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/cache/startup-bundle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: 'default:2026-05-18', bundle }),
    })
    const body = await response.json()

    assert.equal(response.status, 400)
    assert.equal(body.errorCode, 'invalid_startup_bundle')
    assert.equal(cache.store.size, 0)
  } finally {
    server.close()
  }
})

test('startup bundle read treats invalid cached payloads as a miss', async () => {
  const cache = new MemoryCache()
  await cache.set(
    'startup:bundle:v1:default:2026-05-18',
    {
      schemaVersion: 1,
      tradingDate: '2026-05-17',
      createdAt: Date.now(),
      platformData: {
        eastmoney: [{ code: '000001', name: '平安银行', rank: 1 }],
      },
      stocks: [{ code: '000001', name: '平安银行', rank: 1 }],
    },
    { ttlSeconds: 300 },
  )
  const app = createProxyApp({
    logRequests: false,
    cache,
    clients: {
      client: {},
      plainClient: {},
    },
  })

  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(
      `${baseUrl}/api/cache/startup-bundle?key=default%3A2026-05-18`,
    )
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.equal(body.data, null)
    assert.equal(body.dragonMeta.cache.hit, false)
  } finally {
    server.close()
  }
})

test('startup bundle write reports degraded when cache storage is unavailable', async () => {
  const app = createProxyApp({
    logRequests: false,
    cache: {
      enabled: () => false,
      get: async () => null,
      set: async () => false,
      remember: async () => {
        throw new Error('not used')
      },
    },
    clients: {
      client: {},
      plainClient: {},
    },
  })
  const bundle = {
    schemaVersion: 1,
    tradingDate: '2026-05-18',
    createdAt: Date.now(),
    platformData: {
      eastmoney: [{ code: '000001', name: '平安银行', rank: 1 }],
    },
    stocks: [{ code: '000001', name: '平安银行', rank: 1 }],
  }

  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/cache/startup-bundle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: 'default:2026-05-18', bundle }),
    })
    const body = await response.json()

    assert.equal(response.status, 503)
    assert.equal(body.ok, false)
    assert.equal(body.degraded, true)
    assert.equal(body.source, 'startup-cache')
  } finally {
    server.close()
  }
})

test('startup bundle rejects stale payloads before writing cache', async () => {
  const cache = new MemoryCache()
  const app = createProxyApp({
    logRequests: false,
    cache,
    clients: {
      client: {},
      plainClient: {},
    },
  })
  const bundle = {
    schemaVersion: 1,
    tradingDate: '2026-05-18',
    createdAt: Date.now() - 31 * 60 * 1000,
    platformData: {
      eastmoney: [{ code: '000001', name: '平安银行', rank: 1 }],
    },
    stocks: [{ code: '000001', name: '平安银行', rank: 1 }],
  }

  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/cache/startup-bundle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: 'default:2026-05-18', bundle }),
    })
    const body = await response.json()

    assert.equal(response.status, 400)
    assert.equal(body.errorCode, 'invalid_startup_bundle')
    assert.equal(cache.store.size, 0)
  } finally {
    server.close()
  }
})

test('eastmoney quote route coalesces concurrent cache misses', async () => {
  let upstreamCalls = 0
  let release
  const gate = new Promise((resolve) => {
    release = resolve
  })
  const cache = new MemoryCache()
  const app = createProxyApp({
    logRequests: false,
    cache,
    clients: {
      client: {},
      plainClient: {
        get: async () => {
          upstreamCalls += 1
          await gate
          return {
            data: {
              rc: 0,
              data: {
                diff: [{ f12: '000001', f14: '平安银行', f2: 10, f62: 100, f184: 1 }],
              },
            },
          }
        },
      },
    },
  })

  const { server, baseUrl } = await listen(app)
  try {
    const first = fetch(`${baseUrl}/api/quotes/eastmoney?codes=000001`)
    const second = fetch(`${baseUrl}/api/quotes/eastmoney?codes=000001`)
    while (upstreamCalls === 0) {
      await new Promise((resolve) => setTimeout(resolve, 1))
    }
    await new Promise((resolve) => setTimeout(resolve, 10))
    release()
    const [firstBody, secondBody] = await Promise.all([
      first.then((response) => response.json()),
      second.then((response) => response.json()),
    ])

    assert.equal(upstreamCalls, 1)
    assert.equal(firstBody.dragonMeta.cache.hit, false)
    assert.equal(secondBody.dragonMeta.cache.hit, false)
    assert.equal(secondBody.data.diff[0].f12, '000001')
  } finally {
    server.close()
  }
})

test('eastmoney quote route applies configured proxy only to eastmoney requests', async () => {
  const calls = []
  const app = createProxyApp({
    logRequests: false,
    readConfig: (name, fallback = '') =>
      name === 'EASTMONEY_PROXY_URL' ? 'http://127.0.0.1:7890' : fallback,
    clients: {
      client: {},
      plainClient: {
        get: async (url, config = {}) => {
          calls.push({ url, proxy: config.proxy })
          if (url.includes('qt.gtimg.cn')) {
            return {
              data: Buffer.from(
                'v_sz000001="51~平安银行~000001~10.00~9.90~10.10~1000~0~0~100000~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~1.01~0~0~0~0~0~1.2~8~0~0~0~0~100~200~1.1";\n',
                'utf8',
              ),
            }
          }
          return {
            data: {
              rc: 0,
              data: {
                diff: [{ f12: '000001', f14: '平安银行', f2: 10, f62: 100, f184: 1 }],
              },
            },
          }
        },
      },
    },
  })

  const { server, baseUrl } = await listen(app)
  try {
    await fetch(`${baseUrl}/api/quotes/eastmoney?codes=000001`)
    await fetch(`${baseUrl}/api/quotes/tencent?codes=000001`)

    assert.equal(calls.length, 2)
    assert.match(calls[0].url, /eastmoney\.com/)
    assert.deepEqual(calls[0].proxy, {
      protocol: 'http',
      host: '127.0.0.1',
      port: 7890,
    })
    assert.match(calls[1].url, /qt\.gtimg\.cn/)
    assert.equal(calls[1].proxy, undefined)
  } finally {
    server.close()
  }
})
