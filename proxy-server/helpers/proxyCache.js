import crypto from 'node:crypto'

const DEFAULT_PREFIX = 'hellobiga:dragon-board:proxy'

export const PROXY_CACHE_TTLS = {
  hotlist: {
    eastmoney: 120,
    default: 180,
    empty: 15,
  },
  quotes: {
    eastmoneyResponse: 35,
    eastmoneyHistFlow: 300,
    tencentResponse: 5,
    sinaResponse: 5,
    sinaMoneyFlow: 60,
    sinaMoneyFlowStale: 1800,
    empty: 10,
  },
  startupBundle: {
    default: 300,
    stale: 1800,
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

  async set(key, value, { ttlSeconds, staleTtlSeconds, stale = false } = {}) {
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
