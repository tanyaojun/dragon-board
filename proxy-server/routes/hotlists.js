import { DEFAULT_BROWSER_HEADERS } from '../helpers/http.js'
import { attachCacheMeta, PROXY_CACHE_TTLS } from '../helpers/proxyCache.js'
import { sendDegraded } from '../helpers/response.js'
import { generateCLSSign } from '../helpers/sign.js'

const EMPTY_HOTLIST_FALLBACK = {
  xueqiu: { data: { items: [] } },
  cls: { errno: -1, data: [] },
  eastmoney: { data: [] },
  ths: { data: { stock_list: [] } },
  kpl: { List: [] },
  tdx: [],
  tgb: { dto: [] },
  dzh: { result: [] },
}

function fallback(source) {
  return EMPTY_HOTLIST_FALLBACK[source] ?? null
}

async function sendCachedHotlist(res, cache, platform, loader) {
  const ttlSeconds = PROXY_CACHE_TTLS.hotlist[platform] || PROXY_CACHE_TTLS.hotlist.default
  const key = `hotlist:${platform}:v1`
  const result = await cache.remember(
    key,
    {
      ttlSeconds,
      staleTtlSeconds: ttlSeconds * 3,
    },
    loader,
  )
  res.json(
    attachCacheMeta(result.value, {
      ...result.cache,
      upstreamCalled: result.cache.upstreamCalled ?? !result.cache.hit,
      ttlSeconds,
    }),
  )
}

export function registerHotlistRoutes(app, { client, plainClient, readConfig, cache }) {
  app.get('/api/xueqiu/hot', async (req, res) => {
    try {
      await sendCachedHotlist(res, cache, 'xueqiu', async () => {
        const cookie = readConfig('XUEQIU_COOKIE')
        if (!cookie) throw new Error('XUEQIU_COOKIE is not configured')

        const response = await plainClient.get(
          'https://stock.xueqiu.com/v5/stock/hot_stock/list.json?size=100&_type=10&type=10',
          {
            timeout: 8000,
            headers: {
              ...DEFAULT_BROWSER_HEADERS,
              Referer: 'https://xueqiu.com/',
              Cookie: cookie,
            },
          },
        )

        return response.data
      })
    } catch (error) {
      console.warn('[xueqiu] hotlist unavailable:', error.message)
      sendDegraded(res, {
        source: 'xueqiu',
        error,
        fallbackData: fallback('xueqiu'),
      })
    }
  })

  app.get('/api/cls/hot', async (req, res) => {
    try {
      await sendCachedHotlist(res, cache, 'cls', async () => {
        const { params, sign } = generateCLSSign()
        const url = `https://api3.cls.cn/v1/hot_stock?app=${params.app}&os=${params.os}&sv=${params.sv}&sign=${sign}`

        const response = await client.get(url, {
          timeout: 8000,
          headers: { ...DEFAULT_BROWSER_HEADERS, Referer: 'https://www.cls.cn/' },
        })
        return response.data
      })
    } catch (error) {
      sendDegraded(res, { source: 'cls', error, fallbackData: fallback('cls') })
    }
  })

  app.post('/api/eastmoney/hot', async (req, res) => {
    try {
      await sendCachedHotlist(res, cache, 'eastmoney', async () => {
        const response = await client.post(
          'https://emappdata.eastmoney.com/stockrank/getAllCurrentList',
          {
            appId: 'appId01',
            globalId: '786e4c21-70dc-435a-93bb-38',
            pageNo: 1,
            pageSize: 100,
          },
          {
            timeout: 8000,
            headers: {
              'Content-Type': 'application/json',
              ...DEFAULT_BROWSER_HEADERS,
            },
          },
        )

        return response.data
      })
    } catch (error) {
      sendDegraded(res, { source: 'eastmoney', error, fallbackData: fallback('eastmoney') })
    }
  })

  app.get('/api/ths/hot', async (req, res) => {
    try {
      await sendCachedHotlist(res, cache, 'ths', async () => {
        const response = await client.get(
          'https://eq.10jqka.com.cn/open/api/hot_list/v1/hot_stock/a/hour/data.txt',
          { timeout: 8000, headers: DEFAULT_BROWSER_HEADERS },
        )

        return response.data
      })
    } catch (error) {
      sendDegraded(res, { source: 'ths', error, fallbackData: fallback('ths') })
    }
  })

  app.get('/api/kpl/hot', async (req, res) => {
    try {
      await sendCachedHotlist(res, cache, 'kpl', async () => {
        const url =
          'https://apphq.longhuvip.com/w1/api/index.php?Order=1&a=GetHotPHB&st=60&apiv=w21&Type=1&c=StockBidYiDong&PhoneOSNew=1&VerSion=5&_=1734567890000'

        const response = await plainClient.get(url, {
          timeout: 8000,
          headers: { 'User-Agent': 'curl/7.88.1', Accept: '*/*' },
          withCredentials: false,
        })

        return response.data
      })
    } catch (error) {
      console.error('[KPL] hotlist unavailable:', error.message)
      sendDegraded(res, { source: 'kpl', error, fallbackData: fallback('kpl') })
    }
  })

  app.post('/api/tdx/hot', async (req, res) => {
    try {
      await sendCachedHotlist(res, cache, 'tdx', async () => {
        const response = await client.post(
          'https://pul.tdx.com.cn/TQLEX?Entry=JNLPSE.hotStockList&RI=',
          [{ listType: '0', cycle: '0' }],
          {
            timeout: 8000,
            headers: {
              'Content-Type': 'application/json',
              ...DEFAULT_BROWSER_HEADERS,
            },
          },
        )

        return response.data
      })
    } catch (error) {
      sendDegraded(res, { source: 'tdx-hot', error, fallbackData: fallback('tdx') })
    }
  })

  app.get('/api/tgb/hot', async (req, res) => {
    try {
      await sendCachedHotlist(res, cache, 'tgb', async () => {
        const response = await client.get('https://www.tgb.cn/new/nrnt/getNoticeStock?type=H', {
          timeout: 8000,
          headers: DEFAULT_BROWSER_HEADERS,
        })
        return response.data
      })
    } catch (error) {
      sendDegraded(res, { source: 'tgb', error, fallbackData: fallback('tgb') })
    }
  })

  app.get('/api/dzh/hot', async (req, res) => {
    try {
      await sendCachedHotlist(res, cache, 'dzh', async () => {
        const response = await client.get(
          'https://imsearch.dzh.com.cn/stock/top?size=100&type=0&time=h',
          { timeout: 8000, headers: DEFAULT_BROWSER_HEADERS },
        )
        return response.data
      })
    } catch (error) {
      sendDegraded(res, { source: 'dzh', error, fallbackData: fallback('dzh') })
    }
  })
}
