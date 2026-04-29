// D:\dragon-board\server.js
import express from 'express'
import cors from 'cors'
import axios from 'axios'
import { wrapper } from 'axios-cookiejar-support'
import { CookieJar } from 'tough-cookie'
import iconv from 'iconv-lite'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'
import {
  registerSnapshotRemoteRoutes,
  SNAPSHOT_DAY_BUNDLE_JSON_LIMIT,
} from './snapshotRemoteRoutes.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const app = express()
const PORT = 3000

const jar = new CookieJar()
const client = wrapper(axios.create({ jar, withCredentials: true, maxRedirects: 5 }))

app.use(cors({ origin: '*', methods: ['GET', 'POST'] }))
app.use(express.json({ limit: SNAPSHOT_DAY_BUNDLE_JSON_LIMIT }))

// 日志中间件
app.use((req, res, next) => {
  console.log(`[${new Date().toLocaleTimeString()}] ${req.method} ${req.url}`)
  next()
})

// ========== MD5/SHA1签名算法 ==========
const hexcase = 0
const b64pad = ''
const chrsz = 8

function hex_md5(s) {
  return binl2hex(core_md5(str2binl(s), s.length * chrsz))
}

function core_md5(x, len) {
  x[len >> 5] |= 0x80 << (len % 32)
  x[(((len + 64) >>> 9) << 4) + 14] = len

  let a = 1732584193,
    b = -271733879,
    c = -1732584194,
    d = 271733878

  for (let i = 0; i < x.length; i += 16) {
    const olda = a,
      oldb = b,
      oldc = c,
      oldd = d

    a = md5_ff(a, b, c, d, x[i + 0], 7, -680876936)
    d = md5_ff(d, a, b, c, x[i + 1], 12, -389564586)
    c = md5_ff(c, d, a, b, x[i + 2], 17, 606105819)
    b = md5_ff(b, c, d, a, x[i + 3], 22, -1044525330)
    a = md5_ff(a, b, c, d, x[i + 4], 7, -176418897)
    d = md5_ff(d, a, b, c, x[i + 5], 12, 1200080426)
    c = md5_ff(c, d, a, b, x[i + 6], 17, -1473231341)
    b = md5_ff(b, c, d, a, x[i + 7], 22, -45705983)
    a = md5_ff(a, b, c, d, x[i + 8], 7, 1770035416)
    d = md5_ff(d, a, b, c, x[i + 9], 12, -1958414417)
    c = md5_ff(c, d, a, b, x[i + 10], 17, -42063)
    b = md5_ff(b, c, d, a, x[i + 11], 22, -1990404162)
    a = md5_ff(a, b, c, d, x[i + 12], 7, 1804603682)
    d = md5_ff(d, a, b, c, x[i + 13], 12, -40341101)
    c = md5_ff(c, d, a, b, x[i + 14], 17, -1502002290)
    b = md5_ff(b, c, d, a, x[i + 15], 22, 1236535329)

    a = md5_gg(a, b, c, d, x[i + 1], 5, -165796510)
    d = md5_gg(d, a, b, c, x[i + 6], 9, -1069501632)
    c = md5_gg(c, d, a, b, x[i + 11], 14, 643717713)
    b = md5_gg(b, c, d, a, x[i + 0], 20, -373897302)
    a = md5_gg(a, b, c, d, x[i + 5], 5, -701558691)
    d = md5_gg(d, a, b, c, x[i + 10], 9, 38016083)
    c = md5_gg(c, d, a, b, x[i + 15], 14, -660478335)
    b = md5_gg(b, c, d, a, x[i + 4], 20, -405537848)
    a = md5_gg(a, b, c, d, x[i + 9], 5, 568446438)
    d = md5_gg(d, a, b, c, x[i + 14], 9, -1019803690)
    c = md5_gg(c, d, a, b, x[i + 3], 14, -187363961)
    b = md5_gg(b, c, d, a, x[i + 8], 20, 1163531501)
    a = md5_gg(a, b, c, d, x[i + 13], 5, -1444681467)
    d = md5_gg(d, a, b, c, x[i + 2], 9, -51403784)
    c = md5_gg(c, d, a, b, x[i + 7], 14, 1735328473)
    b = md5_gg(b, c, d, a, x[i + 12], 20, -1926607734)

    a = md5_hh(a, b, c, d, x[i + 5], 4, -378558)
    d = md5_hh(d, a, b, c, x[i + 8], 11, -2022574463)
    c = md5_hh(c, d, a, b, x[i + 11], 16, 1839030562)
    b = md5_hh(b, c, d, a, x[i + 14], 23, -35309556)
    a = md5_hh(a, b, c, d, x[i + 1], 4, -1530992060)
    d = md5_hh(d, a, b, c, x[i + 4], 11, 1272893353)
    c = md5_hh(c, d, a, b, x[i + 7], 16, -155497632)
    b = md5_hh(b, c, d, a, x[i + 10], 23, -1094730640)
    a = md5_hh(a, b, c, d, x[i + 13], 4, 681279174)
    d = md5_hh(d, a, b, c, x[i + 0], 11, -358537222)
    c = md5_hh(c, d, a, b, x[i + 3], 16, -722521979)
    b = md5_hh(b, c, d, a, x[i + 6], 23, 76029189)
    a = md5_hh(a, b, c, d, x[i + 9], 4, -640364487)
    d = md5_hh(d, a, b, c, x[i + 12], 11, -421815835)
    c = md5_hh(c, d, a, b, x[i + 15], 16, 530742520)
    b = md5_hh(b, c, d, a, x[i + 2], 23, -995338651)

    a = md5_ii(a, b, c, d, x[i + 0], 6, -198630844)
    d = md5_ii(d, a, b, c, x[i + 7], 10, 1126891415)
    c = md5_ii(c, d, a, b, x[i + 14], 15, -1416354905)
    b = md5_ii(b, c, d, a, x[i + 5], 21, -57434055)
    a = md5_ii(a, b, c, d, x[i + 12], 6, 1700485571)
    d = md5_ii(d, a, b, c, x[i + 3], 10, -1894986606)
    c = md5_ii(c, d, a, b, x[i + 10], 15, -1051523)
    b = md5_ii(b, c, d, a, x[i + 1], 21, -2054922799)
    a = md5_ii(a, b, c, d, x[i + 8], 6, 1873313359)
    d = md5_ii(d, a, b, c, x[i + 15], 10, -30611744)
    c = md5_ii(c, d, a, b, x[i + 6], 15, -1560198380)
    b = md5_ii(b, c, d, a, x[i + 13], 21, 1309151649)
    a = md5_ii(a, b, c, d, x[i + 4], 6, -145523070)
    d = md5_ii(d, a, b, c, x[i + 11], 10, -1120210379)
    c = md5_ii(c, d, a, b, x[i + 2], 15, 718787259)
    b = md5_ii(b, c, d, a, x[i + 9], 21, -343485551)

    a = safe_add(a, olda)
    b = safe_add(b, oldb)
    c = safe_add(c, oldc)
    d = safe_add(d, oldd)
  }
  return [a, b, c, d]
}

