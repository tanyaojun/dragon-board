// src/devtools/diagnostics/configServiceDiagnostic.ts
// 在浏览器控制台执行的手工诊断代码

/**
 * 诊断 ConfigService 的本地存储功能
 * 在浏览器控制台执行：
 * import { testConfigService } from '@/devtools/diagnostics/configServiceDiagnostic'
 * testConfigService()
 */
export async function testConfigService() {
  console.log('========== 开始测试 ConfigService ==========')
  
  // 1. 清除之前的存储
  localStorage.removeItem('kpl-refresh-config')
  console.log('✅ 已清除 localStorage')
  
  // 2. 初始化配置服务
  await configService.init()
  console.log('✅ 初始化完成，当前配置:', configService.getConfig())
  
  // 3. 验证默认配置是否为平衡型
  const defaultConfig = configService.getConfig()
  console.assert(defaultConfig.strategy === 'balanced', '默认策略应为 balanced')
  console.assert(defaultConfig.fullRefreshInterval === 15 * 60 * 1000, '默认全量间隔应为15分钟')
  console.assert(defaultConfig.hotStocksLimit === 100, '默认热点股票应为100只')
  console.log('✅ 默认配置验证通过')
  
  // 4. 测试更新配置
  console.log('\n--- 测试更新配置 ---')
  configService.updateConfig({ 
    fullRefreshInterval: 5 * 60 * 1000,
    hotStocksLimit: 200 
  })
  
  const updatedConfig = configService.getConfig()
  console.assert(updatedConfig.fullRefreshInterval === 5 * 60 * 1000, '全量间隔应更新为5分钟')
  console.assert(updatedConfig.hotStocksLimit === 200, '热点股票应更新为200只')
  console.assert(updatedConfig.strategy === 'balanced', '策略应保持不变')
  console.log('✅ 配置更新验证通过')
  
  // 5. 验证 localStorage 是否保存
  const saved = localStorage.getItem('kpl-refresh-config')
  console.log('localStorage 内容:', saved)
  console.assert(saved !== null, 'localStorage 应有数据')
  
  if (saved) {
    const parsed = JSON.parse(saved)
    console.assert(parsed.fullRefreshInterval === 5 * 60 * 1000, 'localStorage 全量间隔应为5分钟')
    console.assert(parsed.hotStocksLimit === 200, 'localStorage 热点股票应为200只')
    console.log('✅ localStorage 保存验证通过')
  }
  
  // 6. 测试切换策略
  console.log('\n--- 测试切换策略 ---')
  configService.setStrategy('aggressive', true)
  
  const aggressiveConfig = configService.getConfig()
  console.assert(aggressiveConfig.strategy === 'aggressive', '策略应切换为 aggressive')
  console.assert(aggressiveConfig.fullRefreshInterval === 5 * 60 * 1000, '激进型全量间隔应为5分钟')
  console.assert(aggressiveConfig.hotStocksLimit === 200, '激进型热点股票应为200只')
  console.log('✅ 策略切换验证通过')
  
  // 7. 测试只切换策略名称，不应用预设
  console.log('\n--- 测试只切换策略名称 ---')
  // 先修改一些值
  configService.updateConfig({ hotStocksLimit: 150 })
  
  configService.setStrategy('conservative', false)
  
  const conservativeConfig = configService.getConfig()
  console.assert(conservativeConfig.strategy === 'conservative', '策略名称应切换为 conservative')
  console.assert(conservativeConfig.hotStocksLimit === 150, '热点股票应保持150只（未应用预设）')
  console.log('✅ 只切换策略名称验证通过')
  
  // 8. 测试重置功能
  console.log('\n--- 测试重置功能 ---')
  configService.resetToStrategy('balanced')
  
  const resetConfig = configService.getConfig()
  console.assert(resetConfig.strategy === 'balanced', '重置后策略应为 balanced')
  console.assert(resetConfig.fullRefreshInterval === 15 * 60 * 1000, '重置后全量间隔应为15分钟')
  console.assert(resetConfig.hotStocksLimit === 100, '重置后热点股票应为100只')
  console.log('✅ 重置功能验证通过')
  
  // 9. 测试页面刷新后的数据恢复
  console.log('\n--- 测试页面刷新后的数据恢复 ---')
  console.log('请手动刷新页面，然后执行: testConfigServiceAfterReload()')
  
  console.log('\n========== 测试完成 ==========')
  return '测试完成，请查看控制台输出'
}

/**
 * 刷新页面后执行此函数，测试数据是否恢复
 */
export function testConfigServiceAfterReload() {
  console.log('========== 测试刷新后数据恢复 ==========')
  
  const config = configService.getConfig()
  console.log('刷新后配置:', config)
  
  const saved = localStorage.getItem('kpl-refresh-config')
  console.log('localStorage 内容:', saved)
  
  // 验证是否与刷新前一致
  console.assert(config.strategy === 'balanced', '策略应为 balanced')
  console.assert(config.fullRefreshInterval === 15 * 60 * 1000, '全量间隔应为15分钟')
  console.assert(config.hotStocksLimit === 100, '热点股票应为100只')
  
  console.log('✅ 数据恢复验证通过')
  console.log('========== 测试完成 ==========')
}
