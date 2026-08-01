import { createProxyRuntime } from './runtime.js'

const PORT = Number(process.env.PORT || 3000)
const { app, eventRadarBackgroundWorker } = await createProxyRuntime({ port: PORT })

const localRoutes = [
  'GET  /docs',
  'GET  /openapi.json',
  'GET  /health',
  'GET/POST /api/cache/startup-bundle',
  'POST /api/tdx/:entry（/api/tdx/hot 转发 QuantBoard）',
  'GET  /api/tdx-blocks',
  'GET  /api/tdx-blocks/codes',
  'POST /api/tdx-blocks/selection',
  'GET  /api/opening-signals/today',
  'POST /api/opening-signals',
  'GET  /api/notifications/event-radar/status',
  'POST /api/notifications/event-radar/test',
  'POST /api/notifications/event-radar/events',
  'POST /api/notifications/jump-signal',
  'GET  /api/local-voice/status',
  'POST /api/local-voice/speak',
  'POST /api/local-voice/test',
  'POST /api/local-voice/stop',
  'GET  /api/big-order/longhu/all-day',
  'POST /api/big-order/longhu/collect-list',
  'POST /api/big-order/longhu/collect',
]

const forwardedRoutes = [
  '八平台热榜 /api/{xueqiu|cls|eastmoney|ths|kpl|tdx|tgb|dzh}/hot',
  '行情 /api/quotes/tencent|sina、指数 /api/market/overview',
  '涨停池 /api/limitup/*、异动 /api/surge-stock/performance',
  '情绪 /api/sentiment/composite、事件 /api/xuangubao/events',
  '大单 /api/big-order/main-monitor|all-day',
  '既有 QuantBoard 前缀（ranktrend/snapshots/themes/journal 等）',
]

app.listen(PORT, () => {
  console.log('\n' + '='.repeat(60))
  console.log('股票数据代理服务器启动成功')
  console.log('='.repeat(60))
  console.log(`本地地址: http://localhost:${PORT}`)
  console.log('本地接口:')
  localRoutes.forEach((route) => console.log(`   ${route}`))
  console.log('转发到 QuantBoard(8000) 的接口:')
  forwardedRoutes.forEach((route) => console.log(`   ${route}`))
  console.log(`API 文档: http://localhost:${PORT}/docs`)
  if (eventRadarBackgroundWorker.start()) {
    console.log('异动雷达飞书后台推送: 已启动')
  } else {
    console.log('异动雷达飞书后台推送: 未启用或配置不完整')
  }
  console.log('='.repeat(60))
})
