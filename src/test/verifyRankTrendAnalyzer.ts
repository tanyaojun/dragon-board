// src/test/verifyRankTrendAnalyzer.ts
// 最小化测试脚本 - 验证RankTrendAnalyzer功能是否受DataLayer修改影响

import { rankTrendAnalyzer } from '../services/RankTrendAnalyzer'
import { DEFAULT_RANK_TREND_SNAPSHOT_TYPE } from '../type/rankTrendDefaults'

/**
 * 测试1：验证getSnapshotsByType方法
 */
async function testGetSnapshotsByType(): Promise<boolean> {
  console.log('🧪 测试1: 验证getSnapshotsByType方法')

  try {
    const analyzer = rankTrendAnalyzer
    const snapshots = await analyzer.getSnapshotsByType(DEFAULT_RANK_TREND_SNAPSHOT_TYPE, { limit: 3 })

    // 确定性验证
    console.log('  验证1: snapshots应该是数组')
    if (!Array.isArray(snapshots)) {
      console.error('  ❌ 失败: snapshots不是数组')
      return false
    }
    console.log('  ✅ 通过: snapshots是数组')

    console.log('  验证2: snapshots数量不超过limit')
    if (snapshots.length > 3) {
      console.error('  ❌ 失败: snapshots数量超过limit')
      return false
    }
    console.log('  ✅ 通过: snapshots数量正确')

    // 检查每个快照的结构
    for (let i = 0; i < Math.min(snapshots.length, 2); i++) {
      const snapshot = snapshots[i]

      console.log(`  验证3.${i + 1}: 快照${i + 1}必须有date字段`)
      if (!snapshot.date) {
        console.error(`  ❌ 失败: 快照${i + 1}缺少date字段`)
        return false
      }
      console.log(`  ✅ 通过: 快照${i + 1}有date字段`)

      console.log(`  验证4.${i + 1}: 快照${i + 1}必须有timestamp字段`)
      if (!snapshot.timestamp) {
        console.error(`  ❌ 失败: 快照${i + 1}缺少timestamp字段`)
        return false
      }
      console.log(`  ✅ 通过: 快照${i + 1}有timestamp字段`)

      console.log(`  验证5.${i + 1}: 快照${i + 1}必须有snapshot字段`)
      if (!snapshot.snapshot) {
        console.error(`  ❌ 失败: 快照${i + 1}缺少snapshot字段`)
        return false
      }
      console.log(`  ✅ 通过: 快照${i + 1}有snapshot字段`)

      console.log(`  验证6.${i + 1}: 快照类型必须正确`)
      if (snapshot.snapshot.type !== DEFAULT_RANK_TREND_SNAPSHOT_TYPE) {
        console.error(`  ❌ 失败: 快照类型不正确`)
        return false
      }
      console.log(`  ✅ 通过: 快照类型正确`)

      console.log(`  验证7.${i + 1}: hotlist必须是数组`)
      if (!Array.isArray(snapshot.snapshot.hotlist)) {
        console.error(`  ❌ 失败: hotlist不是数组`)
        return false
      }
      console.log(`  ✅ 通过: hotlist是数组`)
    }

    console.log('  📊 结果: 找到', snapshots.length, '个快照')
    return true
  } catch (error) {
    console.error('  ❌ 测试失败:', error instanceof Error ? error.message : String(error))
    return false
  }
}

/**
 * 测试2：验证buildPercentilesHistory方法（使用模拟数据）
 */
