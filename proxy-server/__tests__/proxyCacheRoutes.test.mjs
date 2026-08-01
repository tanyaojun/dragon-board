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

test('startup bundle accepts a complete fact package larger than 2 MB', async () => {
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
    snapshotContext: {
      marketData: {
        completeFactPackage: 'x'.repeat(3 * 1024 * 1024),
      },
    },
  }

  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/cache/startup-bundle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: 'default:2026-05-18', bundle }),
    })

    assert.equal(response.status, 200)
    assert.equal(cache.store.size, 1)
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
