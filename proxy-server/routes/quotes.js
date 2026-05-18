import iconv from 'iconv-lite'

import {
  DEFAULT_BROWSER_HEADERS,
  cleanCode,
  createSourceProxyConfig,
  getMarketPrefix,
  parseCodeList,
} from '../helpers/http.js'
import {
  attachCacheMeta,
  normalizeCodeCacheKey,
  PROXY_CACHE_TTLS,
} from '../helpers/proxyCache.js'
import { sendBadRequest, sendDegraded } from '../helpers/response.js'

const EMPTY_QUOTES = { rc: 0, data: { diff: [] } }
const EASTMONEY_QUOTE_FIELDS = 'f2,f3,f5,f6,f8,f9,f12,f14,f20,f21,f23,f62,f66,f69,f184'
const EASTMONEY_FLOW_FIELDS =
  'f12,f14,f2,f3,f5,f6,f8,f9,f20,f21,f23,f62,f66,f69,f72,f75,f78,f81,f84,f87,f184'
const EASTMONEY_FLOW_FS = 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23'
const EASTMONEY_HIST_FLOW_FIELDS1 = 'f1,f2,f3,f7'
const EASTMONEY_HIST_FLOW_FIELDS2 = 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65'
const EASTMONEY_HIST_FLOW_CONCURRENCY = 4
const EASTMONEY_HIST_FLOW_RETRIES = 2
const EASTMONEY_ULIST_HIST_FLOW_LIMIT = 20
const EASTMONEY_FUND_FLOW_FIELDS = new Set(['f62', 'f66', 'f69', 'f184'])

function requireCodes(req, res) {
  const codes = parseCodeList(req.query.codes)
  if (!req.query.codes || codes.length === 0) {
    sendBadRequest(res, 'missing_codes', '缺少 codes 参数')
    return null
  }
  return codes
}

function normalizeEastmoneyQuoteRow(row) {
  return {
    f12: cleanCode(row?.f12),
    f14: row?.f14 || '',
    f2: Number(row?.f2) || 0,
    f3: Number(row?.f3) || 0,
    f5: Number(row?.f5) || 0,
    f6: Number(row?.f6) || 0,
    f8: Number(row?.f8) || 0,
    f9: Number(row?.f9) || 0,
    f20: Number(row?.f20) || 0,
    f21: Number(row?.f21) || 0,
    f23: Number(row?.f23) || 0,
    f62: Number(row?.f62) || 0,
    f66: Number(row?.f66) || 0,
    f69: Number(row?.f69) || 0,
    f184: Number(row?.f184) || 0,
  }
}

function normalizeEastmoneyResponse(data, codeList) {
  const allowed = new Set(codeList.map((code) => cleanCode(code)))
  const rows = Array.isArray(data?.data?.diff) ? data.data.diff : []
  return {
    rc: Number(data?.rc) || 0,
    data: {
      diff: rows
        .map(normalizeEastmoneyQuoteRow)
        .filter((row) => row.f12 && (!allowed.size || allowed.has(row.f12))),
    },
  }
}

function mergeEastmoneyRows(baseData, fallbackData, codeList) {
  const rowsByCode = new Map()
  for (const row of normalizeEastmoneyResponse(baseData, codeList).data.diff) {
    rowsByCode.set(row.f12, row)
  }
  for (const row of normalizeEastmoneyResponse(fallbackData, codeList).data.diff) {
    const existing = rowsByCode.get(row.f12) || {}
    const merged = { ...existing }
    for (const [key, value] of Object.entries(row)) {
      if (key === 'f12' || key === 'f14') {
        if (value) merged[key] = value
        continue
      }
      if (Number(value) !== 0 || merged[key] === undefined) {
        merged[key] = value
      }
    }
    rowsByCode.set(row.f12, merged)
  }
  return { rc: 0, data: { diff: Array.from(rowsByCode.values()) } }
}

function mergeEastmoneyFundFlowRows(baseData, fallbackData, codeList) {
  const rowsByCode = new Map()
  for (const row of normalizeEastmoneyResponse(baseData, codeList).data.diff) {
    rowsByCode.set(row.f12, row)
  }
  for (const row of normalizeEastmoneyResponse(fallbackData, codeList).data.diff) {
    const existing = rowsByCode.get(row.f12) || { f12: row.f12 }
    const merged = { ...existing }
    if (row.f14 && !merged.f14) merged.f14 = row.f14
    for (const key of EASTMONEY_FUND_FLOW_FIELDS) {
      const value = row[key]
      if (Number(value) !== 0 || merged[key] === undefined) {
        merged[key] = value
      }
    }
    rowsByCode.set(row.f12, merged)
  }
  return { rc: 0, data: { diff: Array.from(rowsByCode.values()) } }
}

