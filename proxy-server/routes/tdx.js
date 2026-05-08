import { sendDegraded } from '../helpers/response.js'

export function registerTdxRoutes(app, { plainClient }) {
  app.post('/api/tdx/:entry', async (req, res) => {
    const { entry } = req.params
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
