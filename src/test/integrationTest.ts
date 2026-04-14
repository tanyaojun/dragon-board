// src/test/integrationTest.ts
// 集成测试脚本 - 验证数据增强和回测系统的核心功能

import { dataQualityChecker } from './dataQualityChecker'
import { BacktestEngine } from '../services/backtest/BacktestEngine'

/**
 * 集成测试 - 验证整个系统的核心功能
 */
export async function runIntegrationTest() {
  console.log('=== 数据增强和回测系统集成测试 ===')
  console.log('开始时间:', new Date().toISOString())
  console.log('')

  const testResults = {
    dataQualityCheck: { passed: false, message: '' },
    backtestEngine: { passed: false, message: '' },
    dataEnhancement: { passed: false, message: '' },
    overall: { passed: false, message: '' },
  }

  try {
    // 测试1: 数据质量检查
    console.log('🧪 测试1: 数据质量检查工具')
    try {
      const report = await dataQualityChecker.generateQualityReport()
      const lines = report.split('\n')

      // 检查报告是否包含关键信息
      const hasKeyInfo = lines.some(
        (line) =>
          line.includes('总快照数:') || line.includes('有效快照:') || line.includes('v2.0 快照:'),
      )

      if (hasKeyInfo) {
        testResults.dataQualityCheck.passed = true
        testResults.dataQualityCheck.message = '数据质量检查工具工作正常'
        console.log('  ✅ 数据质量检查工具: 工作正常')

        // 输出关键统计
        for (const line of lines.slice(0, 10)) {
          if (line.includes('总快照数:') || line.includes('v2.0 快照:')) {
            console.log('  ', line)
          }
        }
      } else {
        testResults.dataQualityCheck.message = '数据质量检查报告缺少关键信息'
        console.log('  ⚠️ 数据质量检查工具: 报告缺少关键信息')
      }
    } catch (error) {
      testResults.dataQualityCheck.message = `数据质量检查失败: ${error instanceof Error ? error.message : String(error)}`
      console.log('  ❌ 数据质量检查工具: 测试失败', error)
    }
    console.log('')

    // 测试2: 回测引擎初始化
    console.log('🧪 测试2: 回测引擎初始化')
    try {
      const engine = new BacktestEngine({
        startDate: '2026-04-01',
        endDate: '2026-04-11',
        initialCapital: 100000,
        positionSize: 0.1,
        maxPositions: 3,
        confidenceThreshold: 70,
      })

      // 检查引擎配置
      if (engine && typeof engine.runBacktest === 'function') {
        testResults.backtestEngine.passed = true
        testResults.backtestEngine.message = '回测引擎初始化成功'
        console.log('  ✅ 回测引擎: 初始化成功')
        console.log('    初始资金:', engine['config'].initialCapital)
        console.log('    仓位比例:', engine['config'].positionSize)
        console.log('    最大持仓:', engine['config'].maxPositions)
      } else {
        testResults.backtestEngine.message = '回测引擎初始化失败'
        console.log('  ❌ 回测引擎: 初始化失败')
      }
    } catch (error) {
      testResults.backtestEngine.message = `回测引擎初始化失败: ${error instanceof Error ? error.message : String(error)}`
      console.log('  ❌ 回测引擎: 初始化异常', error)
    }
    console.log('')

    // 测试3: 数据增强功能验证
    console.log('🧪 测试3: 数据增强功能验证')
    try {
      // 检查DataLayer是否包含增强功能
      const snapshotDates = await (window as any).dataLayer?.getSnapshotDates?.()

      if (snapshotDates && Array.isArray(snapshotDates)) {
        testResults.dataEnhancement.passed = true
        testResults.dataEnhancement.message = `找到 ${snapshotDates.length} 个快照`
        console.log(`  ✅ 数据增强: 找到 ${snapshotDates.length} 个快照`)

        // 检查是否有快照
        if (snapshotDates.length > 0) {
          console.log('  📊 快照示例:', snapshotDates[0])
        }
      } else {
        testResults.dataEnhancement.message = '无法获取快照数据'
        console.log('  ⚠️ 数据增强: 无法获取快照数据')
      }
    } catch (error) {
      testResults.dataEnhancement.message = `数据增强验证失败: ${error instanceof Error ? error.message : String(error)}`
      console.log('  ❌ 数据增强: 验证失败', error)
    }
    console.log('')

    // 总体评估
    console.log('📊 测试结果汇总:')
    console.log('')

    const passedTests = [
      testResults.dataQualityCheck.passed,
      testResults.backtestEngine.passed,
      testResults.dataEnhancement.passed,
    ].filter(Boolean).length

    const totalTests = 3

    console.log(`  通过测试: ${passedTests}/${totalTests}`)
    console.log('')

    console.log('  1. 数据质量检查:', testResults.dataQualityCheck.passed ? '✅' : '❌')
    console.log('     状态:', testResults.dataQualityCheck.message)
    console.log('')

    console.log('  2. 回测引擎:', testResults.backtestEngine.passed ? '✅' : '❌')
    console.log('     状态:', testResults.backtestEngine.message)
    console.log('')

    console.log('  3. 数据增强:', testResults.dataEnhancement.passed ? '✅' : '❌')
    console.log('     状态:', testResults.dataEnhancement.message)
    console.log('')

    // 总体结论
    if (passedTests === totalTests) {
      testResults.overall.passed = true
      testResults.overall.message = '所有测试通过！系统准备就绪。'
      console.log('🎉 总体结论: ✅ 所有测试通过！')
      console.log('   系统已准备就绪，可以开始使用。')
    } else if (passedTests >= 2) {
      testResults.overall.passed = true
      testResults.overall.message = '大部分测试通过，系统基本可用。'
      console.log('📈 总体结论: ⚠️ 大部分测试通过')
      console.log('   系统基本可用，建议检查失败的项目。')
    } else {
      testResults.overall.message = '测试失败较多，需要修复问题。'
      console.log('🚨 总体结论: ❌ 测试失败较多')
      console.log('   需要修复问题后才能正常使用。')
    }

    console.log('')

    // 使用建议
    console.log('💡 使用建议:')
    if (!testResults.dataQualityCheck.passed) {
      console.log('  1. 检查数据质量检查工具配置')
    }
    if (!testResults.backtestEngine.passed) {
      console.log('  2. 检查回测引擎依赖和数据访问')
    }
    if (!testResults.dataEnhancement.passed) {
      console.log('  3. 确保DataLayer已正确加载')
    }

    if (passedTests > 0) {
      console.log('')
      console.log('🚀 下一步操作:')
      console.log('  1. 让系统运行一段时间积累v2.0格式数据')
      console.log('  2. 运行数据质量检查: dataQualityChecker.generateQualityReport()')
      console.log('  3. 运行回测测试: new BacktestEngine().runBacktest()')
    }
  } catch (error) {
    console.error('❌ 集成测试过程中发生错误:', error)
    testResults.overall.message = `集成测试失败: ${error instanceof Error ? error.message : String(error)}`
  }

  console.log('')
  console.log('=== 集成测试完成 ===')
  console.log('结束时间:', new Date().toISOString())

  return testResults
}

