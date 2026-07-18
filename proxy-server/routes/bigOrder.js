import { delay } from '../helpers/http.js'
import {
  attachCacheMeta,
  LayeredProxyCache,
  ProcessMemoryCache,
  PROXY_CACHE_TTLS,
} from '../helpers/proxyCache.js'
import { sendBadRequest, sendDegraded } from '../helpers/response.js'
import { createBigOrderArchiver } from '../services/bigOrderArchive.js'
import { createBigOrderCollector } from '../services/bigOrderCollector.js'
import { createLonghuBigOrderService } from '../services/longhuBigOrderCache.js'

const THS_BIG_ORDER_BASE = 'https://vaserviece.10jqka.com.cn/Level2/index.php'

const THS_MONEY_FLOW_CONCURRENCY = 2
const THS_MONEY_FLOW_DELAY_MS = 200
const THS_MONEY_FLOW_BG_MAX = 2
const THS_MONEY_FLOW_CIRCUIT_BREAKER_FAILS = 5

const THS_BIG_ORDER_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
  Referer: 'https://vaserviece.10jqka.com.cn/',
  Accept: 'application/json,text/plain,*/*',
}

function buildThsBigOrderUrl(stockCode) {
  const url = new URL(THS_BIG_ORDER_BASE)
  url.searchParams.set('op', 'mainMonitorDetail')
  url.searchParams.set('stockcode', stockCode)
  return url
}

function normalizeStockCode(value) {
  const code = String(value || '').trim()
  return /^\d{6}$/.test(code) ? code : ''
}

function validateThsPayload(payload, now) {
  if (Number(payload?.errorcode) !== 0) throw new Error(payload?.msg || 'ths error response')
  if (!payload?.title || typeof payload.title !== 'object' || Array.isArray(payload.title) || !Array.isArray(payload?.list)) {
    throw new Error('invalid ths big-order payload')
  }
  return {
    fetchedAt: now(),
    sessionDate: inferThsSessionDate(payload),
    title: payload.title,
    list: payload.list,
    pricechange: Array.isArray(payload.pricechange) ? payload.pricechange : [],
  }
}