function md5_cmn(q, a, b, x, s, t) {
  return safe_add(bit_rol(safe_add(safe_add(a, q), safe_add(x, t)), s), b)
}

function md5_ff(a, b, c, d, x, s, t) {
  return md5_cmn((b & c) | (~b & d), a, b, x, s, t)
}

function md5_gg(a, b, c, d, x, s, t) {
  return md5_cmn((b & d) | (c & ~d), a, b, x, s, t)
}

function md5_hh(a, b, c, d, x, s, t) {
  return md5_cmn(b ^ c ^ d, a, b, x, s, t)
}

function md5_ii(a, b, c, d, x, s, t) {
  return md5_cmn(c ^ (b | ~d), a, b, x, s, t)
}

function safe_add(x, y) {
  const lsw = (x & 0xffff) + (y & 0xffff)
  const msw = (x >> 16) + (y >> 16) + (lsw >> 16)
  return (msw << 16) | (lsw & 0xffff)
}

function bit_rol(num, cnt) {
  return (num << cnt) | (num >>> (32 - cnt))
}

function str2binl(str) {
  const bin = []
  const mask = (1 << chrsz) - 1
  for (let i = 0; i < str.length * chrsz; i += chrsz) {
    bin[i >> 5] |= (str.charCodeAt(i / chrsz) & mask) << (i % 32)
  }
  return bin
}

