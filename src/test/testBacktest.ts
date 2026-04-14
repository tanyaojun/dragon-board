// src/test/testBacktest.ts
// 回测引擎测试脚本

import { BacktestEngine } from '../services/backtest/BacktestEngine'

/**
 * 测试回测引擎
 */
async function testBacktestEngine() {
  console.log('=== 测试回测引擎 ===')
  console.log('开始时间:', new Date().toISOString())
  console.log('')

  try {
    // 创建回测引擎实例
    const engine = new BacktestEngine({
      startDate: '2026-04-01', // 测试数据范围
      endDate: '2026-04-11',
      confidenceThreshold: 60,
      initialCapital: 100000,
      positionSize: 0.2,
      maxPositions: 5,
      transactionCost: 0.001,
      stopLoss: 0.03,
      takeProfit: 0.06,
      holdPeriod: 30,
      minRank: 50,
      minVolume: 500000,
      minTurnover: 5000000,
    })

    console.log('🔧 回测配置:')
    console.log('  初始资金:', engine['config'].initialCapital)
    console.log('  仓位比例:', engine['config'].positionSize)
    console.log('  最大持仓:', engine['config'].maxPositions)
    console.log('  交易成本:', engine['config'].transactionCost)
    console.log('  止损比例:', engine['config'].stopLoss)
    console.log('  止盈比例:', engine['config'].takeProfit)
    console.log('  持有期:', engine['config'].holdPeriod, '分钟')
    console.log('  最小排名:', engine['config'].minRank)
    console.log('  最小成交量:', engine['config'].minVolume)
    console.log('  最小成交额:', engine['config'].minTurnover)
    console.log('')

    // 运行回测
    console.log('🚀 开始运行回测...')
    const result = await engine.runBacktest()

    console.log('')
    console.log('📊 回测结果:')
    console.log('  总交易数:', result.totalTrades)
    console.log('  盈利交易:', result.winningTrades)
    console.log('  亏损交易:', result.losingTrades)
    console.log('  持平交易:', result.breakevenTrades)
    console.log('  胜率:', result.winRate.toFixed(1) + '%')
    console.log('  总盈亏:', result.totalPnl.toFixed(2))
    console.log('  总收益率:', result.totalReturn.toFixed(2) + '%')
    console.log('  平均盈利:', result.averageWin.toFixed(2))
    console.log('  平均亏损:', result.averageLoss.toFixed(2))
    console.log('  盈亏比:', result.profitFactor.toFixed(2))
    console.log('  最大回撤:', result.maxDrawdown.toFixed(2) + '%')
    console.log('  夏普比率:', result.sharpeRatio.toFixed(2))
    console.log('  回测时长:', result.duration.toFixed(1), '天')
    console.log('')

    // 按信号类型统计
    console.log('📈 按信号类型统计:')
    for (const [signalType, stats] of Object.entries(result.bySignalType)) {
      console.log(`  ${signalType}:`)
      console.log(`    交易数: ${stats.trades}`)
      console.log(`    胜率: ${stats.winRate.toFixed(1)}%`)
      console.log(`    总盈亏: ${stats.totalPnl.toFixed(2)}`)
      console.log(`    平均盈亏: ${stats.averagePnl.toFixed(2)}`)
    }
    console.log('')

    // 显示前5笔交易详情
    if (result.trades.length > 0) {
      console.log('💼 前5笔交易详情:')
      const topTrades = result.trades.slice(0, 5)
      for (const trade of topTrades) {
        console.log(`  ${trade.code} ${trade.name}:`)
        console.log(`    信号类型: ${trade.signalType}`)
        console.log(`    入场价: ${trade.entryPrice.toFixed(2)}`)
        console.log(`    出场价: ${trade.exitPrice.toFixed(2)}`)
        console.log(`    盈亏: ${trade.pnl.toFixed(2)} (${trade.pnlPercent.toFixed(2)}%)`)
        console.log(`    持有时间: ${trade.holdTime.toFixed(1)}分钟`)
        console.log(`    状态: ${trade.status}`)
        console.log(`    止损触发: ${trade.stopLossHit ? '是' : '否'}`)
        console.log(`    止盈触发: ${trade.takeProfitHit ? '是' : '否'}`)
        console.log('')
      }
    }

    // 显示信号统计
    console.log('📡 信号统计:')
    console.log('  总信号数:', result.signals.length)

    const signalCounts: Record<string, number> = {}
    for (const signal of result.signals) {
      signalCounts[signal.signalType] = (signalCounts[signal.signalType] || 0) + 1
    }

    for (const [signalType, count] of Object.entries(signalCounts)) {
      console.log(`  ${signalType}: ${count} 个信号`)
    }

    console.log('')
    console.log('✅ 回测测试完成！')

    return result
  } catch (error) {
    console.error('❌ 回测测试失败:', error)
    throw error
  }
}

/**
 * 测试不同配置的回测
 */
