// src/test/validateRankTrendAnalyzer.ts
// 最小化的 RankTrend 验证脚本 - 验证RankTrendAnalyzer的4个信号计算逻辑

import { rankTrendAnalyzer } from '../services/RankTrendAnalyzer'
import { dataLayer } from '../services/DataLayer'

/**
 * 验证RankTrendAnalyzer的4个信号计算逻辑
 * 1. MACD信号
 * 2. 方向一致性信号
 * 3. 零线交叉信号
 * 4. 动量加速度信号
 */
export async function validateRankTrendAnalyzerSignals(): Promise<{
  success: boolean
  results: {
    macdSignals: number
    directionSignals: number
    crossSignals: number
    accelerationSignals: number
    totalStocks: number
    validationTime: number
  }
  errors: string[]
}> {
  const errors: string[] = []
  const startTime = Date.now()

  try {
    console.log('🧪 开始验证RankTrendAnalyzer的4个信号计算逻辑...')

    // 1. 检查rankTrendAnalyzer是否可用
    if (!rankTrendAnalyzer) {
      throw new Error('rankTrendAnalyzer不可用')
    }

    // 2. 获取当前股票数据
    const stocks = dataLayer.getStocks()
    if (stocks.length === 0) {
      throw new Error('没有股票数据')
    }

    console.log(`📊 当前股票数量: ${stocks.length}`)

    // 3. 创建排名映射（使用综合排名）
    const rankMap = new Map<string, number>()
    stocks.forEach((stock, index) => {
      rankMap.set(stock.code, stock.compRank || index + 1)
    })

    // 4. 获取排名趋势分析结果
    console.log('🔍 获取排名趋势分析结果...')
    const rankTrends = await rankTrendAnalyzer.getRankTrends(rankMap)

    if (rankTrends.size === 0) {
      throw new Error('没有获取到排名趋势分析结果')
    }

    console.log(`✅ 获取到 ${rankTrends.size} 个股票的排名趋势分析结果`)

    // 5. 统计4个信号的数量
    let macdSignals = 0
    let directionSignals = 0
    let crossSignals = 0
    let accelerationSignals = 0

    // 6. 验证每个信号的逻辑
    const validationResults: Array<{
      code: string
      name: string
      macdCross: string
      directionSignal: string
      crossSignal: string
      accelerationSignal: string
      finalSignal: string
      confidence: number
    }> = []

    rankTrends.forEach((trend, code) => {
      const stock = stocks.find(s => s.code === code)

      // 统计信号数量
      if (trend.macdCross !== 'none') macdSignals++
      // directionSignal、crossSignal、accelerationSignal的类型是'buy' | 'sell' | 'hold'，没有'none'
      // 所以检查信号是否存在即可
      if (trend.directionSignal) directionSignals++
      if (trend.crossSignal) crossSignals++
      if (trend.accelerationSignal) accelerationSignals++

      // 记录验证结果
      validationResults.push({
        code,
        name: stock?.name || '未知',
        macdCross: trend.macdCross,
        // 这些信号类型没有'none'，所以使用空字符串或undefined
        directionSignal: trend.directionSignal || '',
        crossSignal: trend.crossSignal || '',
        accelerationSignal: trend.accelerationSignal || '',
        finalSignal: trend.finalSignal || '',
        confidence: trend.finalConfidence || 0
      })
    })

    // 7. 输出验证结果
    console.log('\n📈 信号验证结果：')
    console.log(`- MACD信号: ${macdSignals} 个股票 (${((macdSignals / rankTrends.size) * 100).toFixed(1)}%)`)
    console.log(`- 方向一致性信号: ${directionSignals} 个股票 (${((directionSignals / rankTrends.size) * 100).toFixed(1)}%)`)
    console.log(`- 零线交叉信号: ${crossSignals} 个股票 (${((crossSignals / rankTrends.size) * 100).toFixed(1)}%)`)
    console.log(`- 动量加速度信号: ${accelerationSignals} 个股票 (${((accelerationSignals / rankTrends.size) * 100).toFixed(1)}%)`)

    // 8. 输出前10个股票的详细信号
    console.log('\n🔍 前10个股票的详细信号：')
    validationResults.slice(0, 10).forEach((result, index) => {
      console.log(`${index + 1}. ${result.code} ${result.name}`)
      console.log(`   MACD: ${result.macdCross}, 方向: ${result.directionSignal}, 交叉: ${result.crossSignal}, 加速度: ${result.accelerationSignal}`)
      console.log(`   最终信号: ${result.finalSignal} (置信度: ${result.confidence}%)`)
    })

    // 9. 验证信号逻辑的合理性
    const logicErrors = validateSignalLogic(validationResults)
    errors.push(...logicErrors)

    const validationTime = Date.now() - startTime

    return {
      success: errors.length === 0,
      results: {
        macdSignals,
        directionSignals,
        crossSignals,
        accelerationSignals,
        totalStocks: rankTrends.size,
        validationTime
      },
      errors
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
        validationTime: Date.now() - startTime
      },
      errors
    }
  }
}

