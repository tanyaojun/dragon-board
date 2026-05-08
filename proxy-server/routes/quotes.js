import iconv from 'iconv-lite'

import {
  DEFAULT_BROWSER_HEADERS,
  cleanCode,
  getMarketPrefix,
  parseCodeList,
} from '../helpers/http.js'
import { sendBadRequest, sendDegraded } from '../helpers/response.js'

const EMPTY_QUOTES = { rc: 0, data: { diff: [] } }

function requireCodes(req, res) {
  const codes = parseCodeList(req.query.codes)
  if (!req.query.codes || codes.length === 0) {
    sendBadRequest(res, 'missing_codes', '缺少 codes 参数')
    return null
  }
  return codes
}

export function registerQuoteRoutes(app, { plainClient }) {
  app.get('/api/quotes/eastmoney', async (req, res) => {
    const codeList = requireCodes(req, res)
    if (!codeList) return

    try {
      const marketCodes = codeList.map((code) => `${getMarketPrefix(code)}.${cleanCode(code)}`).join(',')

      const url =
        `https://push2.eastmoney.com/api/qt/ulist.np/get?` +
        `fltt=2` +
        `&ut=a79f54e3d4c8d44e494efb8f748db291` +
        `&secids=${marketCodes}` +
        `&fields=f2,f3,f5,f6,f8,f9,f12,f14,f20,f21,f23,f62,f66,f69,f184` +
        `&_=${Date.now()}`

      const response = await plainClient.get(url, {
        timeout: 8000,
        headers: DEFAULT_BROWSER_HEADERS,
      })

      res.json(response.data)
    } catch (error) {
      console.error('[东财行情] 失败:', error.message)
      sendDegraded(res, { source: 'quotes-eastmoney', error, fallbackData: EMPTY_QUOTES })
    }
  })

  app.get('/api/quotes/tencent', async (req, res) => {
    const codeList = requireCodes(req, res)
    if (!codeList) return

    try {
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

      const text = iconv.decode(response.data, 'gbk')
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

      res.json({ rc: 0, data: { diff: results } })
    } catch (error) {
      console.error('[腾讯行情] 失败:', error.message)
      sendDegraded(res, { source: 'quotes-tencent', error, fallbackData: EMPTY_QUOTES })
    }
  })

  app.get('/api/quotes/sina', async (req, res) => {
    const codeList = requireCodes(req, res)
    if (!codeList) return

    try {
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

      const text = iconv.decode(response.data, 'gbk')
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

      res.json({ rc: 0, data: { diff: results } })
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
