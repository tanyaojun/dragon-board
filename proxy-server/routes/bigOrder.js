import { delay } from '../helpers/http.js'
import { sendBadRequest, sendDegraded } from '../helpers/response.js'

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

export function registerBigOrderRoutes(app, { plainClient }) {
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
