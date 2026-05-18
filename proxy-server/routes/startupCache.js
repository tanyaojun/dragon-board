import { attachCacheMeta, PROXY_CACHE_TTLS } from '../helpers/proxyCache.js'
import { sendBadRequest, sendDegraded } from '../helpers/response.js'

const STARTUP_BUNDLE_SCHEMA_VERSION = 1
const STARTUP_CACHE_KEY_PATTERN = /^[0-9A-Za-z:_-]{1,120}$/
const TRADING_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/
const MAX_STARTUP_BUNDLE_AGE_MS = PROXY_CACHE_TTLS.startupBundle.stale * 1000

function parseStartupCacheKey(key) {
  const value = String(key || '')
  if (!value) return { errorCode: 'missing_cache_key', message: '缺少 key 参数' }
  if (!STARTUP_CACHE_KEY_PATTERN.test(value)) {
    return {
      errorCode: 'invalid_cache_key',
      message: 'key 只能包含数字、字母、冒号、下划线和中划线，长度 1-120',
    }
  }
  return { key: value }
}

function tradingDateFromKey(key) {
  const match = String(key || '').match(/(?:^|:)(\d{4}-\d{2}-\d{2})$/)
  return match?.[1] || null
}

function validateBundle(bundle, key) {
  if (!bundle || typeof bundle !== 'object' || Array.isArray(bundle)) return false
  if (Number(bundle.schemaVersion) !== STARTUP_BUNDLE_SCHEMA_VERSION) return false
  if (!TRADING_DATE_PATTERN.test(String(bundle.tradingDate || ''))) return false
  const keyTradingDate = tradingDateFromKey(key)
  if (keyTradingDate && bundle.tradingDate !== keyTradingDate) return false
  const createdAt = Number(bundle.createdAt)
  if (!Number.isFinite(createdAt) || createdAt <= 0) return false
  const ageMs = Date.now() - createdAt
  if (!Number.isFinite(ageMs) || ageMs < 0 || ageMs > MAX_STARTUP_BUNDLE_AGE_MS) return false
  if (!Array.isArray(bundle.stocks) || !bundle.stocks.length) return false
  if (!bundle.platformData || typeof bundle.platformData !== 'object' || Array.isArray(bundle.platformData)) return false
  if (!Object.values(bundle.platformData).every((rows) => Array.isArray(rows))) return false
  return true
}

export function registerStartupCacheRoutes(app, { cache }) {
  app.get('/api/cache/startup-bundle', async (req, res) => {
    const keyResult = parseStartupCacheKey(req.query.key)
    if (!keyResult.key) {
      sendBadRequest(res, keyResult.errorCode, keyResult.message)
      return
    }
    const key = keyResult.key

    const cached = await cache.get(`startup:bundle:v1:${key}`, { allowStale: true })
    if (!cached || !validateBundle(cached.value, key)) {
      res.json({
        ok: true,
        data: null,
        dragonMeta: {
          cache: {
            store: 'redis',
            hit: false,
            stale: false,
            ttlSeconds: PROXY_CACHE_TTLS.startupBundle.default,
          },
        },
      })
      return
    }

    res.json(
      attachCacheMeta(
        {
          ok: true,
          data: cached.value,
        },
        {
          store: 'redis',
          hit: true,
          stale: cached.stale,
          ttlSeconds: cached.meta?.ttlSeconds || PROXY_CACHE_TTLS.startupBundle.default,
        },
      ),
    )
  })

  app.post('/api/cache/startup-bundle', async (req, res) => {
    const keyResult = parseStartupCacheKey(req.body?.key)
    const bundle = req.body?.bundle
    if (!keyResult.key) {
      sendBadRequest(res, keyResult.errorCode, keyResult.message)
      return
    }
    const key = keyResult.key
    if (!validateBundle(bundle, key)) {
      sendBadRequest(res, 'invalid_startup_bundle', 'startup bundle 数据结构无效')
      return
    }
    if (typeof cache.enabled === 'function' && !cache.enabled()) {
      sendDegraded(
        res,
        {
          source: 'startup-cache',
          error: new Error('cache storage unavailable'),
          fallbackData: null,
          message: 'startup cache storage unavailable',
        },
        503,
      )
      return
    }

    const ttlSeconds = PROXY_CACHE_TTLS.startupBundle.default
    const stored = await cache.set(`startup:bundle:v1:${key}`, bundle, {
      ttlSeconds,
      staleTtlSeconds: PROXY_CACHE_TTLS.startupBundle.stale,
    })
    if (stored === false) {
      sendDegraded(
        res,
        {
          source: 'startup-cache',
          error: new Error('cache storage write failed'),
          fallbackData: null,
          message: 'startup cache storage write failed',
        },
        503,
      )
      return
    }

    res.json({
      ok: true,
      data: {
        key,
        schemaVersion: STARTUP_BUNDLE_SCHEMA_VERSION,
      },
      dragonMeta: {
        cache: {
          store: 'redis',
          hit: false,
          stale: false,
          ttlSeconds,
        },
      },
    })
  })
}