function missingEastmoneyCodes(data, codeList) {
  const present = new Set(normalizeEastmoneyResponse(data, codeList).data.diff.map((row) => row.f12))
  return codeList.map(cleanCode).filter((code) => code && !present.has(code))
}

function hasFundFlow(row) {
  return [row?.f62, row?.f184, row?.f66, row?.f69].some((value) => {
    const number = Number(value)
    return Number.isFinite(number) && number !== 0
  })
}

function codesMissingFundFlow(data, codeList) {
  const rowsByCode = new Map(
    normalizeEastmoneyResponse(data, codeList).data.diff.map((row) => [row.f12, row]),
  )
  return codeList
    .map(cleanCode)
    .filter((code) => code && !hasFundFlow(rowsByCode.get(code)))
}

function withEastmoneyQuoteMeta(data, meta) {
  return {
    ...data,
    dragonMeta: {
      source: 'eastmoney',
      ...meta,
      rowCount: Array.isArray(data?.data?.diff) ? data.data.diff.length : 0,
    },
  }
}

function buildEastmoneyUlistUrl(codeList) {
  const marketCodes = codeList.map((code) => `${getMarketPrefix(code)}.${cleanCode(code)}`).join(',')
  return (
    `https://push2.eastmoney.com/api/qt/ulist.np/get?` +
    `fltt=2` +
    `&ut=a79f54e3d4c8d44e494efb8f748db291` +
    `&secids=${marketCodes}` +
    `&fields=${EASTMONEY_QUOTE_FIELDS}` +
    `&_=${Date.now()}`
  )
}

function buildEastmoneyClistUrl(codeList) {
  const pageSize = Math.max(50, Math.min(5000, codeList.length * 30))
  return (
    `https://push2.eastmoney.com/api/qt/clist/get?` +
    `fid=f62` +
    `&po=1` +
    `&pz=${pageSize}` +
    `&pn=1` +
    `&np=1` +
    `&fltt=2` +
    `&invt=2` +
    `&ut=b2884a393a59ad64002292a3e90d46a5` +
    `&fs=${EASTMONEY_FLOW_FS}` +
    `&fields=${EASTMONEY_FLOW_FIELDS}` +
    `&_=${Date.now()}`
  )
}

function buildEastmoneyHistFlowUrl(code) {
  return (
    `https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?` +
    `lmt=1` +
    `&klt=101` +
    `&secid=${getMarketPrefix(code)}.${cleanCode(code)}` +
    `&fields1=${EASTMONEY_HIST_FLOW_FIELDS1}` +
    `&fields2=${EASTMONEY_HIST_FLOW_FIELDS2}` +
    `&_=${Date.now()}`
  )
}

function normalizeEastmoneyHistFlowResponse(data, code) {
  const kline = data?.data?.klines?.[0]
  if (!kline) return null
  const parts = String(kline).split(',')
  if (parts.length < 11) return null

  return normalizeEastmoneyQuoteRow({
    f12: data?.data?.code || code,
    f14: data?.data?.name || '',
    f62: parts[1],
    f184: parts[6],
    f66: parts[5],
    f69: parts[10],
    f2: parts[11],
    f3: parts[12],
  })
}

async function fetchEastmoneyHistFlowQuote(plainClient, code, cache = null, eastmoneyProxyConfig = {}) {
  const cacheKey = `quotes:eastmoney:hist-flow:v1:${cleanCode(code)}`
  const ttlSeconds = PROXY_CACHE_TTLS.quotes.eastmoneyHistFlow
  if (cache) {
    const cached = await cache.get(cacheKey)
    if (cached) return cached.value
  }

  let lastError = null
  for (let attempt = 0; attempt <= EASTMONEY_HIST_FLOW_RETRIES; attempt += 1) {
    try {
      const response = await plainClient.get(buildEastmoneyHistFlowUrl(code), {
        timeout: 8000,
        ...eastmoneyProxyConfig,
        headers: {
          ...DEFAULT_BROWSER_HEADERS,
          Referer: 'https://data.eastmoney.com/zjlx/detail.html',
        },
      })
      const row = normalizeEastmoneyHistFlowResponse(response.data, code)
      if (row && cache) {
        await cache.set(cacheKey, row, {
          ttlSeconds,
          staleTtlSeconds: ttlSeconds * 4,
        })
      }
      return row
    } catch (error) {
      lastError = error
    }
  }
  throw lastError
}

