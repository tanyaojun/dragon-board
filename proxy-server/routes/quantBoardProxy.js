import { hashCachePayload, normalizeCodeCacheKey } from '../helpers/proxyCache.js'

const DEFAULT_QUANT_BOARD_TARGET = 'http://127.0.0.1:8000'

const QUANT_BOARD_PREFIXES = [
  '/api/ranktrend/',
  '/api/snapshots/',
  '/api/themes/mapping',
  '/api/themes/heat',
  '/api/research/',
  '/api/stocks/',
  '/api/journal/',
]

/** Proxy 层 Redis 缓存的只读 GET 端点 */
const CACHEABLE_RESOURCES = [
  { path: '/api/ranktrend/rank-series', ttlSeconds: 7200 },
  { path: '/api/themes/heat', ttlSeconds: 30 },
  { path: '/api/themes/mapping', ttlSeconds: 14400 },
  { path: '/api/snapshots/counts', ttlSeconds: 600 },
]

function resolveCacheableResource(requestPath) {
  return CACHEABLE_RESOURCES.find(
    (resource) => requestPath === resource.path || requestPath.startsWith(resource.path + '?'),
  )
}

export function shouldProxyToQuantBoard(path) {
  return QUANT_BOARD_PREFIXES.some((prefix) => path === prefix || path.startsWith(prefix))
}

export function quantBoardTargetBase() {
  return String(process.env.QUANT_BOARD_API_BASE || DEFAULT_QUANT_BOARD_TARGET).replace(/\/+$/, '')
}

function copyResponseHeaders(upstream, res) {
  for (const [key, value] of upstream.headers.entries()) {
    const lowerKey = key.toLowerCase()
    if (
      lowerKey === 'content-encoding' ||
      lowerKey === 'content-length' ||
      lowerKey === 'transfer-encoding'
    ) {
      continue
    }
    res.setHeader(key, value)
  }
}

function buildCacheKey(resourcePath, query) {
  switch (resourcePath) {
    case '/api/ranktrend/rank-series': {
      const codes = normalizeCodeCacheKey(
        String(query.codes || '')
          .split(',')
          .filter(Boolean),
      )
      const payload = {
        dataset_id: query.dataset_id || query.datasetId || '',
        type: query.type || 'half_hour',
        sort: query.sort || 'desc',
        limit: query.limit || '',
        windowBars: query.windowBars || '',
        codes,
      }
      const digest = hashCachePayload(payload)
      return `proxy:ranktrend:rank-series:${digest}`
    }
    case '/api/themes/heat': {
      const payload = { force: query.force || '' }
      const digest = hashCachePayload(payload)
      return `proxy:themes:heat:${digest}`
    }
    case '/api/themes/mapping': {
      return 'proxy:themes:mapping:v1'
    }
    case '/api/snapshots/counts': {
      const payload = { dataset_id: query.dataset_id || query.datasetId || '' }
      const digest = hashCachePayload(payload)
      return `proxy:snapshots:counts:${digest}`
    }
    default:
      return `proxy:${resourcePath.replace(/\//g, ':')}:v1`
  }
}

/** 缓存失败日志限流：同一条消息在 intervalMs 内最多输出一次 */
function createRateLimitedLogger(intervalMs = 30000) {
  let lastMessage = ''
  let lastTime = 0
  return (message) => {
    const now = Date.now()
    if (message === lastMessage && now - lastTime < intervalMs) return
    lastMessage = message
    lastTime = now
    console.warn(message)
  }
}

const cacheFailureLog = createRateLimitedLogger(30000)

export function registerQuantBoardProxyRoutes(app, { fetchImpl, cache, runtimeCache, now } = {}) {
  app.use('/api', async (req, res, next) => {
    const requestPath = new URL(req.originalUrl, 'http://127.0.0.1').pathname
    if (!shouldProxyToQuantBoard(requestPath)) {
      next()
      return
    }

    const fetcher = fetchImpl || globalThis.fetch
    if (typeof fetcher !== 'function') {
      res.status(503).json({
        ok: false,
        degraded: true,
        source: 'quant-board-proxy',
        errorCode: 'quant_board_fetch_unavailable',
        message: 'quant board proxy fetch unavailable',
      })
      return
    }

    // --- Redis 缓存路径（仅对可缓存的只读 GET 请求）---
    const cacheableResource =
      req.method === 'GET' ? resolveCacheableResource(requestPath) : null
    const effectiveCache = cache?.enabled?.() ? cache : runtimeCache

    if (cacheableResource && effectiveCache?.enabled?.()) {
      const cacheKey = buildCacheKey(requestPath, req.query)
      const cacheOptions = {
        ttlSeconds: cacheableResource.ttlSeconds,
        staleTtlSeconds: cacheableResource.ttlSeconds * 2,
      }

      try {
        const result = await effectiveCache.remember(cacheKey, cacheOptions, async () => {
          const targetUrl = `${quantBoardTargetBase()}${req.originalUrl}`
          const headers = { ...req.headers }
          delete headers.host
          delete headers['content-length']

          const upstream = await fetcher(targetUrl, { method: 'GET', headers })
          const body = Buffer.from(await upstream.arrayBuffer())

          // 只缓存 2xx 成功响应，避免将 4xx/5xx 错误缓存
          if (!upstream.ok) {
            const errorPreview = body.toString('utf8').slice(0, 300)
            throw new Error(`upstream returned ${upstream.status}: ${errorPreview}`)
          }

          return {
            status: upstream.status,
            headers: Object.fromEntries(
              Array.from(upstream.headers.entries()).filter(
                ([key]) =>
                  !['content-encoding', 'content-length', 'transfer-encoding'].includes(
                    key.toLowerCase(),
                  ),
              ),
            ),
            body: body.toString('utf8'),
          }
        })

        const cached = result.value
        for (const [key, value] of Object.entries(cached.headers || {})) {
          res.setHeader(key, value)
        }
        res.status(cached.status || 200)
        res.send(Buffer.from(cached.body || '', 'utf8'))
        return
      } catch (error) {
        // 缓存层失败时回退到直通模式（含上游非 2xx 响应）
        cacheFailureLog(`[quant-board-proxy] 缓存读取失败，回退直通: ${error?.message || error}`)
      }
    }

    // --- 直通模式（非缓存路径 / 缓存失败回退）---
    const targetUrl = `${quantBoardTargetBase()}${req.originalUrl}`
    const headers = { ...req.headers }
    delete headers.host
    delete headers['content-length']

    try {
      const init = {
        method: req.method,
        headers,
      }

      if (!['GET', 'HEAD'].includes(req.method)) {
        if (req.is('application/json') && req.body !== undefined) {
          init.body = JSON.stringify(req.body)
        } else {
          init.body = req
          init.duplex = 'half'
        }
      }

      const upstream = await fetcher(targetUrl, init)
      copyResponseHeaders(upstream, res)
      res.status(upstream.status)

      if (req.method === 'HEAD') {
        res.end()
        return
      }

      const buffer = Buffer.from(await upstream.arrayBuffer())
      res.send(buffer)
    } catch (error) {
      res.status(502).json({
        ok: false,
        degraded: true,
        source: 'quant-board-proxy',
        errorCode: 'quant_board_proxy_failed',
        message: error instanceof Error ? error.message : String(error),
      })
    }
  })
}
