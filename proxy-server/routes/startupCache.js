import { attachCacheMeta, PROXY_CACHE_TTLS } from '../helpers/proxyCache.js'
import { sendBadRequest } from '../helpers/response.js'

const STARTUP_BUNDLE_SCHEMA_VERSION = 1

function normalizeStartupCacheKey(key) {
  return String(key || '').replace(/[^0-9A-Za-z:_-]/g, '').slice(0, 120)
}

function validateBundle(bundle) {
  if (!bundle || typeof bundle !== 'object' || Array.isArray(bundle)) return false
  if (Number(bundle.schemaVersion) !== STARTUP_BUNDLE_SCHEMA_VERSION) return false
  if (!Array.isArray(bundle.stocks) || !bundle.stocks.length) return false
  if (!bundle.platformData || typeof bundle.platformData !== 'object') return false
  return true
}

export function registerStartupCacheRoutes(app, { cache }) {
  app.get('/api/cache/startup-bundle', async (req, res) => {
    const key = normalizeStartupCacheKey(req.query.key)
    if (!key) {
      sendBadRequest(res, 'missing_cache_key', '缺少 key 参数')
      return
    }

    const cached = await cache.get(`startup:bundle:v1:${key}`, { allowStale: true })
    if (!cached) {
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
    const key = normalizeStartupCacheKey(req.body?.key)
    const bundle = req.body?.bundle
    if (!key) {
      sendBadRequest(res, 'missing_cache_key', '缺少 key 参数')
      return
    }
    if (!validateBundle(bundle)) {
      sendBadRequest(res, 'invalid_startup_bundle', 'startup bundle 数据结构无效')
      return
    }

    const ttlSeconds = PROXY_CACHE_TTLS.startupBundle.default
    await cache.set(`startup:bundle:v1:${key}`, bundle, {
      ttlSeconds,
      staleTtlSeconds: PROXY_CACHE_TTLS.startupBundle.stale,
    })

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
