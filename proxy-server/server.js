import { createProxyApp } from './app.js'

const PORT = Number(process.env.PORT || 3000)
const app = createProxyApp({ port: PORT })

const formalRoutes = [
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
  'POST /api/tdx/:entry',
  'GET  /api/limitup/10jqka',
  'GET  /api/surge-stock/performance',
  'GET  /api/market/overview',
  'GET  /api/sentiment/composite',
  'GET  /api/big-order/main-monitor',
  'GET  /api/big-order/all-day',
]

app.listen(PORT, () => {
  console.log('\n' + '='.repeat(60))
  console.log('股票数据代理服务器启动成功')
  console.log('='.repeat(60))
  console.log(`本地地址: http://localhost:${PORT}`)
  console.log('正式接口:')
  formalRoutes.forEach((route) => console.log(`   ${route}`))
  console.log('兼容接口: /api/theme/:id, /api/themes/batch, /api/limitup/detail, /api/quotes/tencent/spk')
  console.log('='.repeat(60))
})
