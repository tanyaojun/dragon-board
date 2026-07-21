import iconv from 'iconv-lite'

import {
  DEFAULT_BROWSER_HEADERS,
  cleanCode,
  parseCodeList,
} from '../helpers/http.js'
import {
  attachCacheMeta,
  normalizeCodeCacheKey,
  PROXY_CACHE_TTLS,
} from '../helpers/proxyCache.js'
import { sendBadRequest, sendDegraded } from '../helpers/response.js'

const EMPTY_QUOTES = { rc: 0, data: { diff: [] } }

function shouldBypassQuoteCache(query = {}) {
  const force = String(query.force || query.refresh || '').toLowerCase()
  return force === '1' || force === 'true' || force === 'yes' || query._t !== undefined
}

function requireCodes(req, res) {
  const codes = parseCodeList(req.query.codes)
  if (!req.query.codes || codes.length === 0) {
    sendBadRequest(res, 'missing_codes', '缺少 codes 参数')
    return null
  }
  return codes
}

function normalizeSingleCode(value) {
  const code = String(value || '').trim()
  return /^\d{6}$/.test(code) ? code : ''
}

function parseTencentMinutePayload(payload, stockCode, fetchedAt) {
  if (Number(payload?.code) !== 0) throw new Error(payload?.msg || 'tencent minute error')
  const marketCode = `${stockCode.startsWith('6') ? 'sh' : 'sz'}${stockCode}`
  const source = payload?.data?.[marketCode]?.data
  if (!source || !Array.isArray(source.data) || !/^\d{8}$/.test(String(source.date || ''))) {
    throw new Error('invalid tencent minute payload')
  }
  const points = source.data.map((row) => {
    const [time, price, cumulativeVolume, cumulativeAmount] = String(row).trim().split(/\s+/)
    const point = {
      time,
      price: Number(price),
      cumulativeVolume: Number(cumulativeVolume),
      cumulativeAmount: Number(cumulativeAmount),
    }
    if (
      !/^\d{4}$/.test(time) ||
      !Number.isFinite(point.price) ||
      !Number.isFinite(point.cumulativeVolume) ||
      !Number.isFinite(point.cumulativeAmount)
    ) {
      throw new Error('invalid tencent minute row')
    }
    return point
  })
  return { fetchedAt, date: String(source.date), points }
}

function orderQuoteResponseByCodes(data, codeList) {
  const rows = Array.isArray(data?.data?.diff) ? data.data.diff : []
  if (!rows.length) return data
  const rowsByCode = new Map(rows.map((row) => [cleanCode(row?.f12), row]))
  const orderedRows = []
  const usedCodes = new Set()
  for (const code of codeList.map(cleanCode)) {
    const row = rowsByCode.get(code)
    if (!row) continue
    orderedRows.push(row)
    usedCodes.add(code)
  }
  for (const row of rows) {
    const code = cleanCode(row?.f12)
    if (!usedCodes.has(code)) orderedRows.push(row)
  }
  return {
    ...data,
    data: {
      ...(data.data || {}),
      diff: orderedRows,
    },
  }
}

export const __quoteRouteInternals = {
  parseTencentQuotePayload,
}

function parseTencentQuotePayload(rawData) {
  const text = iconv.decode(rawData, 'gbk')
  const results = []

  text.split('\n').forEach((line) => {
    if (!line || !line.includes('~')) return
    const match = line.match(/v_[^=]+="([^"]+)"/)
    if (!match) return

    const parts = match[1].split('~')
    if (parts.length < 49) return

    results.push({
      f12: parts[2],
      f14: parts[1],
      f2: parseFloat(parts[3]) || 0,
      f3: parseFloat(parts[32]) || 0,
      f6: parseFloat(parts[6]) || 0,
      f5: (parseFloat(parts[3]) || 0) * (parseFloat(parts[6]) || 0) * 100,
      f8: parseFloat(parts[38]) || 0,
      f9: parseFloat(parts[39]) || 0,
      f10: parseFloat(parts[49]) || 0,
      f20: (parseFloat(parts[45]) || 0) * 10000,
      f21: (parseFloat(parts[44]) || 0) * 10000,
      f23: parseFloat(parts[46]) || 0,
      f62: 0,
      f66: 0,
      f69: 0,
      f184: 0,
    })
  })

  return { rc: 0, data: { diff: results } }
}

function parseSinaQuotePayload(rawData) {
  const text = iconv.decode(rawData, 'gbk')
  const results = []

  text.split('\n').forEach((line) => {
    if (!line || !line.includes('="')) return
    const match = line.match(/var hq_str_([^=]+)="([^"]+)"/)
    if (!match) return

    const code = match[1].replace('sh', '').replace('sz', '')
    const parts = match[2].split(',')
    const prevClose = parseFloat(parts[2]) || 0
    const price = parseFloat(parts[3]) || 0

    results.push({
      f12: code,
      f14: parts[0],
      f2: price,
      f3: prevClose > 0 ? parseFloat((((price - prevClose) / prevClose) * 100).toFixed(2)) : 0,
      f6: parseFloat(parts[8]) || 0,
      f5: parseFloat(parts[9]) || 0,
      f8: 0,
      f9: 0,
      f20: 0,
      f21: 0,
      f23: 0,
      f62: 0,
      f66: 0,
      f69: 0,
      f184: 0,
    })
  })

  return { rc: 0, data: { diff: results } }
}

function sendCachedQuoteResponse(res, data, cacheMeta, codeList = []) {
  res.json(
    attachCacheMeta(orderQuoteResponseByCodes(data, codeList), {
      store: 'redis',
      ...cacheMeta,
    }),
  )
}