async function fetchEastmoneyHistFlowQuotes(
  plainClient,
  codeList,
  concurrency = EASTMONEY_HIST_FLOW_CONCURRENCY,
  cache = null,
  eastmoneyProxyConfig = {},
) {
  const rows = []
  const failures = []
  const queue = codeList.map(cleanCode).filter(Boolean)
  const workerCount = Math.max(1, Math.min(Number(concurrency) || 1, queue.length))
  let cursor = 0

  await Promise.all(
    Array.from({ length: workerCount }, async () => {
      while (cursor < queue.length) {
        const code = queue[cursor]
        cursor += 1
        try {
          const row = await fetchEastmoneyHistFlowQuote(
            plainClient,
            code,
            cache,
            eastmoneyProxyConfig,
          )
          if (row) rows.push(row)
        } catch (error) {
          failures.push({
            code,
            error: error?.code || error?.message || 'unknown',
          })
        }
      }
    }),
  )

  if (failures.length) {
    console.warn('[东财行情] hist-flow partial failures:', failures.slice(0, 10))
  }
  return {
    rc: 0,
    data: { diff: rows },
    dragonMeta: {
      histRequested: queue.length,
      histReturned: rows.length,
      histFailed: failures.length,
      histFailures: failures.slice(0, 20),
    },
  }
}

