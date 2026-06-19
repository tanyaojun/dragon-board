import express from 'express'
import cors from 'cors'
import { fileURLToPath } from 'url'
import { existsSync } from 'fs'
import { dirname, join, resolve } from 'path'

import {
  createConfigReader,
  createHttpClients,
  loadEnvFile,
} from './helpers/http.js'
import { ProcessMemoryCache, ProxyRedisCache } from './helpers/proxyCache.js'
import { buildBadRequestEnvelope } from './helpers/response.js'
import { registerBigOrderRoutes } from './routes/bigOrder.js'
import { registerDeprecatedRoutes } from './routes/deprecated.js'
import { registerDocsRoutes } from './routes/docs.js'
import { registerHotlistRoutes } from './routes/hotlists.js'
import { registerJumpSignalRoutes } from './routes/jumpSignalNotifications.js'
import { registerLocalVoiceRoutes } from './routes/localVoice.js'
import { registerMarketRoutes } from './routes/market.js'
import { registerNotificationRoutes } from './routes/notifications.js'
import { registerOpeningSignalRoutes } from './routes/openingSignals.js'
import { registerQuantBoardProxyRoutes } from './routes/quantBoardProxy.js'
import { registerQuoteRoutes } from './routes/quotes.js'
import { registerStartupCacheRoutes } from './routes/startupCache.js'
import { registerTdxBlockRoutes } from './routes/tdxBlocks.js'
import { registerTdxRoutes } from './routes/tdx.js'
import { registerXuangubaoRoutes } from './routes/xuangubao.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const frontendDistDir = resolve(__dirname, '..', 'dist')
const frontendIndexHtml = join(frontendDistDir, 'index.html')

export function createProxyApp(options = {}) {
  const app = express()
  const port = Number(options.port || process.env.PORT || 3000)
  const localEnv = options.localEnv || loadEnvFile(join(__dirname, '.env.local'))
  const readConfig = options.readConfig || createConfigReader(localEnv)
  const clients = options.clients || createHttpClients()
  const cache = options.cache || new ProxyRedisCache()
  const runtimeCache = options.runtimeCache || new ProcessMemoryCache({ now: options.now })
  const context = {
    client: clients.client,
    plainClient: clients.plainClient,
    readConfig,
    cache,
    runtimeCache,
    now: options.now || (() => Date.now()),
    port,
    localVoice: options.localVoice,
    feishuEventRadar: options.feishuEventRadar,
    eventRadarBackgroundWorker: options.eventRadarBackgroundWorker,
    fetchImpl: options.fetchImpl,
    openingSignalStore: options.openingSignalStore,
  }

  app.use(cors({ origin: '*', methods: ['GET', 'POST'] }))
  app.use(express.json({ limit: '2mb' }))

  if (options.logRequests !== false) {
    app.use((req, res, next) => {
      console.log(`[${new Date().toLocaleTimeString()}] ${req.method} ${req.url}`)
      next()
    })
  }

  app.get('/health', (req, res) => {
    res.json({
      ok: true,
      status: 'ok',
      service: 'stock-proxy-server',
      port,
      time: new Date().toLocaleString(),
      externalProbeOnStartup: false,
      xueqiuCookieConfigured: Boolean(readConfig('XUEQIU_COOKIE')),
    })
  })

  registerDocsRoutes(app, context)
  registerHotlistRoutes(app, context)
  registerQuoteRoutes(app, context)
  registerStartupCacheRoutes(app, context)
  registerDeprecatedRoutes(app, context)
  registerBigOrderRoutes(app, context)
  registerLocalVoiceRoutes(app, context)
  registerNotificationRoutes(app, context)
  registerJumpSignalRoutes(app, context)
  registerOpeningSignalRoutes(app, context)
  registerTdxBlockRoutes(app, context)
  registerTdxRoutes(app, context)
  registerMarketRoutes(app, context)
  registerXuangubaoRoutes(app, context)
  registerQuantBoardProxyRoutes(app, context)

  app.use('/static', express.static(join(__dirname, 'public')))

  if (existsSync(frontendIndexHtml)) {
    app.use(express.static(frontendDistDir))
    app.get('*', (req, res, next) => {
      if (req.path.startsWith('/api/') || req.path === '/openapi.json' || req.path === '/docs') {
        next()
        return
      }
      res.sendFile(frontendIndexHtml)
    })
  }

  app.use((req, res) => {
    res.status(404).json(
      buildBadRequestEnvelope('proxy_route_not_found', `proxy route not found: ${req.method} ${req.path}`),
    )
  })

  app.use((error, req, res, next) => {
    if (!error) {
      next()
      return
    }
    if (error.type === 'entity.too.large') {
      res.status(413).json({
        ok: false,
        degraded: false,
        source: 'proxy',
        errorCode: 'proxy_payload_too_large',
        message: 'request payload exceeds proxy json limit',
      })
      return
    }
    res.status(error.status || 500).json({
      ok: false,
      degraded: false,
      source: 'proxy',
      errorCode: 'proxy_unhandled_error',
      message: error.message || String(error),
    })
  })

  return app
}
