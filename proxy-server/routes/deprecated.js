import { delay } from '../helpers/http.js'
import { sendBadRequest, sendDegraded } from '../helpers/response.js'

function buildThemeUrl(id, page = 1, pageSize = 500) {
  const url = new URL('https://applhb.longhuvip.com/w1/api/index.php')
  url.searchParams.append('a', 'InfoGet')
  url.searchParams.append('apiv', 'w43')
  url.searchParams.append('c', 'Theme')
  url.searchParams.append('PhoneOSNew', '1')
  url.searchParams.append('UserID', '397605')
  url.searchParams.append('DeviceID', '548d826f-a2a7-301a-b148-920f31f15331')
  url.searchParams.append('VerSion', '5.22.0.2')
  url.searchParams.append('Token', 'df9cadb87bbba7d04e9fcbaa2aa229b3')
  url.searchParams.append('ID', id)
  url.searchParams.append('page', String(page))
  url.searchParams.append('pageSize', String(pageSize))
  return url
}

export function registerDeprecatedRoutes(app, { plainClient }) {
  app.get('/api/theme/:id', async (req, res) => {
    res.set('X-Dragon-Board-Deprecated', 'true')
    const { id } = req.params
    const { page = 1, pageSize = 500 } = req.query

    try {
      const response = await plainClient.get(buildThemeUrl(id, page, pageSize).toString(), {
        timeout: 8000,
      })
      res.json({ ...response.data, deprecated: true })
    } catch (error) {
      sendDegraded(res, {
        source: 'theme-detail-deprecated',
        error,
        fallbackData: { deprecated: true, data: null },
        message: 'deprecated theme proxy unavailable; use QuantBoard /api/themes/mapping',
      })
    }
  })

  app.post('/api/themes/batch', async (req, res) => {
    res.set('X-Dragon-Board-Deprecated', 'true')
    const { ids } = req.body
    if (!ids || !Array.isArray(ids) || ids.length === 0) {
      return sendBadRequest(res, 'missing_theme_ids', '缺少题材ID列表')
    }
    if (ids.length > 20) {
      return sendBadRequest(res, 'too_many_theme_ids', '一次最多请求20个题材')
    }

    const results = []
    const errors = []

    for (const id of ids) {
      try {
        const response = await plainClient.get(buildThemeUrl(id).toString(), { timeout: 8000 })
        results.push({ id, data: response.data, success: true, deprecated: true })
      } catch (error) {
        errors.push({ id, error: error.message })
      }
      await delay(200)
    }

    res.json({
      deprecated: true,
      success: results.length,
      failed: errors.length,
      results,
      errors,
      total: ids.length,
    })
  })
}
