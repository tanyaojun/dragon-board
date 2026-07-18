import { createProxyRuntime } from './runtime.js'

const PORT = Number(process.env.PORT || 3000)
const { app, eventRadarBackgroundWorker } = await createProxyRuntime({ port: PORT })

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
  'GET  /api/quotes/tencent/minute',
  'GET  /api/quotes/eastmoney',
  'GET  /api/quotes/sina',
  'GET  /api/quotes/tencent/spk',
  'GET  /api/cache/startup-bundle',
  'POST /api/cache/startup-bundle',
  'POST /api/tdx/:entry',
  'GET  /api/limitup/10jqka',
  'GET  /api/limitup/detail',
  'GET  /api/surge-stock/performance',
  'GET  /api/xuangubao/events',
  'GET  /api/local-voice/status',
  'POST /api/local-voice/speak',
  'POST /api/local-voice/test',
  'POST /api/local-voice/stop',
  'GET  /api/notifications/event-radar/status',
  'POST /api/notifications/event-radar/test',
  'POST /api/notifications/event-radar/events',
  'GET  /api/market/overview',
  'GET  /api/sentiment/composite',
  'GET  /api/big-order/main-monitor',
  'GET  /api/big-order/all-day',
  'GET  /api/big-order/longhu/all-day',
  'POST /api/big-order/longhu/collect-list',
  'POST /api/big-order/longhu/collect',
  'GET  /api/big-order/ths-detail',
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
  if (eventRadarBackgroundWorker.start()) {
    console.log('异动雷达飞书后台推送: 已启动')
  } else {
    console.log('异动雷达飞书后台推送: 未启用或配置不完整')
  }
  console.log('='.repeat(60))
})
