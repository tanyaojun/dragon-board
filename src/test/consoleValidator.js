// src/test/consoleValidator.js
// 可以直接在浏览器控制台中粘贴运行的验证函数

/**
 * 完整的RankTrendAnalyzer验证函数
 * 可以直接在浏览器控制台中粘贴运行
 */
async function validateRankTrendAnalyzerConsole() {
  console.log('🧪 开始验证RankTrendAnalyzer的4个信号计算逻辑...')

  const startTime = Date.now()
  const errors = []

  try {
    // 1. 检查必要的全局对象
    if (!window.rankTrendAnalyzer) {
      throw new Error('rankTrendAnalyzer不可用')
    }

    if (!window.dataLayer) {
      throw new Error('dataLayer不可用')
    }

    console.log('✅ 必要的全局对象存在')

    // 2. 获取股票数据
    const stocks = window.dataLayer.getStocks()
    if (!stocks || stocks.length === 0) {
      throw new Error('没有股票数据')
    }

    console.log(`📊 当前股票数量: ${stocks.length}`)

    // 3. 创建排名映射（使用综合排名或简单排名）
    const rankMap = new Map()
    stocks.forEach((stock, index) => {
      // 优先使用compRank，如果没有则使用索引
      rankMap.set(stock.code, stock.compRank || index + 1)
    })

    // 4. 获取排名趋势分析结果
    console.log('🔍 获取排名趋势分析结果...')
    const rankTrends = await window.rankTrendAnalyzer.getRankTrends(rankMap)

    if (!rankTrends || rankTrends.size === 0) {
      throw new Error('没有获取到排名趋势分析结果')
    }

    console.log(`✅ 获取到 ${rankTrends.size} 个股票的排名趋势分析结果`)

    // 5. 统计4个信号的数量
    let macdSignals = 0
    let directionSignals = 0
    let crossSignals = 0
    let accelerationSignals = 0

    // 6. 收集验证结果
    const validationResults = []

    rankTrends.forEach((trend, code) => {
      const stock = stocks.find((s) => s.code === code)

      // 统计信号数量
      if (trend.macdCross && trend.macdCross !== 'none') macdSignals++
      if (trend.directionSignal) directionSignals++
      if (trend.crossSignal) crossSignals++
      if (trend.accelerationSignal) accelerationSignals++

      // 记录验证结果
      validationResults.push({
        code,
        name: stock?.name || '未知',
        macdCross: trend.macdCross || 'none',
        directionSignal: trend.directionSignal || '',
        crossSignal: trend.crossSignal || '',
        accelerationSignal: trend.accelerationSignal || '',
        finalSignal: trend.finalSignal || '',
        confidence: trend.finalConfidence || 0,
      })
    })

    // 7. 输出验证结果
    console.log('\n📈 信号验证结果：')
    console.log(
      `- MACD信号: ${macdSignals} 个股票 (${((macdSignals / rankTrends.size) * 100).toFixed(1)}%)`,
    )
    console.log(
      `- 方向一致性信号: ${directionSignals} 个股票 (${((directionSignals / rankTrends.size) * 100).toFixed(1)}%)`,
    )
    console.log(
      `- 零线交叉信号: ${crossSignals} 个股票 (${((crossSignals / rankTrends.size) * 100).toFixed(1)}%)`,
    )
    console.log(
      `- 动量加速度信号: ${accelerationSignals} 个股票 (${((accelerationSignals / rankTrends.size) * 100).toFixed(1)}%)`,
    )

    // 8. 输出前10个股票的详细信号
    console.log('\n🔍 前10个股票的详细信号：')
    validationResults.slice(0, 10).forEach((result, index) => {
      console.log(`${index + 1}. ${result.code} ${result.name}`)
      console.log(`   MACD: ${result.macdCross}`)
      console.log(`   方向: ${result.directionSignal || '无'}`)
      console.log(`   交叉: ${result.crossSignal || '无'}`)
      console.log(`   加速度: ${result.accelerationSignal || '无'}`)
      console.log(`   最终信号: ${result.finalSignal || '无'} (置信度: ${result.confidence}%)`)
    })

    // 9. 验证信号逻辑的合理性
    const logicErrors = validateSignalLogicConsole(validationResults)
    errors.push(...logicErrors)

    const validationTime = Date.now() - startTime

    // 10. 输出总结
    console.log('\n📊 验证总结：')
    console.log(`- 总股票数: ${rankTrends.size}`)
    console.log(`- 验证耗时: ${validationTime}ms`)
    console.log(`- 发现错误: ${errors.length} 个`)

    if (errors.length > 0) {
      console.log('\n❌ 发现的问题：')
      errors.forEach((error) => console.log(`  - ${error}`))
    } else {
      console.log('\n🎉 验证成功！所有信号计算逻辑正常')
    }

    return {
      success: errors.length === 0,
      results: {
        macdSignals,
        directionSignals,
        crossSignals,
        accelerationSignals,
        totalStocks: rankTrends.size,
        validationTime,
      },
      errors,
    }
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error)
    console.error('❌ 验证失败:', errorMessage)
    errors.push(errorMessage)

    return {
      success: false,
      results: {
        macdSignals: 0,
        directionSignals: 0,
        crossSignals: 0,
        accelerationSignals: 0,
        totalStocks: 0,
        validationTime: Date.now() - startTime,
      },
      errors,
    }
  }
}