function testBuildPercentilesHistory(): boolean {
  console.log('\n🧪 测试2: 验证buildPercentilesHistory方法')

  try {
    // 创建模拟的快照数据
    const mockSnapshots = [
      {
        date: '2026-04-12 10:15',
        timestamp: Date.now() - 3600000,
        snapshot: {
          type: DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
          hotlist: [
            { code: '000001', rank: 1, name: '股票A' },
            { code: '000002', rank: 2, name: '股票B' },
            { code: '000003', rank: 3, name: '股票C' },
          ],
        },
      },
      {
        date: '2026-04-12 10:30',
        timestamp: Date.now() - 1800000,
        snapshot: {
          type: DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
          hotlist: [
            { code: '000002', rank: 1, name: '股票B' },
            { code: '000001', rank: 2, name: '股票A' },
            { code: '000003', rank: 3, name: '股票C' },
          ],
        },
      },
    ]

    // 调用私有方法（通过any类型绕过TypeScript检查）
    const analyzer = rankTrendAnalyzer as any
    const percentiles = analyzer.buildPercentilesHistory(mockSnapshots)

    console.log('  验证1: percentiles应该是Map')
    if (!(percentiles instanceof Map)) {
      console.error('  ❌ 失败: percentiles不是Map')
      return false
    }
    console.log('  ✅ 通过: percentiles是Map')

    console.log('  验证2: 应该有3个股票的百分位数据')
    if (percentiles.size !== 3) {
      console.error('  ❌ 失败: 股票数量不正确')
      return false
    }
    console.log('  ✅ 通过: 有3个股票的百分位数据')

    // 检查每个股票的百分位数据
    for (const [code, values] of percentiles) {
      console.log(`  验证3.${code}: 股票代码必须是6位`)
      if (code.length !== 6) {
        console.error(`  ❌ 失败: 股票代码${code}不是6位`)
        return false
      }
      console.log(`  ✅ 通过: 股票代码${code}是6位`)

      console.log(`  验证4.${code}: values必须是数组`)
      if (!Array.isArray(values)) {
        console.error(`  ❌ 失败: values不是数组`)
        return false
      }
      console.log(`  ✅ 通过: values是数组`)

      console.log(`  验证5.${code}: 百分位必须在0-100之间`)
      if (!values.every((v) => v >= 0 && v <= 100)) {
        console.error(`  ❌ 失败: 百分位不在0-100之间`)
        return false
      }
      console.log(`  ✅ 通过: 百分位在0-100之间`)

      console.log(`  验证6.${code}: 应该有2个百分位值`)
      if (values.length !== 2) {
        console.error(`  ❌ 失败: 百分位值数量不正确`)
        return false
      }
      console.log(`  ✅ 通过: 有2个百分位值`)
    }

    // 验证具体计算
    console.log('  验证7: 验证百分位计算')
    const stockAPercentiles = percentiles.get('000001')
    if (!stockAPercentiles) {
      console.error('  ❌ 失败: 找不到股票A的百分位数据')
      return false
    }

    // 股票A在第一个快照中排名第1（共3只），百分位 = ((3-1+1)/3)*100 = 100
    // 股票A在第二个快照中排名第2（共3只），百分位 = ((3-2+1)/3)*100 = 66.67
    const expected1 = 100
    const expected2 = 66.67

    if (Math.abs(stockAPercentiles[0] - expected1) > 0.01) {
      console.error(
        `  ❌ 失败: 第一个百分位计算错误，期望${expected1}，实际${stockAPercentiles[0]}`,
      )
      return false
    }

    if (Math.abs(stockAPercentiles[1] - expected2) > 0.01) {
      console.error(
        `  ❌ 失败: 第二个百分位计算错误，期望${expected2}，实际${stockAPercentiles[1]}`,
      )
      return false
    }

    console.log('  ✅ 通过: 百分位计算正确')
    return true
  } catch (error) {
    console.error('  ❌ 测试失败:', error instanceof Error ? error.message : String(error))
    return false
  }
}

/**
 * 测试3：验证calculateRankTrendSignal方法（使用模拟数据）
 */