export function registerQuoteRoutes(app, { plainClient, readConfig, cache, runtimeCache, now = () => Date.now(), fetchImpl = globalThis.fetch }) {
  app.get('/api/quotes/tencent', async (req, res) => {
    const codeList = requireCodes(req, res)
    if (!codeList) return
    const cacheKey = `quotes:tencent:v1:${normalizeCodeCacheKey(codeList)}`
    const ttlSeconds = PROXY_CACHE_TTLS.quotes.tencentResponse

    try {
      const result = await cache.remember(
        cacheKey,
        {
          ttlSeconds,
          staleTtlSeconds: ttlSeconds * 6,
        },
        async () => {
          const tencentCodes = codeList
            .map((code) => {
              const c = cleanCode(code)
              return c.startsWith('6') ? `sh${c}` : `sz${c}`
            })
            .join(',')

          const response = await plainClient.get(`http://qt.gtimg.cn/q=${tencentCodes}`, {
            timeout: 5000,
            responseType: 'arraybuffer',
          })

          return parseTencentQuotePayload(response.data)
        },
      )
      sendCachedQuoteResponse(
        res,
        result.value,
        {
          ...result.cache,
          ttlSeconds,
        },
        codeList,
      )
    } catch (error) {
      console.error('[腾讯行情] 失败:', error.message)
      sendDegraded(res, { source: 'quotes-tencent', error, fallbackData: EMPTY_QUOTES })
    }
  })

  app.get('/api/quotes/tencent/minute', async (req, res) => {
    const stockCode = normalizeSingleCode(req.query.code)
    if (!stockCode) return sendBadRequest(res, 'invalid_stock_code', 'code 必须是六位数字')

    const ttlSeconds = PROXY_CACHE_TTLS.quotes.tencentMinute
    try {
      const result = await runtimeCache.remember(
        `quotes:tencent-minute:v1:${stockCode}`,
        { ttlSeconds, staleTtlSeconds: ttlSeconds * 6 },
        async () => {
          const marketCode = `${stockCode.startsWith('6') ? 'sh' : 'sz'}${stockCode}`
          const response = await plainClient.get(
            `https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=${marketCode}`,
            { timeout: 5000, headers: DEFAULT_BROWSER_HEADERS },
          )
          return parseTencentMinutePayload(response.data, stockCode, now())
        },
      )
      res.json({
        ok: true,
        source: 'quotes-tencent-minute',
        stockCode,
        fetchedAt: result.value.fetchedAt,
        servedAt: now(),
        data: attachCacheMeta(
          { date: result.value.date, points: result.value.points },
          { ...result.cache, store: 'memory', ttlSeconds },
        ),
      })
    } catch (error) {
      sendDegraded(res, { source: 'quotes-tencent-minute', error, fallbackData: null })
    }
  })

  app.get('/api/quotes/sina', async (req, res) => {
    const codeList = requireCodes(req, res)
    if (!codeList) return
    const cacheKey = `quotes:sina:v1:${normalizeCodeCacheKey(codeList)}`
    const ttlSeconds = PROXY_CACHE_TTLS.quotes.sinaResponse

    try {
      const result = await cache.remember(
        cacheKey,
        {
          ttlSeconds,
          staleTtlSeconds: ttlSeconds * 6,
        },
        async () => {
          const sinaCodes = codeList
            .map((code) => {
              const c = cleanCode(code)
              return c.startsWith('6') ? `sh${c}` : `sz${c}`
            })
            .join(',')

          const response = await plainClient.get(`http://hq.sinajs.cn/list=${sinaCodes}`, {
            timeout: 5000,
            responseType: 'arraybuffer',
            headers: { Referer: 'http://finance.sina.com.cn' },
          })

          return parseSinaQuotePayload(response.data)
        },
      )
      sendCachedQuoteResponse(
        res,
        result.value,
        {
          ...result.cache,
          ttlSeconds,
        },
        codeList,
      )
    } catch (error) {
      console.error('[新浪行情] 失败:', error.message)
      sendDegraded(res, { source: 'quotes-sina', error, fallbackData: EMPTY_QUOTES })
    }
  })

  app.get('/api/quotes/tencent/spk', async (req, res) => {
    res.set('X-Dragon-Board-Deprecated', 'true')
    const codeList = requireCodes(req, res)
    if (!codeList) return

    try {
      const spkCodes = codeList
        .map((code) => {
          const c = cleanCode(code)
          const market = c.startsWith('6') ? 'sh' : 'sz'
          return `s_pk${market}${c}`
        })
        .join(',')

      const response = await plainClient.get(`http://qt.gtimg.cn/q=${spkCodes}`, {
        timeout: 5000,
        responseType: 'arraybuffer',
      })

      const text = iconv.decode(response.data, 'gbk')
      const results = []

      text.split('\n').forEach((line) => {
        if (!line || !line.includes('=')) return
        const match = line.match(/v_s_pk[^=]+="([^"]+)"/)
        if (!match) return

        const parts = match[1].split('~')
        if (parts.length < 4) return

        const codeMatch = line.match(/v_s_pk([^=]+)=/)
        if (!codeMatch) return

        const code = codeMatch[1].replace('sh', '').replace('sz', '').padStart(6, '0')

        results.push({
          code,
          buy_big: parseFloat(parts[0]) || 0,
          buy_small: parseFloat(parts[1]) || 0,
          sell_big: parseFloat(parts[2]) || 0,
          sell_small: parseFloat(parts[3]) || 0,
        })
      })

      res.json({ rc: 0, deprecated: true, data: { diff: results } })
    } catch (error) {
      console.error('[腾讯盘口] 失败:', error.message)
      sendDegraded(res, { source: 'quotes-tencent-spk', error, fallbackData: { ...EMPTY_QUOTES, deprecated: true } })
    }
  })
}