function binl2hex(binarray) {
  const hex_tab = hexcase ? '0123456789ABCDEF' : '0123456789abcdef'
  let str = ''
  for (let i = 0; i < binarray.length * 4; i++) {
    str +=
      hex_tab.charAt((binarray[i >> 2] >> ((i % 4) * 8 + 4)) & 0xf) +
      hex_tab.charAt((binarray[i >> 2] >> ((i % 4) * 8)) & 0xf)
  }
  return str
}

function hex_sha1(s) {
  return binb2hex(core_sha1(str2binb(s), s.length * chrsz))
}

function core_sha1(x, len) {
  x[len >> 5] |= 0x80 << (24 - (len % 32))
  x[(((len + 64) >> 9) << 4) + 15] = len

  const w = []
  let a = 1732584193,
    b = -271733879,
    c = -1732584194,
    d = 271733878,
    e = -1009589776

  for (let i = 0; i < x.length; i += 16) {
    const olda = a,
      oldb = b,
      oldc = c,
      oldd = d,
      olde = e

    for (let j = 0; j < 80; j++) {
      if (j < 16) w[j] = x[i + j]
      else w[j] = bit_rol(w[j - 3] ^ w[j - 8] ^ w[j - 14] ^ w[j - 16], 1)

      const t = safe_add(
        safe_add(bit_rol(a, 5), sha1_ft(j, b, c, d)),
        safe_add(safe_add(e, w[j]), sha1_kt(j)),
      )
      e = d
      d = c
      c = bit_rol(b, 30)
      b = a
      a = t
    }

    a = safe_add(a, olda)
    b = safe_add(b, oldb)
    c = safe_add(c, oldc)
    d = safe_add(d, oldd)
    e = safe_add(e, olde)
  }
  return [a, b, c, d, e]
}

function sha1_ft(t, b, c, d) {
  if (t < 20) return (b & c) | (~b & d)
  if (t < 40) return b ^ c ^ d
  if (t < 60) return (b & c) | (b & d) | (c & d)
  return b ^ c ^ d
}

function sha1_kt(t) {
  return t < 20 ? 1518500249 : t < 40 ? 1859775393 : t < 60 ? -1894007588 : -899497514
}

function str2binb(str) {
  const bin = []
  const mask = (1 << chrsz) - 1
  for (let i = 0; i < str.length * chrsz; i += chrsz) {
    bin[i >> 5] |= (str.charCodeAt(i / chrsz) & mask) << (32 - chrsz - (i % 32))
  }
  return bin
}

function binb2hex(binarray) {
  const hex_tab = hexcase ? '0123456789ABCDEF' : '0123456789abcdef'
  let str = ''
  for (let i = 0; i < binarray.length * 4; i++) {
    str +=
      hex_tab.charAt((binarray[i >> 2] >> ((3 - (i % 4)) * 8 + 4)) & 0xf) +
      hex_tab.charAt((binarray[i >> 2] >> ((3 - (i % 4)) * 8)) & 0xf)
  }
  return str
}

function generateCLSSign() {
  const params = { app: 'cailianpress', os: 'android', sv: '835' }
  const keys = Object.keys(params).sort()
  const str = keys.map((k) => k + '=' + params[k]).join('&')

  const sha1Str = hex_sha1(str)
  const md5Str = hex_md5(sha1Str)

  return { params, sign: md5Str }
}

