import { attachCacheMeta, PROXY_CACHE_TTLS } from '../helpers/proxyCache.js'
import { classifyUpstreamError, sendDegraded } from '../helpers/response.js'

const THS_LIMIT_UP_POOLS = [
  { key: 'one', cate: 'limit_up_one', sourceType: 'limit-up-layer' },
  { key: 'two', cate: 'limit_up_two', sourceType: 'limit-up-layer' },
  { key: 'three', cate: 'limit_up_three', sourceType: 'limit-up-layer' },
  { key: 'four', cate: 'limit_up_four', sourceType: 'limit-up-layer' },
  { key: 'high', cate: 'limit_up_high', sourceType: 'limit-up-layer' },
  { key: 'failed', cate: 'limit_up_fail', sourceType: 'open-limit-pool' },
  { key: 'rushing', cate: 'rushing', sourceType: 'rushing-limit-up' },
  { key: 'drawdown', cate: 'limit_up_bigboard', sourceType: 'limit-up-drawdown' },
]

const SHANGHAI_DATE_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

function currentDateString() {
  const parts = Object.fromEntries(SHANGHAI_DATE_FORMATTER.formatToParts(new Date()).map((part) => [part.type, part.value]))
  return `${parts.year}${parts.month}${parts.day}`
}

function normalizeDate(value) {
  const digits = String(value || '').replace(/\D/g, '')
  return digits.length === 8 ? digits : currentDateString()
}

function buildThsLimitUpPoolUrl(pool, date) {
  if (pool.sourceType === 'limit-up-drawdown') {
    return `https://data.10jqka.com.cn/mobileapi/hotspot_focus/stock_pool/v1/get_drawdown_stocks?date=${date}&cate=limit_up&sort_field=max_drawdown&sort_dir=asc&page=1&size=200`
  }
  if (pool.sourceType === 'open-limit-pool') {
    return `https://data.10jqka.com.cn/dataapi/limit_up/open_limit_pool?page=1&limit=200&field=199112%2C9002%2C48%2C1968584%2C19%2C3475914%2C9003%2C10%2C9004&filter=HS%2CGEM2STAR&order_field=199112&order_type=0&date=${date}`
  }
  if (pool.sourceType === 'rushing-limit-up') {
    return `https://data.10jqka.com.cn/dataapi/limit_up/limit_up?page=1&limit=200&field=199112%2C10%2C48%2C1968584%2C19%2C3475914%2C9003%2C9004&filter=HS%2CGEM2STAR&order_field=199112&order_type=0&date=${date}`
  }
  return `https://data.10jqka.com.cn/mobileapi/hotspot_focus/stock_pool/v1/get_limit_up_stocks?date=${date}&cate=${pool.cate}&sort_field=limit_up_time&sort_dir=asc&page=1&size=200`
}

function extractPoolItems(payload) {
  const data = payload?.data && typeof payload.data === 'object' ? payload.data : {}
  if (Array.isArray(data.stock_list)) return data.stock_list
  if (Array.isArray(data.info)) return data.info
  if (Array.isArray(payload?.stock_list)) return payload.stock_list
  if (Array.isArray(payload?.info)) return payload.info
  return []
}

function extractPoolTotal(payload, items) {
  const data = payload?.data && typeof payload.data === 'object' ? payload.data : {}
  return Number(data.page_info?.total ?? data.page?.total ?? payload?.page_info?.total ?? payload?.page?.total) || items.length
}

function validateThsLimitUpPayload(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('invalid ths limit-up payload')
  }
  if (payload?.data?.info !== undefined && !Array.isArray(payload.data.info)) {
    throw new Error('invalid ths limit-up info')
  }
  if (!Array.isArray(payload?.data?.info)) throw new Error('missing ths limit-up info')
  return payload
}

