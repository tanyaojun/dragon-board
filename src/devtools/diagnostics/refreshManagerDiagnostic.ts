// src/devtools/diagnostics/refreshManagerDiagnostic.ts
export async function testRefreshManager() {
  console.log('========== 开始测试 RefreshManager ==========')

  // 1. 重置配置
  localStorage.removeItem('kpl-refresh-config')
  console.log('✅ 已清除 localStorage')

  // 2. 初始化 RefreshManager
  await RefreshManager.init()
  console.log('✅ RefreshManager 初始化完成')

  // 3. 获取状态，验证是否从 configService 读取
  const status = RefreshManager.getStatus()
  console.log('RefreshManager 状态:', status)

  console.assert(status.strategy === 'balanced', '策略应为 balanced')
  console.assert(status.fullRefreshInterval === 15 * 60 * 1000, '全量间隔应为15分钟')
  console.log('✅ 初始状态验证通过')

  // 4. 测试更新配置
  console.log('\n--- 测试更新配置 ---')
  RefreshManager.updateConfig({
    fullRefreshInterval: 30 * 60 * 1000,
  })

  const updatedStatus = RefreshManager.getStatus()
  console.assert(updatedStatus.fullRefreshInterval === 30 * 60 * 1000, '全量间隔应更新为30分钟')
  console.log('✅ 配置更新验证通过')

  // 5. 验证 localStorage 是否保存
  const saved = localStorage.getItem('kpl-refresh-config')
  console.log('localStorage 内容:', saved)

  if (saved) {
    const parsed = JSON.parse(saved)
    console.assert(parsed.fullRefreshInterval === 30 * 60 * 1000, 'localStorage 全量间隔应为30分钟')
    console.log('✅ localStorage 保存验证通过')
  }

  // 6. 测试切换策略
  console.log('\n--- 测试切换策略 ---')
  RefreshManager.setStrategy('aggressive', true)

  const aggressiveStatus = RefreshManager.getStatus()
  console.assert(aggressiveStatus.strategy === 'aggressive', '策略应切换为 aggressive')
  console.assert(aggressiveStatus.fullRefreshInterval === 5 * 60 * 1000, '全量间隔应为5分钟')
  console.log('✅ 策略切换验证通过')

  // 7. 验证定时器是否重启（查看控制台日志）
  console.log('查看控制台是否有 "▶️ 已启动" 日志，验证定时器已重启')

  // 8. 测试手动刷新
  console.log('\n--- 测试手动刷新 ---')
  const result = await RefreshManager.manualRefresh('full')
  console.assert(result === true, '手动刷新应成功')
  console.log('查看控制台是否有 "AppEvents.REFRESH.FULL_REQUESTED" 事件日志')

  console.log('\n========== 测试完成 ==========')
}
