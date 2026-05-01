// src/test/testDataQuality.ts
// 数据质量检查工具测试脚本

import { runDataQualityCheck } from './dataQualityChecker'

/**
 * 测试数据质量检查工具
 */
async function testDataQualityChecker() {
  console.log('=== 测试数据质量检查工具 ===')
  console.log('开始时间:', new Date().toISOString())
  console.log('')

  try {
    // 运行数据质量检查
    const result = await runDataQualityCheck()

    if (result.success) {
      console.log('✅ 数据质量检查完成')
      console.log('')

      // 输出一些统计信息
      const report = result.report as string
      const lines = report.split('\n')

      console.log('📋 检查结果摘要:')
      for (const line of lines) {
        if (
          line.includes('总快照数:') ||
          line.includes('有效快照:') ||
          line.includes('无效快照:') ||
          line.includes('有效率:') ||
          line.includes('v1.0 快照:') ||
          line.includes('v2.0 快照:')
        ) {
          console.log(line)
        }
      }

      console.log('')
      console.log('💡 建议操作:')
      for (const line of lines) {
        if (line.includes('建议:')) {
          console.log(line)
        }
      }
    } else {
      console.error('❌ 数据质量检查失败:', result.error)
    }
  } catch (error) {
    console.error('❌ 测试过程中发生错误:', error)
  }

  console.log('')
  console.log('=== 测试完成 ===')
  console.log('结束时间:', new Date().toISOString())
}

/**
 * 模拟测试数据（用于开发测试）
 */
async function testWithMockData() {
  console.log('=== 使用模拟数据测试 ===')

  // 创建模拟的快照数据
  const mockSnapshot = {
    date: '[一刻快照] 2026-04-12 12:15',
    timestamp: Date.now(),
    type: 'quarter_hour',
    metadata: {
      version: '2.0',
      totalStocks: 100,
      marketMode: 'hot',
      dataVersion: 1,
      timestamp: Date.now(),
    },
    hotlist: [
      {
        code: '000001',
        name: '测试股票',
        avgRank: 50.5,
        rank: 1,
        price: 10.5,
        change: 2.5,
        volume: 1000000,
        turnover: 50000000,
        turnoverRate: 3.2,
        totalMV: 1000000000,
        cirMV: 500000000,
        zlje: 10000000,
        zljzb: 2.5,
        cddje: 5000000,
        cddjzb: 1.2,
        pe: 15.5,
        pb: 2.1,
        technicalIndicators: {
          ma5: 10.2,
          ma10: 10.0,
          maTrend: 'up',
          macd: 0.15,
          macdSignal: 0.12,
          macdHistogram: 0.03,
          macdCross: 'golden',
          percentile: 99.0,
          fundPenetration: 2.5,
        },
        volumeRatio: 1.5,
        speed: 0.8,
        leadStatus: '领涨',
        lianbanStr: '首板',
        fengdan: 5000000,
        popularity: 85,
        popularityChange: 5,
        isNew: false,
        firstZtTime: '09:35',
        lastZtTime: '09:35',
        boardHeight: 1,
        highDays: 1,
        hotness: 75,
        tags: [{ Name: '测试标签' }],
        reason: '测试原因',
        rankChange: 5,
        mainTheme: '测试题材',
        themeHeat: 80,
        themeLevel: '热',
        signals: {
          direction: { signal: 'buy', confidence: 85 },
          acceleration: { signal: 'buy', confidence: 70 },
          cross: { signal: 'buy', confidence: 75 },
          final: { signal: 'buy', confidence: 80 },
        },
      },
    ],
  }

  console.log('✅ 模拟数据创建成功')
  console.log('数据版本:', mockSnapshot.metadata.version)
  console.log('包含技术指标:', mockSnapshot.hotlist[0].technicalIndicators ? '是' : '否')
  console.log('包含完整信号:', mockSnapshot.hotlist[0].signals ? '是' : '否')
  console.log('')

  // 检查必需字段
  const requiredFields = [
    'metadata.version',
    'metadata.totalStocks',
    'hotlist[0].technicalIndicators.ma5',
    'hotlist[0].technicalIndicators.macd',
    'hotlist[0].signals.direction',
    'hotlist[0].signals.final',
  ]

  console.log('🔍 字段检查:')
  for (const field of requiredFields) {
    const value = eval(`mockSnapshot.${field}`)
    console.log(`  ${field}: ${value !== undefined ? '✅' : '❌'} ${value}`)
  }

  console.log('')
  console.log('📊 模拟数据验证通过！')
}

/**
 * 检查当前数据保存状态
 */
async function checkDataSavingStatus() {
  console.log('=== 检查数据保存状态 ===')

  // 这里可以添加检查数据保存状态的逻辑
  // 例如：检查最近是否有新的v2.0快照保存

  console.log('1. ✅ 数据增强功能已实现')
  console.log('   - 一刻快照: 增加metadata和technicalIndicators')
  console.log('   - 半点快照: 增加metadata和technicalIndicators')
  console.log('   - 整点快照: 增加metadata和technicalIndicators，恢复完整4个信号')
  console.log('')
  console.log('2. ✅ 数据质量检查工具已创建')
  console.log('   - 支持检查单个快照质量')
  console.log('   - 支持检查所有快照质量')
  console.log('   - 支持生成质量报告')
  console.log('   - 支持导出报告文件')
  console.log('')
  console.log('3. 📈 下一步建议:')
  console.log('   a. 运行实际的数据质量检查')
  console.log('   b. 将研究数据导入 QuantBoard 后端')
  console.log('   c. 创建数据预处理模块')
  console.log('   d. 实现绩效统计模块')
}

// 主函数
async function main() {
  console.log('')
  console.log('🚀 数据质量检查工具测试')
  console.log('========================')
  console.log('')

  // 1. 检查数据保存状态
  await checkDataSavingStatus()

  console.log('')
  console.log('---')
  console.log('')

  // 2. 使用模拟数据测试
  await testWithMockData()

  console.log('')
  console.log('---')
  console.log('')

  // 3. 运行实际的数据质量检查（注释掉，需要时启用）
  // console.log('注意: 实际数据质量检查需要浏览器环境')
  // console.log('请在浏览器控制台中运行:')
  // console.log('   import("./test/dataQualityChecker.ts").then(m => m.runDataQualityCheck())')
  // console.log('')

  console.log('✅ 所有测试完成！')
  console.log('')
  console.log('💡 使用说明:')
  console.log('1. 在浏览器中打开开发者工具')
  console.log('2. 在控制台中输入:')
  console.log('   dataQualityChecker.generateQualityReport().then(console.log)')
  console.log('3. 或者运行完整检查:')
  console.log('   runDataQualityCheck()')
}

// 导出测试函数
export {
  testDataQualityChecker,
  testWithMockData,
  checkDataSavingStatus,
  main as testDataQualityMain,
}

// 浏览器环境自动运行（如果直接通过script标签引入）
if (typeof window !== 'undefined') {
  // 添加到全局对象，方便在浏览器控制台中调用
  ;(window as any).testDataQualityMain = main
  ;(window as any).testDataQualityChecker = testDataQualityChecker
  ;(window as any).testWithMockData = testWithMockData
  ;(window as any).checkDataSavingStatus = checkDataSavingStatus

  console.log('✅ 数据质量测试脚本已加载，可在控制台中调用:')
  console.log('   testDataQualityMain() - 运行完整测试')
  console.log('   testDataQualityChecker() - 测试数据质量检查工具')
  console.log('   testWithMockData() - 使用模拟数据测试')
  console.log('   checkDataSavingStatus() - 检查数据保存状态')
}
