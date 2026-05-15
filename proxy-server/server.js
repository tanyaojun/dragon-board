import { createProxyApp } from './app.js'
import { createConfigReader, loadEnvFile } from './helpers/http.js'
import { createProxyRedisCache } from './helpers/proxyCache.js'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const PORT = Number(process.env.PORT || 3000)
const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const localEnv = loadEnvFile(join(__dirname, '.env.local'))
const readConfig = createConfigReader(localEnv)
const cache = await createProxyRedisCache({ readConfig })
const app = createProxyApp({ port: PORT, localEnv, readConfig, cache })

const formalRoutes = [
  'GET  /docs',
  'GET  /openapi.json',
  'GET  /health',
  'GET  /api/xueqiu/hot',
  'GET  /api/cls/hot',
  'POST /api/eastmoney/hot',
  'GET  /api/ths/hot',
  'GET  /api/kpl/hot',
  'POST /api/tdx/hot',
  'GET  /api/tgb/hot',
  'GET  /api/dzh/hot',
  'GET  /api/quotes/tencent',
  'GET  /api/quotes/eastmoney',
  'GET  /api/quotes/sina',
  'GET  /api/quotes/tencent/spk',
  'POST /api/tdx/:entry',
  'GET  /api/limitup/10jqka',
  'GET  /api/limitup/detail',
  'GET  /api/surge-stock/performance',
  'GET  /api/xuangubao/events',
  'GET  /api/market/overview',
  'GET  /api/sentiment/composite',
  'GET  /api/big-order/main-monitor',
  'GET  /api/big-order/all-day',
  'GET  /api/theme/:id',
  'POST /api/themes/batch',
]

app.listen(PORT, () => {
  console.log('\n' + '='.repeat(60))
  console.log('股票数据代理服务器启动成功')
  console.log('='.repeat(60))
  console.log(`本地地址: http://localhost:${PORT}`)
  console.log('正式接口:')
  formalRoutes.forEach((route) => console.log(`   ${route}`))
  console.log(`API 文档: http://localhost:${PORT}/docs`)
  console.log('='.repeat(60))
})