/**
 * 验证信号逻辑的合理性
 */
function validateSignalLogicConsole(results) {
  const errors = []

  // 1. 检查置信度范围是否合理
  results.forEach((result, index) => {
    if (result.confidence < 0 || result.confidence > 100) {
      errors.push(
        `股票 ${index + 1} (${result.code}): 置信度 ${result.confidence}% 超出合理范围 (0-100)`,
      )
    }
  })

  // 2. 检查信号一致性
  let inconsistentCount = 0
  results.forEach((result, index) => {
    const signals = [
      result.macdCross,
      result.directionSignal,
      result.crossSignal,
      result.accelerationSignal,
    ]

    const buySignals = signals.filter((s) => s === 'buy' || s === 'golden').length
    const sellSignals = signals.filter((s) => s === 'sell' || s === 'death').length

    // 如果买信号和卖信号都很多，可能有问题
    if (buySignals >= 2 && sellSignals >= 2) {
      inconsistentCount++
      errors.push(
        `股票 ${index + 1} (${result.code}): 信号不一致 (${buySignals}个买信号, ${sellSignals}个卖信号)`,
      )
    }
  })

  if (inconsistentCount > results.length * 0.3) {
    errors.push(
      `信号不一致的股票过多: ${inconsistentCount}/${results.length} (${((inconsistentCount / results.length) * 100).toFixed(1)}%)`,
    )
  }

  // 3. 检查最终信号的合理性
  const validFinalSignals = results.filter(
    (r) => r.finalSignal === 'buy' || r.finalSignal === 'sell' || r.finalSignal === 'hold',
  ).length

  if (validFinalSignals !== results.length) {
    errors.push(`最终信号有效性: ${validFinalSignals}/${results.length} 个有效`)
  }

  return errors
}

// 注册到全局对象
if (typeof window !== 'undefined') {
  window.validateRankTrendAnalyzerConsole = validateRankTrendAnalyzerConsole
  console.log('✅ validateRankTrendAnalyzerConsole 函数已注册到全局对象')
  console.log('💡 在浏览器控制台中输入: validateRankTrendAnalyzerConsole()')
}

// 如果直接运行这个文件，自动执行验证
if (typeof window !== 'undefined' && window.location.href.includes('test.html')) {
  console.log('🚀 自动执行验证...')
  validateRankTrendAnalyzerConsole().then((result) => {
    console.log(result.success ? '✅ 验证通过' : '❌ 验证失败')
  })
}