function cleanCode(code) {
  return code.replace(/[^0-9]/g, '').padStart(6, '0')
}

function getMarketPrefix(code) {
  const c = cleanCode(code)
  return c.startsWith('6') || c.startsWith('11') || c.startsWith('51') ? '1' : '0'
}

// ========== 健康检查 ==========
app.get('/health', (req, res) => {
  res.json({ status: 'ok', time: new Date().toLocaleString() })
})

// ========== 各平台接口 ==========
app.get('/api/xueqiu/hot', async (req, res) => {
  try {
    const cookie =
      'xq_a_token=0c005f2d08ad61d883f7f562a47ef054a834818e; xqat=0c005f2d08ad61d883f7f562a47ef054a834818e; xq_r_token=5ab66336a5d267c9663141e65a3e24b1cd3b435e; u=9546611598'

    const response = await axios.get(
      'https://stock.xueqiu.com/v5/stock/hot_stock/list.json?size=100&_type=10&type=10',
      {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
          Referer: 'https://xueqiu.com/',
          Cookie: cookie,
        },
      },
    )

    res.json(response.data)
  } catch (error) {
    res.status(500).json({ error: error.message })
  }
})

app.get('/api/cls/hot', async (req, res) => {
  try {
    const { params, sign } = generateCLSSign()
    const url = `https://api3.cls.cn/v1/hot_stock?app=${params.app}&os=${params.os}&sv=${params.sv}&sign=${sign}`

    const response = await client.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        Referer: 'https://www.cls.cn/',
      },
    })

    res.json(response.data)
  } catch (error) {
    res.status(500).json({ error: error.message })
  }
})

app.post('/api/eastmoney/hot', async (req, res) => {
  try {
    const response = await client.post(
      'https://emappdata.eastmoney.com/stockrank/getAllCurrentList',
      {
        appId: 'appId01',
        globalId: '786e4c21-70dc-435a-93bb-38',
        pageNo: 1,
        pageSize: 100,
      },
      {
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        },
      },
    )

    res.json(response.data)
  } catch (error) {
    res.status(500).json({ error: error.message })
  }
})

app.get('/api/ths/hot', async (req, res) => {
  try {
    const response = await client.get(
      'https://eq.10jqka.com.cn/open/api/hot_list/v1/hot_stock/a/hour/data.txt',
      {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        },
      },
    )

    res.json(response.data)
  } catch (error) {
    res.status(500).json({ error: error.message })
  }
})

app.get('/api/kpl/hot', async (req, res) => {
  try {
    // 关键1: 使用CMD curl中的完整URL（带时间戳参数）
    const url =
      'https://apphq.longhuvip.com/w1/api/index.php?Order=1&a=GetHotPHB&st=60&apiv=w21&Type=1&c=StockBidYiDong&PhoneOSNew=1&VerSion=5&_=1734567890000'

    const response = await axios.get(url, {
      headers: {
        'User-Agent': 'curl/7.88.1', // ← 关键：伪装成curl
        Accept: '*/*', // ← 关键：接受任何类型
      },
      withCredentials: false, // ← 关键：不发送Cookie
    })

    res.json(response.data)
  } catch (error) {
    console.error('[KPL] 修复版请求失败:', error.message)
    res.status(500).json({ error: error.message })
  }
})

app.post('/api/tdx/hot', async (req, res) => {
  try {
    const response = await client.post(
      'https://pul.tdx.com.cn/TQLEX?Entry=JNLPSE.hotStockList&RI=',
      [{ listType: '0', cycle: '0' }],
      {
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        },
      },
    )

    res.json(response.data)
  } catch (error) {
    res.status(500).json({ error: error.message })
  }
})

app.get('/api/tgb/hot', async (req, res) => {
  try {
    const response = await client.get('https://www.tgb.cn/new/nrnt/getNoticeStock?type=H', {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
      },
    })
    res.json(response.data)
  } catch (error) {
    res.status(500).json({ error: error.message })
  }
})