function testCalculateRankTrendSignal(): boolean {
  console.log('\n🧪 测试3: 验证calculateRankTrendSignal方法')

  try {
    const analyzer = rankTrendAnalyzer as any

    // 创建模拟数据
    const percentiles = [50, 55, 60, 65, 70, 75, 80, 85, 90, 95] // 上升趋势
    const stockChange = 2.5

    const momentumData = {
      values: [5, 8, 12, 15, 18], // 所有正数，表示上升
      prevValues: [3, 5, 8, 10, 12], // 前一期也是上升
      score: 85,
      signal: 'buy' as const,
      confidence: 80,
    }

    const result = analyzer.calculateRankTrendSignal(percentiles, stockChange, momentumData)

    console.log('  验证1: 结果必须有directionSignal字段')
    if (!result.directionSignal) {
      console.error('  ❌ 失败: 缺少directionSignal字段')
      return false
    }
    console.log('  ✅ 通过: 有directionSignal字段')

    console.log('  验证2: 结果必须有accelerationSignal字段')
    if (!result.accelerationSignal) {
      console.error('  ❌ 失败: 缺少accelerationSignal字段')
      return false
    }
    console.log('  ✅ 通过: 有accelerationSignal字段')

    console.log('  验证3: 结果必须有crossSignal字段')
    if (!result.crossSignal) {
      console.error('  ❌ 失败: 缺少crossSignal字段')
      return false
    }
    console.log('  ✅ 通过: 有crossSignal字段')

    console.log('  验证4: 信号值必须是buy/sell/hold之一')
    const validSignals = ['buy', 'sell', 'hold']
    if (!validSignals.includes(result.directionSignal)) {
      console.error('  ❌ 失败: directionSignal值无效')
      return false
    }
    if (!validSignals.includes(result.accelerationSignal)) {
      console.error('  ❌ 失败: accelerationSignal值无效')
      return false
    }
    if (!validSignals.includes(result.crossSignal)) {
      console.error('  ❌ 失败: crossSignal值无效')
      return false
    }
    console.log('  ✅ 通过: 所有信号值有效')

    console.log('  验证5: 置信度必须在0-100之间')
    if (result.directionConfidence < 0 || result.directionConfidence > 100) {
      console.error('  ❌ 失败: directionConfidence不在0-100之间')
      return false
    }
    if (result.accelerationConfidence < 0 || result.accelerationConfidence > 100) {
      console.error('  ❌ 失败: accelerationConfidence不在0-100之间')
      return false
    }
    if (result.crossConfidence < 0 || result.crossConfidence > 100) {
      console.error('  ❌ 失败: crossConfidence不在0-100之间')
      return false
    }
    console.log('  ✅ 通过: 所有置信度在0-100之间')

    console.log('  📊 测试结果:')
    console.log('    directionSignal:', result.directionSignal)
    console.log('    directionConfidence:', result.directionConfidence)
    console.log('    accelerationSignal:', result.accelerationSignal)
    console.log('    accelerationConfidence:', result.accelerationConfidence)
    console.log('    crossSignal:', result.crossSignal)
    console.log('    crossConfidence:', result.crossConfidence)
    console.log('    factors:', result.factors)

    return true
  } catch (error) {
    console.error('  ❌ 测试失败:', error instanceof Error ? error.message : String(error))
    return false
  }
}

/**
 * 主测试函数
 */
async function runAllTests() {
  console.log('=== RankTrendAnalyzer功能验证测试 ===')
  console.log('开始时间:', new Date().toISOString())
  console.log('')

  const results = {
    test1: false,
    test2: false,
    test3: false,
  }

  // 运行测试1
  results.test1 = await testGetSnapshotsByType()

  // 运行测试2
  results.test2 = testBuildPercentilesHistory()

  // 运行测试3
  results.test3 = testCalculateRankTrendSignal()

  console.log('\n=== 测试结果汇总 ===')
  console.log('测试1 (getSnapshotsByType):', results.test1 ? '✅ 通过' : '❌ 失败')
  console.log('测试2 (buildPercentilesHistory):', results.test2 ? '✅ 通过' : '❌ 失败')
  console.log('测试3 (calculateRankTrendSignal):', results.test3 ? '✅ 通过' : '❌ 失败')

  const allPassed = results.test1 && results.test2 && results.test3
  console.log('\n总体结果:', allPassed ? '🎉 所有测试通过' : '⚠️ 有测试失败')

  if (allPassed) {
    console.log('\n✅ 结论: RankTrendAnalyzer功能正常')
    console.log('   我修改的DataLayer.ts没有影响RankTrendAnalyzer的计算逻辑')
  } else {
    console.log('\n❌ 结论: RankTrendAnalyzer功能有问题')
    console.log('   需要检查我修改的DataLayer.ts是否影响了RankTrendAnalyzer')
  }

  console.log('\n结束时间:', new Date().toISOString())
  return allPassed
}

// 如果直接运行此文件
if (typeof window !== 'undefined') {
  // 添加到全局对象
  ;(window as any).verifyRankTrendAnalyzer = runAllTests

  console.log('✅ RankTrendAnalyzer验证脚本已加载')
  console.log('   在控制台中运行: verifyRankTrendAnalyzer()')

  // 自动运行测试
  setTimeout(() => {
    console.log('\n🔍 自动运行RankTrendAnalyzer验证测试...')
    runAllTests()
      .then((passed) => {
        if (passed) {
          console.log('🎉 RankTrendAnalyzer验证通过，可以继续分析原始问题')
        } else {
          console.log('⚠️ RankTrendAnalyzer验证失败，需要先修复问题')
        }
      })
      .catch((error) => {
        console.error('❌ 自动测试失败:', error)
      })
  }, 2000)
}

// 导出测试函数
export {
  testGetSnapshotsByType,
  testBuildPercentilesHistory,
  testCalculateRankTrendSignal,
  runAllTests,
}
