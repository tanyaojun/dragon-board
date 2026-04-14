// src/test/simpleTest.js
// 简单的测试脚本，可以直接在浏览器控制台中运行

/**
 * 简单的RankTrendAnalyzer验证测试
 * 这个脚本可以直接在浏览器控制台中运行
 */
async function simpleRankTrendAnalyzerTest() {
  console.log('🧪 开始简单的RankTrendAnalyzer验证测试...')

  try {
    // 1. 检查必要的全局对象
    if (!window.rankTrendAnalyzer) {
      console.error('❌ rankTrendAnalyzer 不存在')
      return false
    }

    if (!window.dataLayer) {
      console.error('❌ dataLayer 不存在')
      return false
    }

    console.log('✅ 必要的全局对象存在')

    // 2. 获取股票数据
    const stocks = window.dataLayer.getStocks()
    if (!stocks || stocks.length === 0) {
      console.error('❌ 没有股票数据')
      return false
    }

    console.log(`📊 当前股票数量: ${stocks.length}`)

    // 3. 创建简单的排名映射（取前20个股票）
    const rankMap = new Map()
    const sampleStocks = stocks.slice(0, Math.min(20, stocks.length))
    sampleStocks.forEach((stock, index) => {
      rankMap.set(stock.code, index + 1)
    })

    console.log(`🔍 使用 ${rankMap.size} 个股票进行测试`)

    // 4. 调用getRankTrends方法
    console.log('🔄 调用 rankTrendAnalyzer.getRankTrends()...')
    const startTime = Date.now()
    const results = await window.rankTrendAnalyzer.getRankTrends(rankMap)
    const endTime = Date.now()

    if (!results || results.size === 0) {
      console.error('❌ 没有获取到排名趋势分析结果')
      return false
    }

    console.log(`✅ 获取到 ${results.size} 个结果，耗时: ${endTime - startTime}ms`)

    // 5. 检查4个信号
    let macdCount = 0
    let directionCount = 0
    let crossCount = 0
    let accelerationCount = 0

    results.forEach((result, code) => {
      // MACD信号
      if (result.macdCross && result.macdCross !== 'none') {
        macdCount++
      }

      // 方向一致性信号
      if (result.directionSignal) {
        directionCount++
      }

      // 零线交叉信号
      if (result.crossSignal) {
        crossCount++
      }

      // 动量加速度信号
      if (result.accelerationSignal) {
        accelerationCount++
      }
    })

    // 6. 输出结果
    console.log('\n📈 信号统计结果：')
    console.log(`- MACD信号: ${macdCount} 个股票`)
    console.log(`- 方向一致性信号: ${directionCount} 个股票`)
    console.log(`- 零线交叉信号: ${crossCount} 个股票`)
    console.log(`- 动量加速度信号: ${accelerationCount} 个股票`)

    // 7. 输出前5个股票的详细信号
    console.log('\n🔍 前5个股票的详细信号：')
    let count = 0
    for (const [code, result] of results) {
      if (count >= 5) break

      const stock = stocks.find((s) => s.code === code)
      console.log(`${count + 1}. ${code} ${stock?.name || '未知'}`)
      console.log(`   MACD: ${result.macdCross}`)
      console.log(`   方向: ${result.directionSignal} (置信度: ${result.directionConfidence}%)`)
      console.log(`   交叉: ${result.crossSignal} (置信度: ${result.crossConfidence}%)`)
      console.log(
        `   加速度: ${result.accelerationSignal} (置信度: ${result.accelerationConfidence}%)`,
      )
      console.log(`   最终信号: ${result.finalSignal} (置信度: ${result.finalConfidence}%)`)
      count++
    }

    console.log('\n🎉 测试完成！')
    return true
  } catch (error) {
    console.error('❌ 测试失败:', error)
    return false
  }
}

// 注册到全局对象
if (typeof window !== 'undefined') {
  window.simpleRankTrendAnalyzerTest = simpleRankTrendAnalyzerTest
  console.log('✅ simpleRankTrendAnalyzerTest 函数已注册到全局对象')
  console.log('💡 在浏览器控制台中输入: simpleRankTrendAnalyzerTest()')
}

// 如果直接运行这个文件，自动执行测试
if (typeof window !== 'undefined' && window.location.href.includes('test.html')) {
  console.log('🚀 自动执行测试...')
  simpleRankTrendAnalyzerTest().then((result) => {
    console.log(result ? '✅ 测试通过' : '❌ 测试失败')
  })
}