export const __quoteRouteInternals = {
  EASTMONEY_ULIST_HIST_FLOW_LIMIT,
  normalizeEastmoneyResponse,
  normalizeEastmoneyHistFlowResponse,
  mergeEastmoneyRows,
  missingEastmoneyCodes,
  codesMissingFundFlow,
  mergeEastmoneyFundFlowRows,
  buildEastmoneyUlistUrl,
  buildEastmoneyClistUrl,
  buildEastmoneyHistFlowUrl,
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

function sendCachedQuoteResponse(res, data, cacheMeta) {
  res.json(
    attachCacheMeta(data, {
      store: 'redis',
      ...cacheMeta,
    }),
  )
}

async function sendEastmoneyQuoteResponse(res, cache, cacheKey, data, cacheMeta) {
  void cache
  void cacheKey
  sendCachedQuoteResponse(res, data, cacheMeta)
}

async function loadEastmoneyQuotePayload(
  plainClient,
  cache,
  codeList,
  ttlSeconds,
  eastmoneyProxyConfig = {},
) {
  void ttlSeconds
  const response = await plainClient.get(buildEastmoneyUlistUrl(codeList), {
    timeout: 8000,
    ...eastmoneyProxyConfig,
    headers: DEFAULT_BROWSER_HEADERS,
  })

  const ulistData = normalizeEastmoneyResponse(response.data, codeList)
  const missingFundFlowCodes = codesMissingFundFlow(ulistData, codeList)
  const histRequestCodes = missingFundFlowCodes.slice(0, EASTMONEY_ULIST_HIST_FLOW_LIMIT)
  const histSkippedCount = Math.max(0, missingFundFlowCodes.length - histRequestCodes.length)
  const histData = histRequestCodes.length
    ? await fetchEastmoneyHistFlowQuotes(
        plainClient,
        histRequestCodes,
        EASTMONEY_HIST_FLOW_CONCURRENCY,
        cache,
        eastmoneyProxyConfig,
      )
    : EMPTY_QUOTES
  const mergedData = histRequestCodes.length
    ? mergeEastmoneyFundFlowRows(ulistData, histData, codeList)
    : ulistData

  return withEastmoneyQuoteMeta(mergedData, {
    route: 'ulist',
    fallback: false,
    histFillCount: histData.data.diff.length,
    histFailed: histData.dragonMeta?.histFailed || 0,
    missingFundFlowCount: missingFundFlowCodes.length,
    histSkippedCount,
  })
}

async function loadEastmoneyQuoteFallbackPayload(
  plainClient,
  cache,
  codeList,
  primaryError,
  ttlSeconds,
  eastmoneyProxyConfig = {},
) {
  void ttlSeconds
  try {
    const fallbackResponse = await plainClient.get(buildEastmoneyClistUrl(codeList), {
      timeout: 10000,
      ...eastmoneyProxyConfig,
      headers: {
        ...DEFAULT_BROWSER_HEADERS,
        Referer: 'https://data.eastmoney.com/zjlx/detail.html',
      },
    })
    const clistData = mergeEastmoneyRows(EMPTY_QUOTES, fallbackResponse.data, codeList)
    const missingCodes = missingEastmoneyCodes(clistData, codeList)
    const histData = missingCodes.length
      ? await fetchEastmoneyHistFlowQuotes(
          plainClient,
          missingCodes,
          EASTMONEY_HIST_FLOW_CONCURRENCY,
          cache,
          eastmoneyProxyConfig,
        )
      : EMPTY_QUOTES
    const mergedData = mergeEastmoneyRows(clistData, histData, codeList)
    return withEastmoneyQuoteMeta(mergedData, {
      route: 'clist',
      fallback: true,
      primaryError: primaryError?.code || primaryError?.message || 'unknown',
      histFillCount: histData.data.diff.length,
      histFailed: histData.dragonMeta?.histFailed || 0,
      missingAfterClist: missingCodes.length,
    })
  } catch (clistError) {
    console.warn('[东财行情] clist fallback 失败，尝试 push2his 当日资金流:', clistError.message)
    try {
      const histData = await fetchEastmoneyHistFlowQuotes(
        plainClient,
        codeList,
        EASTMONEY_HIST_FLOW_CONCURRENCY,
        cache,
        eastmoneyProxyConfig,
      )
      return withEastmoneyQuoteMeta(histData, {
        route: 'hist-flow',
        fallback: true,
        primaryError: primaryError?.code || primaryError?.message || 'unknown',
        clistError: clistError?.code || clistError?.message || 'unknown',
        histRequested: histData.dragonMeta?.histRequested || codeList.length,
        histReturned: histData.dragonMeta?.histReturned || histData.data.diff.length,
        histFailed: histData.dragonMeta?.histFailed || 0,
        histFailures: histData.dragonMeta?.histFailures || [],
      })
    } catch (histError) {
      console.error('[东财行情] hist-flow fallback 失败:', histError.message)
      histError.cause = clistError
      throw histError
    }
  }
}

export function registerQuoteRoutes(app, { plainClient, readConfig, cache }) {
  app.get('/api/quotes/eastmoney', async (req, res) => {
    const codeList = requireCodes(req, res)
    if (!codeList) return
    const cacheKey = `quotes:eastmoney:v1:${normalizeCodeCacheKey(codeList)}`
    const ttlSeconds = PROXY_CACHE_TTLS.quotes.eastmoneyResponse
    const eastmoneyProxyConfig = createSourceProxyConfig(readConfig, 'eastmoney')
    try {
      const result = await cache.remember(
        cacheKey,
        {
          ttlSeconds,
          staleTtlSeconds: ttlSeconds * 6,
        },
        () =>
          loadEastmoneyQuotePayload(
            plainClient,
            cache,
            codeList,
            ttlSeconds,
            eastmoneyProxyConfig,
          ),
      )
      await sendEastmoneyQuoteResponse(res, cache, cacheKey, result.value, {
        ...result.cache,
        ttlSeconds,
      })
    } catch (error) {
      console.warn('[东财行情] ulist 失败，尝试 clist 资金流 fallback:', error.message)
      try {
        const payload = await loadEastmoneyQuoteFallbackPayload(
          plainClient,
          cache,
          codeList,
          error,
          ttlSeconds,
          eastmoneyProxyConfig,
        )
        await cache.set(cacheKey, payload, {
          ttlSeconds,
          staleTtlSeconds: ttlSeconds * 6,
        })
        await sendEastmoneyQuoteResponse(res, cache, cacheKey, payload, {
          hit: false,
          stale: false,
          upstreamCalled: true,
          ttlSeconds,
        })
      } catch (fallbackError) {
        sendDegraded(res, { source: 'quotes-eastmoney', error: fallbackError, fallbackData: EMPTY_QUOTES })
      }
    }
  })

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
      sendCachedQuoteResponse(res, result.value, {
        ...result.cache,
        ttlSeconds,
      })
    } catch (error) {
      console.error('[腾讯行情] 失败:', error.message)
      sendDegraded(res, { source: 'quotes-tencent', error, fallbackData: EMPTY_QUOTES })
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
      sendCachedQuoteResponse(res, result.value, {
        ...result.cache,
        ttlSeconds,
      })
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