/**
 * 验证信号逻辑的合理性
 */
function validateSignalLogic(results: Array<{
  macdCross: string
  directionSignal: string
  crossSignal: string
  accelerationSignal: string
  finalSignal: string
  confidence: number
}>): string[] {
  const errors: string[] = []

  // 1. 检查置信度范围是否合理
  results.forEach((result, index) => {
    if (result.confidence < 0 || result.confidence > 100) {
      errors.push(`股票 ${index + 1}: 置信度 ${result.confidence}% 超出合理范围 (0-100)`)
    }
  })

  // 2. 检查信号一致性
  let inconsistentCount = 0
  results.forEach((result, index) => {
    const signals = [
      result.macdCross,
      result.directionSignal,
      result.crossSignal,
      result.accelerationSignal
    ]

    const buySignals = signals.filter(s => s === 'buy' || s === 'golden').length
    const sellSignals = signals.filter(s => s === 'sell' || s === 'death').length

    // 如果买信号和卖信号都很多，可能有问题
    if (buySignals >= 2 && sellSignals >= 2) {
      inconsistentCount++
    }
  })

  if (inconsistentCount > results.length * 0.3) {
    errors.push(`信号不一致的股票过多: ${inconsistentCount}/${results.length} (${((inconsistentCount / results.length) * 100).toFixed(1)}%)`)
  }

  // 3. 检查最终信号的合理性
  const validFinalSignals = results.filter(r =>
    r.finalSignal === 'buy' || r.finalSignal === 'sell' || r.finalSignal === 'hold'
  ).length

  if (validFinalSignals !== results.length) {
    errors.push(`最终信号有效性: ${validFinalSignals}/${results.length} 个有效`)
  }

  return errors
}

/**
 * 导出验证函数到全局对象，方便在浏览器控制台中调用
 */
if (typeof window !== 'undefined') {
  (window as any).validateRankTrendAnalyzer = async () => {
    console.log('🚀 在浏览器中运行RankTrendAnalyzer验证...')
    const result = await validateRankTrendAnalyzerSignals()

    if (result.success) {
      console.log('🎉 验证成功！')
      console.log('📊 结果摘要：')
      console.log(`- 总股票数: ${result.results.totalStocks}`)
      console.log(`- 验证耗时: ${result.results.validationTime}ms`)
      console.log(`- MACD信号: ${result.results.macdSignals}`)
      console.log(`- 方向信号: ${result.results.directionSignals}`)
      console.log(`- 交叉信号: ${result.results.crossSignals}`)
      console.log(`- 加速度信号: ${result.results.accelerationSignals}`)
    } else {
      console.error('❌ 验证失败！')
      result.errors.forEach(error => console.error(`  - ${error}`))
    }

    return result
  }

  console.log('✅ validateRankTrendAnalyzer 函数已注册到全局对象')
  console.log('💡 在浏览器控制台中输入: validateRankTrendAnalyzer()')
}

// 默认导出
export default validateRankTrendAnalyzerSignals