/**
 * 快速健康检查
 */
export async function quickHealthCheck() {
  console.log('🔍 快速健康检查...')

  const checks = [
    { name: 'DataLayer', passed: false },
    { name: 'DataQualityChecker', passed: false },
    { name: 'BacktestEngine', passed: false },
  ]

  try {
    // 检查DataLayer
    if (typeof (window as any).dataLayer !== 'undefined') {
      checks[0].passed = true
    }

    // 检查DataQualityChecker
    if (typeof dataQualityChecker !== 'undefined') {
      checks[1].passed = true
    }

    // 检查BacktestEngine
    try {
      new BacktestEngine()
      checks[2].passed = true
    } catch {
      // 忽略构造函数错误
    }

    console.log('📋 健康检查结果:')
    for (const check of checks) {
      console.log(`  ${check.name}: ${check.passed ? '✅' : '❌'}`)
    }

    const allPassed = checks.every((check) => check.passed)
    console.log(allPassed ? '✅ 所有组件加载正常' : '⚠️ 部分组件可能有问题')

    return { allPassed, checks }
  } catch (error) {
    console.error('健康检查失败:', error)
    return { allPassed: false, checks, error: String(error) }
  }
}

// 浏览器环境自动运行
if (typeof window !== 'undefined') {
  // 添加到全局对象
  ;(window as any).runIntegrationTest = runIntegrationTest
  ;(window as any).quickHealthCheck = quickHealthCheck

  console.log('✅ 集成测试脚本已加载')
  console.log('   可用函数:')
  console.log('     runIntegrationTest() - 运行完整集成测试')
  console.log('     quickHealthCheck() - 快速健康检查')

  // 自动运行快速健康检查
  setTimeout(() => {
    quickHealthCheck()
      .then((result) => {
        if (result.allPassed) {
          console.log('🎉 系统健康状态良好，可以开始使用！')
        } else {
          console.log('⚠️ 系统有组件未正常加载，请检查控制台错误。')
        }
      })
      .catch(() => {
        // 忽略错误
      })
  }, 1000)
}
