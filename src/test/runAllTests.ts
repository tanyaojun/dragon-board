// src/tests/runAllTests.ts
import { testConfigService, testConfigServiceAfterReload } from './ConfigService.test'
import { testRefreshManager } from './RefreshManager.test'
import { testIncrementalUpdater } from './IncrementalUpdater.test'

/**
 * 运行所有测试
 * 在浏览器控制台执行：
 * import { runAllTests } from '@/tests/runAllTests'
 * runAllTests()
 */
export async function runAllTests() {
  console.log('%c========== 开始全面测试 ==========', 'color: blue; font-size: 16px')
  
  // 1. 清除之前的存储
  localStorage.removeItem('kpl-refresh-config')
  console.log('✅ 已清除 localStorage')
  
  // 2. 测试 ConfigService
  console.log('\n%c--- 测试 ConfigService ---', 'color: green')
  await testConfigService()
  
  // 3. 测试 RefreshManager
  console.log('\n%c--- 测试 RefreshManager ---', 'color: green')
  await testRefreshManager()
  
  // 4. 测试 IncrementalUpdater
  console.log('\n%c--- 测试 IncrementalUpdater ---', 'color: green')
  await testIncrementalUpdater()
  
  // 5. 验证 localStorage 最终状态
  console.log('\n%c--- 最终验证 ---', 'color: green')
  const finalSaved = localStorage.getItem('kpl-refresh-config')
  console.log('最终 localStorage 内容:', finalSaved)
  
  console.log('%c\n========== 所有测试完成 ==========', 'color: blue; font-size: 16px')
  
  return {
    message: '测试完成，请查看控制台输出',
    finalConfig: finalSaved ? JSON.parse(finalSaved) : null
  }
}

// 挂载到 window 方便调试
if (typeof window !== 'undefined') {
  ;(window as any).test = {
    configService: testConfigService,
    configServiceAfterReload: testConfigServiceAfterReload,
    refreshManager: testRefreshManager,
    incrementalUpdater: testIncrementalUpdater,
    all: runAllTests
  }
}