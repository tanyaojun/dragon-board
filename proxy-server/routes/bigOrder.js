import { delay } from '../helpers/http.js'
import { attachCacheMeta, PROXY_CACHE_TTLS } from '../helpers/proxyCache.js'
import { sendBadRequest, sendDegraded } from '../helpers/response.js'

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
    title: payload.title,
    list: payload.list,
    pricechange: Array.isArray(payload.pricechange) ? payload.pricechange : [],
  }
}

function generateDeviceId() {
  const input = Date.now() + Math.random().toString(36)
  let hash = 0
  for (let i = 0; i < input.length; i++) {
    const char = input.charCodeAt(i)
    hash = (hash << 5) - hash + char
    hash &= hash
  }
  return Math.abs(hash).toString(16).padStart(32, '0').substring(0, 32)
}

function buildBigOrderUrl({ stockCode, limit, money, index, deviceId }) {
  const url = new URL('https://apphwhq.longhuvip.com/w1/api/index.php')
  url.searchParams.append('Order', '0')
  url.searchParams.append('st', String(limit))
  url.searchParams.append('a', 'GetMainMonitor_w30')
  url.searchParams.append('c', 'StockYiDongKanPan')
  url.searchParams.append('PhoneOSNew', '1')
  url.searchParams.append('DeviceID', deviceId)
  url.searchParams.append('VerSion', '5.17.0.4')
  url.searchParams.append('Index', String(index))
  url.searchParams.append('Money', String(money))
  url.searchParams.append('apiv', 'w36')
  url.searchParams.append('StockID', String(stockCode))
  url.searchParams.append('IsBS', '0')
  return url
}

const BIG_ORDER_HEADERS = {
  'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 9; MI 8 MIUI/V11.0.5.0.PEACNXM)',
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

export function registerBigOrderRoutes(app, { plainClient, cache, runtimeCache, now = () => Date.now() }) {
  app.get('/api/big-order/ths-detail', async (req, res) => {
    const stockCode = normalizeStockCode(req.query.stockCode)
    if (!stockCode) {
      return sendBadRequest(res, 'invalid_stock_code', 'stockCode 必须是六位数字')
    }

    const ttlSeconds = PROXY_CACHE_TTLS.bigOrder.thsDetail
    try {
      const result = await runtimeCache.remember(
        `big-order:ths-detail:v1:${stockCode}`,
        { ttlSeconds, staleTtlSeconds: ttlSeconds * 6 },
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
        fetchedAt: result.value.fetchedAt,
        servedAt: now(),
        data: attachCacheMeta(result.value, {
          ...result.cache,
          store: 'memory',
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

      const url = buildBigOrderUrl({
        stockCode,
        limit: Math.min(Number(limit) || 100, 500),
        money: Number(money) || 0,
        index: Number(index) || 0,
        deviceId: generateDeviceId(),
      })

      const response = await plainClient.get(url.toString(), {
        timeout: 15000,
        headers: BIG_ORDER_HEADERS,
      })

      res.json(response.data)
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

      const pageSize = 500
      const maxPages = 20
      let index = 0
      let allData = []
      const deviceId = generateDeviceId()

      for (let page = 0; page < maxPages; page++) {
        const url = buildBigOrderUrl({
          stockCode,
          limit: pageSize,
          money: Number(money) || 0,
          index,
          deviceId,
        })

        const response = await plainClient.get(url.toString(), {
          timeout: 10000,
          headers: BIG_ORDER_HEADERS,
        })

        const list = response.data?.List || []
        if (!Array.isArray(list) || list.length === 0) break

        allData = allData.concat(list)
        if (list.length < pageSize) break

        index += pageSize
        await delay(100)
      }

      res.json({ List: allData })
    } catch (error) {
      console.error('[全天大单] 失败:', error.message)
      sendDegraded(res, { source: 'big-order-all-day', error, fallbackData: { List: [] } })
    }
  })
}