app.get('/api/dzh/hot', async (req, res) => {
  try {
    const response = await client.get(
      'https://imsearch.dzh.com.cn/stock/top?size=100&type=0&time=h',
      {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        },
      },
    )
    res.json(response.data)
  } catch (error) {
    res.status(500).json({ error: error.message })
  }
})

// ========== 行情接口（纯代理） ==========

// 东财行情
app.get('/api/quotes/eastmoney', async (req, res) => {
  try {
    const { codes } = req.query
    if (!codes) return res.status(400).json({ error: '缺少 codes 参数' })

    const codeList = codes.split(',').filter((c) => c && c.length >= 6)

    const marketCodes = codeList
      .map((code) => `${getMarketPrefix(code)}.${cleanCode(code)}`)
      .join(',')

    const url =
      `https://push2.eastmoney.com/api/qt/ulist.np/get?` +
      `fltt=2` +
      `&ut=a79f54e3d4c8d44e494efb8f748db291` +
      `&secids=${marketCodes}` +
      `&fields=f2,f3,f5,f6,f8,f9,f12,f14,f20,f21,f23,f62,f66,f69,f184` +
      `&_=${Date.now()}`

    const response = await axios.get(url, {
      timeout: 8000,
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' },
    })

    res.json(response.data)
  } catch (error) {
    console.error('[东财行情] 失败:', error.message)
    res.status(500).json({ error: error.message })
  }
})

