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

export function registerQuantBoardProxyRoutes(app, { fetchImpl } = {}) {
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
