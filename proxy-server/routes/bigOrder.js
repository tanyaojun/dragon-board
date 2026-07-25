import { LayeredProxyCache, ProcessMemoryCache } from '../helpers/proxyCache.js'
import { sendBadRequest, sendDegraded } from '../helpers/response.js'
import { createBigOrderArchiver } from '../services/bigOrderArchive.js'
import { createBigOrderCollector } from '../services/bigOrderCollector.js'
import { createLonghuBigOrderService } from '../services/longhuBigOrderCache.js'

function normalizeStockCode(value) {
  const code = String(value || '').trim()
  return /^\d{6}$/.test(code) ? code : ''
}

function uiStaleThresholdMs(timestamp) {
  const date = new Date(timestamp)
  const weekday = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    weekday: 'short',
  }).format(date)
  if (weekday === 'Sat' || weekday === 'Sun') return 12 * 60 * 60 * 1000
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  const hour = Number(parts.find((part) => part.type === 'hour')?.value || 0)
  const minute = Number(parts.find((part) => part.type === 'minute')?.value || 0)
  const clock = hour * 60 + minute
  const trading =
    (clock >= 570 && clock <= 690) ||
    (clock >= 780 && clock <= 900)
  if (trading) return 30_000
  if ((clock >= 540 && clock < 570) || (clock > 690 && clock < 780)) return 300_000
  return 12 * 60 * 60 * 1000
}

export function registerBigOrderRoutes(
  app,
  {
    plainClient,
    cache,
    runtimeCache,
    readConfig,
    now = () => Date.now(),
    bigOrderArchiver = null,
    bigOrderCollector = null,
  },
) {
  const archiver = bigOrderArchiver || createBigOrderArchiver()
  const longhuCache = new LayeredProxyCache({
    memoryCache: new ProcessMemoryCache({
      now,
      maxEntries: 24,
      maxBytes: 96 * 1024 * 1024,
      maxValueBytes: 8 * 1024 * 1024,
    }),
    redisCache: cache,
  })
  const longhuService = createLonghuBigOrderService({
    plainClient,
    layeredCache: longhuCache,
    readConfig,
    now,
    archiver: archiver,
    pageCache: new LayeredProxyCache({
      memoryCache: new ProcessMemoryCache({
        now,
        maxEntries: 128,
        maxBytes: 32 * 1024 * 1024,
        maxValueBytes: 1024 * 1024,
      }),
      redisCache: cache,
    }),
  })
  const collector =
    bigOrderCollector ||
    createBigOrderCollector({
      service: longhuService,
      dir: archiver.dir,
      now,
    })
  collector.startTimer()

  // 盘中登记"当日进入候选池/交易池"的股票，收盘后 15:10~16:00 自动逐只采集归档
  app.post('/api/big-order/longhu/collect-list', async (req, res) => {
    try {
      const stockCodes = Array.isArray(req.body?.stockCodes) ? req.body.stockCodes : null
      if (!stockCodes?.length) {
        return sendBadRequest(res, 'missing_stock_codes', 'stockCodes 必须是非空数组')
      }
      const list = await collector.register(stockCodes)
      return res.json({ ok: true, source: 'big-order-collect-list', list })
    } catch (error) {
      console.error('[大单采集清单] 失败:', error.message)
      return sendDegraded(res, { source: 'big-order-collect-list', error, fallbackData: { list: [] } })
    }
  })

  // 手动兜底：立即采集（传 stockCodes 用传入校验后清单，否则用当日登记清单）
  app.post('/api/big-order/longhu/collect', async (req, res) => {
    try {
      // 与 collect-list 一致的 validate + normalize：仅接受六位数字代码，上限 20 只
      const raw = Array.isArray(req.body?.stockCodes) ? req.body.stockCodes : null
      const validated = raw
        ? raw.map((code) => normalizeStockCode(code)).filter(Boolean).slice(0, 20)
        : null
      const report = await collector.runDaily(validated)
      return res.json({ ok: true, source: 'big-order-collect', report })
    } catch (error) {
      console.error('[大单采集] 失败:', error.message)
      return sendDegraded(res, { source: 'big-order-collect', error, fallbackData: null })
    }
  })

  app.get('/api/big-order/longhu/all-day', async (req, res) => {
    const stockCode = normalizeStockCode(req.query.stockCode)
    const money = Number(req.query.money || 0)
    if (!stockCode) return sendBadRequest(res, 'invalid_stock_code', 'stockCode 必须是六位数字')
    if (money !== 0) {
      return sendBadRequest(res, 'invalid_money', 'Longhu 结构化全天端点只支持 money=0')
    }
    try {
      const result = await longhuService.loadAllDay({ stockCode, money })
      const servedAt = now()
      const ageSeconds = Math.max(0, Math.floor((servedAt - result.fetchedAt) / 1000))
      return res.json({
        ok: true,
        source: 'longhu-big-order-all-day',
        stockCode,
        sessionDate: result.sessionDate,
        fetchedAt: result.fetchedAt,
        servedAt,
        data: {
          ...result.data,
          dragonMeta: {
            cache: {
              ...result.cache,
              ageSeconds,
              uiStale: servedAt - result.fetchedAt > uiStaleThresholdMs(servedAt),
              upstreamCalled: !result.cache.hit,
              ttlSeconds: result.cache.ttlSeconds,
            },
            refresh: result.refresh,
          },
        },
      })
    } catch (error) {
      return sendDegraded(res, {
        source: 'longhu-big-order-all-day',
        error,
        fallbackData: null,
      })
    }
  })

  app.get('/api/big-order/main-monitor', async (req, res) => {
    try {
      const { stockCode, limit = 100, money = 0, index = 0 } = req.query

      if (!stockCode) {
        return sendBadRequest(res, 'missing_stock_code', '缺少 stockCode 参数')
      }
      const numericMoney = Number(money) || 0

      const payload = await longhuService.loadPage({
        stockCode,
        limit: Math.min(Number(limit) || 100, 500),
        money: numericMoney,
        index: Number(index) || 0,
      })
      res.json(payload)
    } catch (error) {
      console.error('[大单监控] 失败:', error.message)
      sendDegraded(res, { source: 'big-order-main-monitor', error, fallbackData: { List: [] } })
    }
  })

  app.get('/api/big-order/all-day', async (req, res) => {
    try {
      const { stockCode, money = 0 } = req.query

      if (!stockCode) {
        return sendBadRequest(res, 'missing_stock_code', '缺少 stockCode 参数')
      }

      const numericMoney = Number(money) || 0
      const payload =
        numericMoney === 0
          ? (await longhuService.loadAllDay({ stockCode, money: 0 })).data
          : await longhuService.loadPage({
              stockCode,
              money: numericMoney,
              index: 0,
              limit: 40_000,
            })
      res.json({ List: payload.List })
    } catch (error) {
      console.error('[全天大单] 失败:', error.message)
      sendDegraded(res, { source: 'big-order-all-day', error, fallbackData: { List: [] } })
    }
  })
}
