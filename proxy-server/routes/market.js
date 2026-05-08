import { sendDegraded } from '../helpers/response.js'

export function registerMarketRoutes(app, { plainClient, port }) {
  app.get('/api/limitup/10jqka', async (req, res) => {
    try {
      const { date } = req.query
      const dateStr = date || new Date().toISOString().slice(0, 10).replace(/-/g, '')
      const url = `https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200&field=199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004,continue_day,continue_day_cnt,high_days,reason_type&filter=HS,GEM2STAR&order_field=330324&order_type=0&date=${dateStr}`

      const response = await plainClient.get(url, { timeout: 8000 })
      res.json(response.data)
    } catch (error) {
      sendDegraded(res, {
        source: 'limitup-10jqka',
        error,
        fallbackData: { data: { info: [] } },
      })
    }
  })

  app.get('/api/limitup/detail', async (req, res) => {
    res.set('X-Dragon-Board-Deprecated', 'true')
    const { date } = req.query
    const dateStr = date || new Date().toISOString().slice(0, 10).replace(/-/g, '')

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
