import { sendDegraded } from '../helpers/response.js'

export function registerTdxRoutes(app, { plainClient }) {
  app.post('/api/tdx/:entry', async (req, res, next) => {
    const { entry } = req.params
    // /api/tdx/hot 已迁移到 QuantBoard（通达信热榜），放行给 quantBoardProxy 转发。
    if (entry === 'hot') {
      next()
      return
    }
    try {
      const tdxUrl = `http://hot.icfqs.com:7615/TQLEX?Entry=${entry}&RI=`
      const requestBody = typeof req.body === 'string' ? req.body : JSON.stringify(req.body)

      const response = await plainClient.post(tdxUrl, requestBody, {
        headers: { 'Content-Type': 'text/plain' },
        timeout: 8000,
        validateStatus: (status) => status >= 200 && status < 500,
      })

      res.json(response.data)
    } catch (error) {
      sendDegraded(res, { source: 'tdx-proxy', error, fallbackData: { error: true } })
    }
  })
}
