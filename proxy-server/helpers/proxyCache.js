import crypto from 'node:crypto'

const DEFAULT_PREFIX = 'hellobiga:dragon-board:proxy'

export const PROXY_CACHE_TTLS = {
  hotlist: {
    eastmoney: 120,
    default: 180,
    empty: 15,
  },
  quotes: {
    // 60s TTL 配合前端 10s 刷新：6 次刷新仅 1 次触发上游，其余全部 Redis 命中
    eastmoneyResponse: 60,
    eastmoneyHistFlow: 300,
    tencentResponse: 60,
    tencentMinute: 60,
    sinaResponse: 60,
    empty: 10,
  },
  startupBundle: {
    default: 300,
    stale: 1800,
  },
  bigOrder: {
    thsDetail: 30,
    longhuPage: 10,
    longhuAllDay: 10,
    longhuEmpty: 5,
  },
  market: {
    thsLimitUp: 30,
    thsPools: 30,
    overview: 30,
    sentimentComposite: 30,
    surgeStock: 30,
  },
}

export function normalizeCodeCacheKey(codes) {
  return Array.from(new Set((codes || []).map((code) => String(code || '').replace(/[^0-9]/g, '')).filter(Boolean)))
    .sort()
    .join(',')
}

export function hashCachePayload(payload) {
  return crypto
    .createHash('sha256')
    .update(JSON.stringify(payload))
    .digest('hex')
    .slice(0, 24)
}

export function attachCacheMeta(data, cacheMeta = {}) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return data
  return {
    ...data,
    dragonMeta: {
      ...(data.dragonMeta || {}),
      cache: {
        store: cacheMeta.store || 'redis',
        hit: Boolean(cacheMeta.hit),
        stale: Boolean(cacheMeta.stale),
        ageSeconds: cacheMeta.ageSeconds,
        uiStale: Boolean(cacheMeta.uiStale),
        upstreamCalled: Boolean(cacheMeta.upstreamCalled),
        ttlSeconds: cacheMeta.ttlSeconds,
      },
    },
  }
}

export class ProxyRedisCache {
  constructor({ redisClient = null, prefix = DEFAULT_PREFIX, now = () => Date.now() } = {}) {
    this.redisClient = redisClient
    this.prefix = String(prefix || DEFAULT_PREFIX).replace(/:+$/, '')
    this.now = now
    this.pending = new Map()
  }

  enabled() {
    return Boolean(this.redisClient)
  }

  fullKey(key) {
    return `${this.prefix}:${key}`
  }

  async get(key, { allowStale = false } = {}) {
    if (!this.redisClient) return null
    try {
      const raw = await this.redisClient.get(this.fullKey(key))
      if (!raw) return null
      const entry = JSON.parse(typeof raw === 'string' ? raw : raw.toString('utf8'))
      if (!entry || typeof entry !== 'object') return null
      const expiresAt = Number(entry.expiresAt) || 0
      const staleUntil = Number(entry.staleUntil) || 0
      const now = this.now()
      if (expiresAt > now) {
        return {
          value: entry.value,
          stale: false,
          meta: {
            ttlSeconds: entry.ttlSeconds,
          },
        }
      }
      if (allowStale && staleUntil > now) {
        return {
          value: entry.value,
          stale: true,
          meta: {
            ttlSeconds: entry.ttlSeconds,
          },
        }
      }
      return null
    } catch {
      return null
    }
  }

  async set(
    key,
    value,
    {
      ttlSeconds,
      staleTtlSeconds,
      stale = false,
      maxValueBytes = Number.POSITIVE_INFINITY,
    } = {},
  ) {
    if (!this.redisClient) return false
    const ttl = Math.max(1, Number(ttlSeconds) || 1)
    const staleTtl = Math.max(ttl, Number(staleTtlSeconds) || ttl * 3)
    const now = this.now()
    const payload = JSON.stringify({
      value,
      ttlSeconds: ttl,
      expiresAt: stale ? now - 1 : now + ttl * 1000,
      staleUntil: now + staleTtl * 1000,
    })
    if (Number.isFinite(maxValueBytes) && Buffer.byteLength(payload, 'utf8') > maxValueBytes) {
      return false
    }
    try {
      await this.redisClient.setEx(this.fullKey(key), staleTtl, payload)
      return true
    } catch {
      return false
    }
  }