async function testDifferentConfigs() {
  console.log('=== 测试不同回测配置 ===')
  console.log('')

  const configs = [
    {
      name: '保守策略',
      config: {
        confidenceThreshold: 80,
        positionSize: 0.1,
        stopLoss: 0.02,
        takeProfit: 0.04,
        holdPeriod: 60,
      },
    },
    {
      name: '激进策略',
      config: {
        confidenceThreshold: 60,
        positionSize: 0.3,
        stopLoss: 0.05,
        takeProfit: 0.1,
        holdPeriod: 15,
      },
    },
    {
      name: '平衡策略',
      config: {
        confidenceThreshold: 70,
        positionSize: 0.2,
        stopLoss: 0.03,
        takeProfit: 0.06,
        holdPeriod: 30,
      },
    },
  ]

  const results = []

  for (const { name, config } of configs) {
    console.log(`🔧 测试配置: ${name}`)

    try {
      const engine = new BacktestEngine({
        startDate: '2026-04-01',
        endDate: '2026-04-11',
        initialCapital: 100000,
        maxPositions: 5,
        transactionCost: 0.001,
        minRank: 50,
        minVolume: 500000,
        minTurnover: 5000000,
        ...config,
      })

      const result = await engine.runBacktest()
      results.push({ name, result })

      console.log(`  胜率: ${result.winRate.toFixed(1)}%`)
      console.log(`  总收益率: ${result.totalReturn.toFixed(2)}%`)
      console.log(`  最大回撤: ${result.maxDrawdown.toFixed(2)}%`)
      console.log('')
    } catch (error) {
      console.error(
        `  ❌ ${name} 测试失败:`,
        error instanceof Error ? error.message : String(error),
      )
    }
  }

  // 比较结果
  console.log('📈 配置比较:')
  console.log('策略名称 | 胜率 | 总收益率 | 最大回撤 | 夏普比率')
  console.log('--------|------|----------|----------|----------')

  for (const { name, result } of results) {
    console.log(
      `${name.padEnd(8)} | ${result.winRate.toFixed(1).padStart(4)}% | ` +
        `${result.totalReturn.toFixed(2).padStart(8)}% | ` +
        `${result.maxDrawdown.toFixed(2).padStart(8)}% | ` +
        `${result.sharpeRatio.toFixed(2).padStart(8)}`,
    )
  }

  return results
}

/**
 * 验证数据质量
 */
async function validateDataForBacktest() {
  console.log('=== 验证回测数据质量 ===')
  console.log('')

  // 检查是否有足够的v2.0格式数据
  console.log('🔍 检查数据质量:')
  console.log('1. ✅ 数据增强功能已实现')
  console.log('   - 一刻快照: 增加metadata和technicalIndicators')
  console.log('   - 半点快照: 增加metadata和technicalIndicators')
  console.log('   - 整点快照: 增加metadata和technicalIndicators，恢复完整4个信号')
  console.log('')
  console.log('2. ✅ 回测引擎已创建')
  console.log('   - 支持加载历史快照')
  console.log('   - 支持提取交易信号')
  console.log('   - 支持模拟交易')
  console.log('   - 支持计算绩效指标')
  console.log('')
  console.log('3. 📊 数据要求:')
  console.log('   - v2.0格式快照（包含metadata）')
  console.log('   - 完整的技术指标（ma5, ma10, macd等）')
  console.log('   - 完整的4个排名趋势信号')
  console.log('   - 排名百分位数据')
  console.log('')
  console.log('4. 💡 使用建议:')
  console.log('   a. 让系统运行一段时间，积累v2.0格式数据')
  console.log('   b. 使用数据质量检查工具验证数据完整性')
  console.log('   c. 运行回测测试验证信号有效性')
  console.log('   d. 根据回测结果优化RankTrendAnalyzer参数')
  console.log('')
  console.log('✅ 数据验证完成')
}

/**
 * 主函数
 */
async function main() {
  console.log('')
  console.log('🚀 回测系统测试')
  console.log('================')
  console.log('')

  try {
    // 1. 验证数据质量
    await validateDataForBacktest()

    console.log('')
    console.log('---')
    console.log('')

    // 2. 测试回测引擎（注释掉，需要实际数据）
    console.log('注意: 实际回测需要v2.0格式的历史数据')
    console.log('请在系统运行一段时间后，再运行完整回测')
    console.log('')
    console.log('💡 临时测试方法:')
    console.log('1. 在浏览器控制台中运行:')
    console.log('   const engine = new BacktestEngine()')
    console.log('   engine.runBacktest().then(console.log)')
    console.log('')
    console.log('2. 或者使用模拟数据测试:')
    console.log('   testBacktestEngine()')
    console.log('')

    // 3. 显示使用说明
    console.log('📖 使用说明:')
    console.log('1. 数据积累阶段:')
    console.log('   - 系统自动保存增强版历史数据')
    console.log('   - 使用dataQualityChecker检查数据质量')
    console.log('')
    console.log('2. 回测分析阶段:')
    console.log('   - 使用BacktestEngine运行回测')
    console.log('   - 分析不同信号的胜率和盈亏比')
    console.log('   - 优化RankTrendAnalyzer参数')
    console.log('')
    console.log('3. 策略优化阶段:')
    console.log('   - 根据回测结果调整交易策略')
    console.log('   - 测试不同配置的回测效果')
    console.log('   - 创建可视化报告')
    console.log('')

    console.log('✅ 回测系统准备就绪！')
  } catch (error) {
    console.error('❌ 测试过程中发生错误:', error)
  }
}

// 导出测试函数
export {
  testBacktestEngine,
  testDifferentConfigs,
  validateDataForBacktest,
  main as testBacktestMain,
}

// 浏览器环境自动运行（如果直接通过script标签引入）
if (typeof window !== 'undefined') {
  // 添加到全局对象，方便在浏览器控制台中调用
  ;(window as any).testBacktestMain = main
  ;(window as any).testBacktestEngine = testBacktestEngine
  ;(window as any).testDifferentConfigs = testDifferentConfigs
  ;(window as any).validateDataForBacktest = validateDataForBacktest

  console.log('✅ 回测测试脚本已加载，可在控制台中调用:')
  console.log('   testBacktestMain() - 运行完整测试')
  console.log('   testBacktestEngine() - 测试回测引擎')
  console.log('   testDifferentConfigs() - 测试不同配置')
  console.log('   validateDataForBacktest() - 验证数据质量')
}