function inferThsSessionDate(payload) {
  const explicit = [payload?.sessionDate, payload?.tradeDate, payload?.date]
    .map((value) => String(value || '').trim())
    .find((value) => /^\d{4}-\d{2}-\d{2}$/.test(value))
  if (explicit) return explicit
  for (const row of payload?.pricechange || []) {
    const match = String(row?.[1] || '').match(/^(\d{4})(\d{2})(\d{2})/)
    if (match) return `${match[1]}-${match[2]}-${match[3]}`
  }
  for (const row of payload?.list || []) {
    const match = String(row?.otime || row?.ctime || '').match(/^(\d{4}-\d{2}-\d{2})\s/)
    if (match) return match[1]
  }
  return null
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

function parseChineseAmount(raw) {
  if (!raw || typeof raw !== 'string') return 0
  const cleaned = raw.replace(/,/g, '').trim()
  const yiMatch = cleaned.match(/^([\d.]+)亿$/)
  if (yiMatch) return parseFloat(yiMatch[1]) * 100_000_000
  const wanMatch = cleaned.match(/^([\d.]+)万$/)
  if (wanMatch) return parseFloat(wanMatch[1]) * 10_000
  const yuanMatch = cleaned.match(/^([\d.]+)元$/)
  if (yuanMatch) return parseFloat(yuanMatch[1]) || 0
  return parseFloat(cleaned) || 0
}

function parseThsMoneyFlowRow(payload, stockCode) {
  const mainbuy = parseChineseAmount(payload?.title?.mainbuy)
  const mainsell = parseChineseAmount(payload?.title?.mainsell)
  const price = parseFloat(payload?.title?.price) || 0
  const zlje = Math.round(mainbuy - mainsell)
  return {
    f12: stockCode,
    f14: payload?.title?.stockname || '',
    f2: price,
    f62: zlje,
    f66: 0,
    f69: 0,
    f184: 0,
  }
}

function thsMoneyFlowCacheKey(code) {
  return `big-order:ths-flow:v2:${code}`
}

const THS_FLOW_CACHE_TTL_SECONDS = 60
const THS_FLOW_CACHE_STALE_SECONDS = 300

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
  const thsCache = new LayeredProxyCache({ memoryCache: runtimeCache, redisCache: cache })
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

  app.get('/api/big-order/ths-detail', async (req, res) => {
    const stockCode = normalizeStockCode(req.query.stockCode)
    if (!stockCode) {
      return sendBadRequest(res, 'invalid_stock_code', 'stockCode 必须是六位数字')
    }

    const ttlSeconds = PROXY_CACHE_TTLS.bigOrder.thsDetail
    try {
      const result = await thsCache.remember(
        `big-order:ths-detail:v2:${new Date(now()).toLocaleDateString('sv-SE', {
          timeZone: 'Asia/Shanghai',
        })}:${stockCode}`,
        { ttlSeconds, staleTtlSeconds: Math.max(ttlSeconds * 6, 180) },
        async () => {
          const response = await plainClient.get(buildThsBigOrderUrl(stockCode).toString(), {
            timeout: 15000,
            headers: THS_BIG_ORDER_HEADERS,
          })
          return validateThsPayload(response.data, now)
        },
      )

      return res.json({
        ok: true,
        source: 'ths-big-order-detail',
        stockCode,
        sessionDate: result.value.sessionDate,
        fetchedAt: result.value.fetchedAt,
        servedAt: now(),
        data: attachCacheMeta(result.value, {
          ...result.cache,
          store: result.cache.store,
          ageSeconds: Math.max(0, Math.floor((now() - result.value.fetchedAt) / 1000)),
          uiStale: now() - result.value.fetchedAt > uiStaleThresholdMs(now()),
          ttlSeconds,
        }),
      })
    } catch (error) {
      console.error('[同花顺大单] 失败:', error.message)
      return sendDegraded(res, {
        source: 'ths-big-order-detail',
        error,
        fallbackData: null,
      })
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

  app.get('/api/quotes/ths-money-flow', async (req, res) => {
    const raw = String(req.query.codes || '')
    const codeList = raw
      .split(',')
      .map((s) => normalizeStockCode(s))
      .filter(Boolean)
    if (!codeList.length) {
      return sendBadRequest(res, 'missing_codes', '缺少 codes 参数')
    }

    const rows = []
    const failures = []
    const queue = [...codeList]
    const workerCount = Math.max(1, Math.min(THS_MONEY_FLOW_CONCURRENCY, queue.length))
    let cursor = 0
    let cacheHitCount = 0
    let cacheStaleCount = 0
    let cacheMissCount = 0
    const pendingBgRefreshes = new Set()
    const flowCache = cache.enabled() ? cache : runtimeCache

    const fetchFromThs = async (code) => {
      const response = await plainClient.get(buildThsBigOrderUrl(code).toString(), {
        timeout: 20000,
        headers: THS_BIG_ORDER_HEADERS,
      })
      return validateThsPayload(response.data, now)
    }

    const refreshAndCache = async (code) => {
      const payload = await fetchFromThs(code)
      const row = parseThsMoneyFlowRow(payload, code)
      await flowCache.set(thsMoneyFlowCacheKey(code), row, {
        ttlSeconds: THS_FLOW_CACHE_TTL_SECONDS,
        staleTtlSeconds: THS_FLOW_CACHE_STALE_SECONDS,
      })
      return row
    }

    let bgRunning = 0

    const scheduleBackgroundRefresh = (code) => {
      if (pendingBgRefreshes.has(code)) return
      if (bgRunning >= THS_MONEY_FLOW_BG_MAX) return
      pendingBgRefreshes.add(code)
      bgRunning++
      // 不 await — 后台静默刷新，不阻塞响应
      refreshAndCache(code)
        .catch((err) => console.warn(`[THS资金流] 后台刷新 ${code} 失败:`, err.message))
        .finally(() => {
          pendingBgRefreshes.delete(code)
          bgRunning--
        })
    }

    await Promise.all(
      Array.from({ length: workerCount }, async () => {
        let consecutiveMissFails = 0
        while (cursor < queue.length) {
          // 熔断：连续失败超过阈值，跳过剩余代码
          if (consecutiveMissFails >= THS_MONEY_FLOW_CIRCUIT_BREAKER_FAILS) {
            const skipped = queue.length - cursor
            cursor = queue.length
            console.warn(`[THS资金流] 熔断触发，跳过剩余 ${skipped} 只`)
            return
          }
          const code = queue[cursor++]
          const cached = await flowCache.get(thsMoneyFlowCacheKey(code), { allowStale: true })

          if (cached && !cached.stale) {
            // 新鲜命中 — 直接返回
            cacheHitCount++
            rows.push(cached.value)
          } else if (cached && cached.stale) {
            // Stale 命中 — 返回旧值，后台静默刷新
            cacheStaleCount++
            rows.push(cached.value)
            scheduleBackgroundRefresh(code)
          } else {
            // 未命中 — 同步等待上游
            cacheMissCount++
            try {
              const row = await refreshAndCache(code)
              rows.push(row)
              consecutiveMissFails = 0
            } catch (error) {
              console.warn(`[THS资金流] ${code} 失败:`, error.message)
              failures.push({ code, error: error?.message || 'unknown' })
              consecutiveMissFails++
            }
            if (cursor < queue.length) {
              await delay(THS_MONEY_FLOW_DELAY_MS)
            }
          }
        }
      }),
    )

    if (failures.length) {
      console.warn('[THS资金流] partial failures:', failures.slice(0, 10))
    }

    res.json({
      rc: 0,
      data: { diff: rows },
      dragonMeta: {
        source: 'ths-money-flow',
        requested: queue.length,
        returned: rows.length,
        failed: failures.length,
        cacheHitCount,
        cacheStaleCount,
        cacheMissCount,
        pendingBgRefreshCount: pendingBgRefreshes.size,
        failures: failures.slice(0, 20),
      },
    })
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