// 腾讯行情
app.get('/api/quotes/tencent', async (req, res) => {
  try {
    const { codes } = req.query
    if (!codes) return res.status(400).json({ error: '缺少 codes 参数' })

    const codeList = codes.split(',').filter((c) => c && c.length >= 6)

    const tencentCodes = codeList
      .map((code) => {
        const c = cleanCode(code)
        return c.startsWith('6') ? `sh${c}` : `sz${c}`
      })
      .join(',')

    const url = `http://qt.gtimg.cn/q=${tencentCodes}`
    const response = await axios.get(url, {
      timeout: 5000,
      responseType: 'arraybuffer',
    })

    const text = iconv.decode(response.data, 'gbk')
    const lines = text.split('\n')
    const results = []

    lines.forEach((line) => {
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
    res.status(500).json({ error: error.message })
  }
})

// 新浪行情
app.get('/api/quotes/sina', async (req, res) => {
  try {
    const { codes } = req.query
    if (!codes) return res.status(400).json({ error: '缺少 codes 参数' })

    const codeList = codes.split(',').filter((c) => c && c.length >= 6)

    const sinaCodes = codeList
      .map((code) => {
        const c = cleanCode(code)
        return c.startsWith('6') ? `sh${c}` : `sz${c}`
      })
      .join(',')

    const url = `http://hq.sinajs.cn/list=${sinaCodes}`
    const response = await axios.get(url, {
      timeout: 5000,
      responseType: 'arraybuffer',
      headers: { Referer: 'http://finance.sina.com.cn' },
    })

    const text = iconv.decode(response.data, 'gbk')
    const lines = text.split('\n')
    const results = []

    lines.forEach((line) => {
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
    res.status(500).json({ error: error.message })
  }
})

// 腾讯盘口
app.get('/api/quotes/tencent/spk', async (req, res) => {
  try {
    const { codes } = req.query
    if (!codes) return res.status(400).json({ error: '缺少 codes 参数' })

    const codeList = codes.split(',').filter((c) => c && c.length >= 6)

    const spkCodes = codeList
      .map((code) => {
        const c = cleanCode(code)
        const market = c.startsWith('6') ? 'sh' : 'sz'
        return `s_pk${market}${c}`
      })
      .join(',')

    const url = `http://qt.gtimg.cn/q=${spkCodes}`
    const response = await axios.get(url, {
      timeout: 5000,
      responseType: 'arraybuffer',
    })

    const text = iconv.decode(response.data, 'gbk')
    const lines = text.split('\n')
    const results = []

    lines.forEach((line) => {
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

    res.json({ rc: 0, data: { diff: results } })
  } catch (error) {
    console.error('[腾讯盘口] 失败:', error.message)
    res.status(500).json({ error: error.message })
  }
})

// ========== 题材数据 ==========
app.get('/api/theme/:id', async (req, res) => {
  const { id } = req.params
  const { page = 1, pageSize = 500 } = req.query

  try {
    const baseUrl = 'https://applhb.longhuvip.com/w1/api/index.php'
    const url = new URL(baseUrl)
    url.searchParams.append('a', 'InfoGet')
    url.searchParams.append('apiv', 'w43')
    url.searchParams.append('c', 'Theme')
    url.searchParams.append('PhoneOSNew', '1')
    url.searchParams.append('UserID', '397605')
    url.searchParams.append('DeviceID', '548d826f-a2a7-301a-b148-920f31f15331')
    url.searchParams.append('VerSion', '5.22.0.2')
    url.searchParams.append('Token', 'df9cadb87bbba7d04e9fcbaa2aa229b3')
    url.searchParams.append('ID', id)
    url.searchParams.append('page', page)
    url.searchParams.append('pageSize', pageSize)

    const response = await axios.get(url.toString(), { timeout: 8000 })
    res.json(response.data)
  } catch (error) {
    res.status(500).json({ error: error.message })
  }
})

app.post('/api/themes/batch', express.json(), async (req, res) => {
  const { ids } = req.body
  if (!ids || !Array.isArray(ids) || ids.length === 0) {
    return res.status(400).json({ error: '缺少题材ID列表' })
  }
  if (ids.length > 20) return res.status(400).json({ error: '一次最多请求20个题材' })

  const results = []
  const errors = []

  for (const id of ids) {
    try {
      const baseUrl = 'https://applhb.longhuvip.com/w1/api/index.php'
      const url = new URL(baseUrl)
      url.searchParams.append('a', 'InfoGet')
      url.searchParams.append('apiv', 'w43')
      url.searchParams.append('c', 'Theme')
      url.searchParams.append('PhoneOSNew', '1')
      url.searchParams.append('UserID', '397605')
      url.searchParams.append('DeviceID', '548d826f-a2a7-301a-b148-920f31f15331')
      url.searchParams.append('VerSion', '5.22.0.2')
      url.searchParams.append('Token', 'df9cadb87bbba7d04e9fcbaa2aa229b3')
      url.searchParams.append('ID', id)
      url.searchParams.append('page', '1')
      url.searchParams.append('pageSize', '500')

      const response = await axios.get(url.toString(), { timeout: 8000 })
      results.push({ id, data: response.data, success: true })
    } catch (error) {
      errors.push({ id, error: error.message })
    }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }

  res.json({ success: results.length, failed: errors.length, results, errors, total: ids.length })
})

// ========== KPL大单数据 ==========

/**
 * 生成设备ID（模拟MD5）- 简化版
 */
function generateDeviceId() {
  const input = Date.now() + Math.random().toString(36)
  // 使用简单的哈希函数替代 MD5
  let hash = 0
  for (let i = 0; i < input.length; i++) {
    const char = input.charCodeAt(i)
    hash = (hash << 5) - hash + char
    hash = hash & hash // 转换为32位整数
  }
  return Math.abs(hash).toString(16).padStart(32, '0').substring(0, 32)
}

/**
 * 获取大单数据（主力监控）
 */
app.get('/api/big-order/main-monitor', async (req, res) => {
  try {
    const { stockCode, limit = 100, money = 0, index = 0 } = req.query

    if (!stockCode) {
      return res.status(400).json({ error: '缺少 stockCode 参数' })
    }

    const deviceId = generateDeviceId()

    const url = new URL('https://apphwhq.longhuvip.com/w1/api/index.php')
    url.searchParams.append('Order', '0')
    url.searchParams.append('st', limit)
    url.searchParams.append('a', 'GetMainMonitor_w30')
    url.searchParams.append('c', 'StockYiDongKanPan')
    url.searchParams.append('PhoneOSNew', '1')
    url.searchParams.append('DeviceID', deviceId)
    url.searchParams.append('VerSion', '5.17.0.4')
    url.searchParams.append('Index', index)
    url.searchParams.append('Money', money)
    url.searchParams.append('apiv', 'w36')
    url.searchParams.append('StockID', stockCode)
    url.searchParams.append('IsBS', '0')

    const response = await axios.get(url.toString(), {
      timeout: 15000,
      headers: {
        'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 9; MI 8 MIUI/V11.0.5.0.PEACNXM)',
      },
    })

    res.json(response.data)
  } catch (error) {
    console.error('[大单监控] 失败:', error.message)
    res.status(500).json({ error: error.message })
  }
})

/**
 * 获取全天大单数据（分页）
 */
app.get('/api/big-order/all-day', async (req, res) => {
  try {
    const { stockCode, money = 0 } = req.query

    if (!stockCode) {
      return res.status(400).json({ error: '缺少 stockCode 参数' })
    }

    const pageSize = 500
    let index = 0
    let allData = []
    const deviceId = generateDeviceId()

    while (true) {
      const url = new URL('https://apphwhq.longhuvip.com/w1/api/index.php')
      url.searchParams.append('Order', '0')
      url.searchParams.append('st', pageSize)
      url.searchParams.append('a', 'GetMainMonitor_w30')
      url.searchParams.append('c', 'StockYiDongKanPan')
      url.searchParams.append('PhoneOSNew', '1')
      url.searchParams.append('DeviceID', deviceId)
      url.searchParams.append('VerSion', '5.17.0.4')
      url.searchParams.append('Index', index)
      url.searchParams.append('Money', money)
      url.searchParams.append('apiv', 'w36')
      url.searchParams.append('StockID', stockCode)
      url.searchParams.append('IsBS', '0')

      const response = await axios.get(url.toString(), {
        timeout: 10000,
        headers: {
          'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 9; MI 8 MIUI/V11.0.5.0.PEACNXM)',
        },
      })

      const list = response.data.List || []
      if (list.length === 0) break

      allData = allData.concat(list)

      if (list.length < pageSize) break

      index += pageSize
      await new Promise((resolve) => setTimeout(resolve, 100))
    }

    res.json({ List: allData })
  } catch (error) {
    console.error('[全天大单] 失败:', error.message)
    res.status(500).json({ error: error.message })
  }
})

// ========== TDX 通用数据代理 ==========
app.post('/api/tdx/:entry', async (req, res) => {
  const { entry } = req.params
  try {
    const tdxUrl = `http://hot.icfqs.com:7615/TQLEX?Entry=${entry}&RI=`
    const requestBody = typeof req.body === 'string' ? req.body : JSON.stringify(req.body)

    const response = await axios.post(tdxUrl, requestBody, {
      headers: { 'Content-Type': 'text/plain' },
      timeout: 8000,
      validateStatus: (status) => true,
    })

    res.json(response.data)
  } catch (error) {
    res.status(500).json({ error: error.message })
  }
})

// ========== 涨停板数据 ==========
app.get('/api/limitup/10jqka', async (req, res) => {
  try {
    const { date } = req.query
    const dateStr = date || new Date().toISOString().slice(0, 10).replace(/-/g, '')
    const url = `https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200&field=199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004,continue_day,continue_day_cnt,high_days,reason_type&filter=HS,GEM2STAR&order_field=330324&order_type=0&date=${dateStr}`

    const response = await axios.get(url, { timeout: 8000 })
    res.json(response.data)
  } catch (error) {
    res.status(500).json({ error: error.message })
  }
})

app.get('/api/limitup/detail', async (req, res) => {
  try {
    const { date } = req.query
    const dateStr = date || new Date().toISOString().slice(0, 10).replace(/-/g, '')

    const urls = [
      `https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool_detail?page=1&limit=200&date=${dateStr}`,
      `https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200&date=${dateStr}`,
    ]

    for (const url of urls) {
      try {
        const res = await axios.get(url, { timeout: 5000 })
        if (res.data) {
          return res.json(res.data)
        }
      } catch (e) {}
    }
  } catch (error) {
    res.status(500).json({ error: error.message })
  }
})

app.get('/api/surge-stock/performance', async (req, res) => {
  try {
    // ✅ 修复参数：去掉单引号
    const response = await axios.get(
      'https://flash-api.xuangubao.cn/api/surge_stock/stocks?normal=true&uplimit=true',
      { timeout: 8000 },
    )
    res.json(response.data)
  } catch (error) {
    console.error('[surge-stock] 接口失败:', error.message)
    res.status(500).json({ error: error.message })
  }
})

// ========== 市场数据 ==========
app.get('/api/market/overview', async (req, res) => {
  try {
    const thsRes = await axios.get('https://dq.10jqka.com.cn/fuyao/v2/board/real_index_data', {
      timeout: 3000,
    })
    if (thsRes.data?.data) {
      return res.json(thsRes.data.data)
    }
  } catch (error) {
    res.status(500).json({ error: error.message })
  }
})

app.get('/api/sentiment/composite', async (req, res) => {
  try {
    const [overviewRes, limitupRes, surgeRes] = await Promise.allSettled([
      axios.get(`http://localhost:${PORT}/api/market/overview`),
      axios.get(`http://localhost:${PORT}/api/limitup/10jqka`),
      axios.get(`http://localhost:${PORT}/api/surge-stock/performance`),
    ])

    res.json({
      timestamp: Date.now(),
      overview: overviewRes.status === 'fulfilled' ? overviewRes.value.data : null,
      limitup: limitupRes.status === 'fulfilled' ? limitupRes.value.data : null,
      yesterdayPerformance: surgeRes.status === 'fulfilled' ? surgeRes.value.data : null,
    })
  } catch (error) {
    res.status(500).json({ error: error.message })
  }
})

registerSnapshotRemoteRoutes(app)

app.use((error, req, res, next) => {
  if (!error) {
    next()
    return
  }
  if (error.type === 'entity.too.large') {
    res.status(413).json({
      ok: false,
      errorCode: 'remote_day_bundle_payload_too_large',
      message: `snapshot payload exceeds proxy json limit (${SNAPSHOT_DAY_BUNDLE_JSON_LIMIT})`,
    })
    return
  }
  res.status(error.status || 500).json({
    ok: false,
    errorCode: 'proxy_unhandled_error',
    message: error.message || String(error),
  })
})

app.use('/static', express.static(join(__dirname, 'public')))

// ========== 启动服务器 ==========
app.listen(PORT, () => {
  console.log('\n' + '='.repeat(60))
  console.log('🚀 股票数据代理服务器启动成功！')
  console.log('='.repeat(60))
  console.log(`📍 本地地址: http://localhost:${PORT}`)
  console.log('='.repeat(60))
  console.log('\n📡 可用接口:')
  console.log('   GET  /health')
  console.log('   GET  /api/xueqiu/hot')
  console.log('   GET  /api/cls/hot')
  console.log('   POST /api/eastmoney/hot')
  console.log('   GET  /api/ths/hot')
  console.log('   GET  /api/kpl/hot')
  console.log('   POST /api/tdx/hot')
  console.log('   GET  /api/tgb/hot')
  console.log('   GET  /api/dzh/hot')
  console.log('   GET  /api/quotes/tencent')
  console.log('   GET  /api/quotes/eastmoney')
  console.log('   GET  /api/quotes/sina')
  console.log('   GET  /api/quotes/tencent/spk')
  console.log('   GET  /api/limitup/10jqka')
  console.log('   GET  /api/limitup/detail')
  console.log('   GET  /api/surge-stock/performance')
  console.log('   GET  /api/market/overview')
  console.log('   GET  /api/sentiment/composite')
  console.log('   GET  /api/theme/:id')
  console.log('   POST /api/themes/batch')
  console.log('='.repeat(60))
})