export function registerMarketRoutes(app, { plainClient, port, runtimeCache }) {
  app.get('/api/limitup/10jqka', async (req, res) => {
    try {
      const { date } = req.query
      const dateStr = normalizeDate(date)
      const url = `https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200&field=199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004,continue_day,continue_day_cnt,high_days,reason_type&filter=HS,GEM2STAR&order_field=330324&order_type=0&date=${dateStr}`
      const ttlSeconds = PROXY_CACHE_TTLS.market.thsLimitUp
      const result = await runtimeCache.remember(
        `market:ths-limitup:v1:${dateStr}`,
        { ttlSeconds, staleTtlSeconds: ttlSeconds * 6 },
        async () => {
          const response = await plainClient.get(url, { timeout: 8000 })
          return validateThsLimitUpPayload(response.data)
        },
      )
      res.json(
        attachCacheMeta(result.value, {
          ...result.cache,
          store: 'memory',
          ttlSeconds,
        }),
      )
    } catch (error) {
      sendDegraded(res, {
        source: 'limitup-10jqka',
        error,
        fallbackData: { data: { info: [] } },
      })
    }
  })

  app.get('/api/limitup/ths/pools', async (req, res) => {
    const dateStr = normalizeDate(req.query.date)
    const entries = await Promise.all(
      THS_LIMIT_UP_POOLS.map(async (pool) => {
        try {
          const url = buildThsLimitUpPoolUrl(pool, dateStr)
          const response = await plainClient.get(url, { timeout: 8000 })
          const items = extractPoolItems(response.data)
          return [
            pool.key,
            {
              ok: true,
              key: pool.key,
              cate: pool.cate,
              total: extractPoolTotal(response.data, items),
              items,
            },
          ]
        } catch (error) {
          return [
            pool.key,
            {
              ok: false,
              key: pool.key,
              cate: pool.cate,
              total: 0,
              items: [],
              errorCode: classifyUpstreamError(error),
              message: error?.message || 'ths limitup pool unavailable',
            },
          ]
        }
      }),
    )
    const pools = Object.fromEntries(entries)
    const errors = Object.values(pools)
      .filter((pool) => !pool.ok)
      .map((pool) => ({ pool: pool.key, errorCode: pool.errorCode, message: pool.message }))

    res.json({
      ok: errors.length === 0,
      degraded: errors.length > 0,
      source: 'limitup-ths-pools',
      date: dateStr,
      timestamp: Date.now(),
      pools,
      errors,
    })
  })

  app.get('/api/limitup/detail', async (req, res) => {
    res.set('X-Dragon-Board-Deprecated', 'true')
    const { date } = req.query
    const dateStr = date || currentDateString()

    const urls = [
      `https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool_detail?page=1&limit=200&date=${dateStr}`,
      `https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200&date=${dateStr}`,
    ]

    let lastError = null
    for (const url of urls) {
      try {
        const upstreamResponse = await plainClient.get(url, { timeout: 5000 })
        if (upstreamResponse.data) {
          return res.json({ ...upstreamResponse.data, deprecated: true })
        }
      } catch (error) {
        lastError = error
      }
    }

    sendDegraded(res, {
      source: 'limitup-detail',
      error: lastError || new Error('no limitup detail source available'),
      fallbackData: { deprecated: true, data: { info: [] } },
    })
  })

  app.get('/api/surge-stock/performance', async (req, res) => {
    try {
      const response = await plainClient.get(
        'https://flash-api.xuangubao.cn/api/surge_stock/stocks?normal=true&uplimit=true',
        { timeout: 8000 },
      )
      res.json(response.data)
    } catch (error) {
      console.error('[surge-stock] 接口失败:', error.message)
      sendDegraded(res, {
        source: 'surge-stock-performance',
        error,
        fallbackData: { data: [] },
      })
    }
  })

  app.get('/api/market/overview', async (req, res) => {
    try {
      const response = await plainClient.get('https://dq.10jqka.com.cn/fuyao/v2/board/real_index_data', {
        timeout: 3000,
      })
      if (response.data?.data) {
        return res.json(response.data.data)
      }
      res.json(response.data)
    } catch (error) {
      sendDegraded(res, { source: 'market-overview', error, fallbackData: null })
    }
  })

  app.get('/api/sentiment/composite', async (req, res) => {
    const [overviewRes, limitupRes, surgeRes] = await Promise.allSettled([
      plainClient.get(`http://localhost:${port}/api/market/overview`, { timeout: 5000 }),
      plainClient.get(`http://localhost:${port}/api/limitup/10jqka`, { timeout: 8000 }),
      plainClient.get(`http://localhost:${port}/api/surge-stock/performance`, { timeout: 8000 }),
    ])

    res.json({
      ok: true,
      degraded:
        overviewRes.status === 'rejected' ||
        limitupRes.status === 'rejected' ||
        surgeRes.status === 'rejected',
      timestamp: Date.now(),
      overview: overviewRes.status === 'fulfilled' ? overviewRes.value.data : null,
      limitup: limitupRes.status === 'fulfilled' ? limitupRes.value.data : null,
      yesterdayPerformance: surgeRes.status === 'fulfilled' ? surgeRes.value.data : null,
    })
  })
}
