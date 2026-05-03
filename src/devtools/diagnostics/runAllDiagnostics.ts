// src/devtools/diagnostics/runAllDiagnostics.ts
import { testConfigService, testConfigServiceAfterReload } from './configServiceDiagnostic'
import { testRefreshManager } from './refreshManagerDiagnostic'
import { testIncrementalUpdater } from './incrementalUpdaterDiagnostic'

/**
 * 运行手工诊断
 * 在浏览器控制台执行：
 * import { runAllDiagnostics } from '@/devtools/diagnostics/runAllDiagnostics'
 * runAllDiagnostics()
 */
export async function runAllDiagnostics() {
  console.log('%c========== 开始全面诊断 ==========', 'color: blue; font-size: 16px')
  
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
  
  console.log('%c\n========== 所有诊断完成 ==========', 'color: blue; font-size: 16px')
  
  return {
    message: '诊断完成，请查看控制台输出',
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
    all: runAllDiagnostics
  }
}