  async remember(key, options, loader) {
    const cached = await this.get(key)
    if (cached) {
      return {
        value: cached.value,
        cache: {
          hit: true,
          stale: false,
          ttlSeconds: cached.meta?.ttlSeconds,
        },
      }
    }

    if (this.pending.has(key)) return this.pending.get(key)

    const pending = Promise.resolve()
      .then(loader)
      .then(async (value) => {
        await this.set(key, value, options)
        return {
          value,
          cache: {
            hit: false,
            stale: false,
            ttlSeconds: options?.ttlSeconds,
          },
        }
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
              ttlSeconds: stale.meta?.ttlSeconds || options?.ttlSeconds,
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

export class ProcessMemoryCache {
  constructor({
    now = () => Date.now(),
    maxEntries = 500,
    maxBytes = Number.POSITIVE_INFINITY,
    maxValueBytes = Number.POSITIVE_INFINITY,
    estimateSize = (value) => Buffer.byteLength(JSON.stringify(value), 'utf8'),
  } = {}) {
    this.now = now
    this.maxEntries = Math.max(1, Number(maxEntries) || 500)
    this.maxBytes = Number.isFinite(maxBytes) ? Math.max(1, maxBytes) : Number.POSITIVE_INFINITY
    this.maxValueBytes = Number.isFinite(maxValueBytes)
      ? Math.max(1, maxValueBytes)
      : Number.POSITIVE_INFINITY
    this.estimateSize = estimateSize
    this.totalBytes = 0
    this.store = new Map()
    this.pending = new Map()
  }

  enabled() {
    return true
  }

  async get(key, { allowStale = false } = {}) {
    const entry = this.store.get(key)
    if (!entry) return null
    const now = this.now()
    if (entry.expiresAt > now) {
      return { value: entry.value, stale: false, meta: { ttlSeconds: entry.ttlSeconds } }
    }
    if (allowStale && entry.staleUntil > now) {
      return { value: entry.value, stale: true, meta: { ttlSeconds: entry.ttlSeconds } }
    }
    if (entry.staleUntil <= now) this.deleteEntry(key)
    return null
  }

  async set(key, value, { ttlSeconds, staleTtlSeconds, stale = false } = {}) {
    const ttl = Math.max(1, Number(ttlSeconds) || 1)
    const staleTtl = Math.max(ttl, Number(staleTtlSeconds) || ttl * 3)
    const now = this.now()
    let sizeBytes
    try {
      sizeBytes = Math.max(0, Number(this.estimateSize(value)) || 0)
    } catch {
      return false
    }
    if (sizeBytes > this.maxValueBytes || sizeBytes > this.maxBytes) return false
    for (const [entryKey, entry] of this.store) {
      if (entry.staleUntil <= now) this.deleteEntry(entryKey)
    }
    if (this.store.has(key)) this.deleteEntry(key)
    while (
      this.store.size > 0 &&
      (this.store.size >= this.maxEntries || this.totalBytes + sizeBytes > this.maxBytes)
    ) {
      this.deleteEntry(this.store.keys().next().value)
    }
    this.store.set(key, {
      value,
      sizeBytes,
      ttlSeconds: ttl,
      expiresAt: stale ? now - 1 : now + ttl * 1000,
      staleUntil: now + staleTtl * 1000,
    })
    this.totalBytes += sizeBytes
    return true
  }

  deleteEntry(key) {
    const entry = this.store.get(key)
    if (!entry) return
    this.totalBytes = Math.max(0, this.totalBytes - (entry.sizeBytes || 0))
    this.store.delete(key)
  }

  async remember(key, options, loader) {
    const cached = await this.get(key)
    if (cached) {
      return {
        value: cached.value,
        cache: { hit: true, stale: false, ttlSeconds: cached.meta?.ttlSeconds },
      }
    }

    if (this.pending.has(key)) return this.pending.get(key)

    const pending = Promise.resolve()
      .then(loader)
      .then(async (value) => {
        await this.set(key, value, options)
        return {
          value,
          cache: { hit: false, stale: false, upstreamCalled: true, ttlSeconds: options?.ttlSeconds },
        }
      })
      .catch(async (error) => {
        const stale = await this.get(key, { allowStale: true })
        if (!stale) throw error
        return {
          value: stale.value,
          cache: {
            hit: true,
            stale: true,
            upstreamCalled: true,
            ttlSeconds: stale.meta?.ttlSeconds || options?.ttlSeconds,
          },
        }
      })
      .finally(() => this.pending.delete(key))

    this.pending.set(key, pending)
    return pending
  }
}

export class LayeredProxyCache {
  constructor({ memoryCache, redisCache } = {}) {
    this.memoryCache = memoryCache || new ProcessMemoryCache()
    this.redisCache = redisCache || new ProxyRedisCache()
    this.pending = new Map()
  }

  enabled() {
    return true
  }

  async get(key, { allowStale = false } = {}) {
    const memory = await this.memoryCache.get(key, { allowStale })
    if (memory && !memory.stale) return { ...memory, store: 'memory' }

    const redis = await this.redisCache.get(key, { allowStale })
    if (redis && !redis.stale) {
      await this.memoryCache.set(key, redis.value, {
        ttlSeconds: redis.meta?.ttlSeconds,
        staleTtlSeconds: (redis.meta?.ttlSeconds || 1) * 3,
      })
      return { ...redis, store: 'redis' }
    }
    if (memory) return { ...memory, store: 'memory' }
    if (redis) {
      await this.memoryCache.set(key, redis.value, {
        ttlSeconds: redis.meta?.ttlSeconds,
        staleTtlSeconds: (redis.meta?.ttlSeconds || 1) * 3,
        stale: true,
      })
      return { ...redis, store: 'redis' }
    }
    return null
  }

  async set(key, value, options) {
    const [memory, redis] = await Promise.all([
      this.memoryCache.set(key, value, options),
      this.redisCache.set(key, value, options),
    ])
    return memory || redis
  }

  async remember(key, options, loader) {
    const cached = await this.get(key, { allowStale: true })
    if (cached && !cached.stale) {
      return {
        value: cached.value,
        cache: {
          hit: true,
          stale: false,
          store: cached.store,
          upstreamCalled: false,
          ttlSeconds: cached.meta?.ttlSeconds,
        },
      }
    }
    if (cached?.stale) {
      this.refresh(key, options, loader).catch(() => {})
      return {
        value: cached.value,
        cache: {
          hit: true,
          stale: true,
          store: cached.store,
          upstreamCalled: false,
          ttlSeconds: cached.meta?.ttlSeconds,
        },
      }
    }
    return this.refresh(key, options, loader)
  }

  async refresh(key, options, loader) {
    if (this.pending.has(key)) return this.pending.get(key)
    const pending = Promise.resolve()
      .then(loader)
      .then(async (value) => {
        await this.set(key, value, options)
        return {
          value,
          cache: {
            hit: false,
            stale: false,
            store: 'upstream',
            upstreamCalled: true,
            ttlSeconds: options?.ttlSeconds,
          },
        }
      })
      .finally(() => this.pending.delete(key))
    this.pending.set(key, pending)
    return pending
  }
}

export async function createProxyRedisCache({ readConfig } = {}) {
  const redisUrl = readConfig?.('PROXY_REDIS_URL') || readConfig?.('REDIS_URL') || ''
  const enabled = (readConfig?.('PROXY_CACHE_ENABLED', 'true') || 'true').toLowerCase() !== 'false'
  if (!enabled || !redisUrl) return new ProxyRedisCache()

  try {
    const redis = await import('redis')
    const client = redis.createClient({ url: redisUrl })
    client.on('error', () => {})
    await client.connect()
    return new ProxyRedisCache({
      redisClient: client,
      prefix: readConfig?.('PROXY_REDIS_KEY_PREFIX') || DEFAULT_PREFIX,
    })
  } catch {
    return new ProxyRedisCache()
  }
}
