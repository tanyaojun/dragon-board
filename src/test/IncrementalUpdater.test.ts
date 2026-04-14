// src/tests/IncrementalUpdater.test.ts
export async function testIncrementalUpdater() {
  console.log('========== 开始测试 IncrementalUpdater ==========')

  // 1. 确保有股票数据
  console.log('当前股票数量:', dataLayer.getStocks().length)

  // 2. 初始化
  await incrementalUpdater.init()
  console.log('✅ IncrementalUpdater 初始化完成')

  // 3. 获取状态，验证热点股票数量
  const status = incrementalUpdater.getStatus()
  console.log('IncrementalUpdater 状态:', status)
  console.assert(status.hotStocksLimit === 100, '热点股票数量应为100只')
  console.log('✅ 热点股票数量验证通过')

  // 4. 测试手动设置热点股票数量
  console.log('\n--- 测试设置热点股票数量 ---')
  incrementalUpdater.setHotStocksLimit(200)
  console.assert(incrementalUpdater.getHotStocksLimit() === 200, '热点股票数量应更新为200只')
  console.log('✅ 手动设置验证通过')

  // 5. 测试通过配置服务更新（应该自动同步）
  console.log('\n--- 测试配置服务同步 ---')
  configService.updateConfig({ hotStocksLimit: 150 })

  // 等待事件处理
  await new Promise((r) => setTimeout(r, 100))

  console.assert(incrementalUpdater.getHotStocksLimit() === 150, '热点股票数量应自动同步为150只')
  console.log('✅ 配置服务同步验证通过')

  // 6. 测试 processHotStocks 方法（如果有股票数据）
  if (dataLayer.getStocks().length > 0) {
    console.log('\n--- 测试处理热点股票 ---')
    console.log('手动触发增量更新...')

    // 触发增量更新
    EventManager.emit('AppEvents.INCREMENTAL_REQUESTED', { timestamp: Date.now() })

    // 等待处理
    await new Promise((r) => setTimeout(r, 2000))

    console.log('查看控制台是否有 HTTP 请求日志')
  } else {
    console.log('⚠️ 无股票数据，跳过 processHotStocks 测试')
  }

  console.log('\n========== 测试完成 ==========')
}
