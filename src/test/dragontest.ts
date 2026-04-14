// ============================================
// 龙头计算完整流程一键测试 (可直接粘贴运行)
// ============================================
;(async function testDragonChain() {
  console.log(
    '%c========== 龙头计算流程测试 ==========',
    'color: #ff4757; font-size: 14px; font-weight: bold',
  )

  const results = {
    algorithm: { status: '❌', weights: null },
    localStorage: { status: '❌', config: null },
    dragonAnalyzer: { status: '❌', leaders: null },
    score: { status: '❌', details: null },
  }

  try {
    // 1. 检查 AlgorithmManager 状态
    console.log('\n%c1. 检查算法管理器状态', 'color: #3498db; font-weight: bold')
    if (window.algorithmManager) {
      const status = window.algorithmManager.getStatus?.()
      const version = window.algorithmManager.getVersion?.()
      const currentAlgo = window.algorithmManager.getCurrentAlgorithm?.()

      console.log('✅ AlgorithmManager 已加载')
      console.log('   ├─ 版本:', version)
      console.log('   ├─ 当前算法:', currentAlgo?.name || currentAlgo?.id)
      console.log('   └─ 自定义权重:', status?.hasCustomWeights ? '有' : '无')

      results.algorithm.status = '✅'
    } else {
      console.log('❌ AlgorithmManager 未加载')
    }

    // 2. 检查 localStorage 中的权重配置
    console.log('\n%c2. 检查 localStorage 权重配置', 'color: #3498db; font-weight: bold')
    const algorithmConfig = localStorage.getItem('algorithm_config')
    if (algorithmConfig) {
      const config = JSON.parse(algorithmConfig)
      console.log('✅ 找到算法配置')
      console.log('   ├─ 当前算法:', config.currentAlgorithm)
      console.log('   ├─ 自定义权重:', config.customWeights ? '存在' : '无')
      console.log('   └─ 阈值:', config.thresholds)

      if (config.customWeights) {
        console.log('\n   自定义权重详情:')
        Object.entries(config.customWeights).forEach(([key, val]) => {
          console.log(`      ${key}: ${val}`)
        })
      }

      results.localStorage.config = config
      results.localStorage.status = '✅'
    } else {
      console.log('❌ 未找到算法配置')
    }

    // 3. 获取股票列表
    console.log('\n%c3. 获取股票数据', 'color: #3498db; font-weight: bold')
    const stocks = window.dataLayer?.getStocks?.() || []
    console.log(`✅ 获取到 ${stocks.length} 只股票`)

    // 取前5只股票作为样本
    const sampleStocks = stocks.slice(0, 5)
    console.log('   样本股票:', sampleStocks.map((s) => `${s.code}(${s.name})`).join(', '))

    // 4. 测试龙头分析器
    console.log('\n%c4. 测试龙头分析器', 'color: #3498db; font-weight: bold')
    if (window.dragonAnalyzer) {
      const leaders = window.dragonAnalyzer.getAllLeaders?.()
      console.log(`✅ 当前龙头数量: ${leaders?.length || 0} 个`)

      if (leaders?.length > 0) {
        console.log('\n   龙头列表(前5):')
        leaders.slice(0, 5).forEach((l, i) => {
          console.log(
            `   ${i + 1}. ${l.name}(${l.code}) - ${l.levelName} - 得分:${l.score.toFixed(1)}`,
          )
        })
      }

      results.dragonAnalyzer.leaders = leaders
      results.dragonAnalyzer.status = '✅'
    } else {
      console.log('❌ DragonAnalyzer 未加载')
    }

    // 5. 测试单个股票分数计算
    console.log('\n%c5. 测试股票分数计算', 'color: #3498db; font-weight: bold')

    if (sampleStocks.length > 0 && window.algorithmManager) {
      for (const stock of sampleStocks) {
        console.log(`\n   📊 计算 ${stock.code} ${stock.name || ''}`)

        // 获取当前使用的权重
        const weights = window.algorithmManager.getFactorWeights?.()
        console.log('     当前权重配置:')
        if (weights && weights.length > 0) {
          weights.slice(0, 5).forEach((w) => {
            console.log(`        ${w.name}: ${w.weight.toFixed(3)}`)
          })
        } else {
          console.log('       无权重数据')
        }

        // 计算分数
        const scoreResult = await window.algorithmManager.calculateScore?.(stock)

        if (scoreResult) {
          console.log(`     得分: ${scoreResult.score.toFixed(2)}`)
          console.log('     因子详情:')

          // 按贡献度排序
          const details = Object.entries(scoreResult.details || {}).sort(
            (a: any, b: any) => b[1].contribution - a[1].contribution,
          )

          if (details.length > 0) {
            details.slice(0, 5).forEach(([key, val]: [string, any]) => {
              console.log(
                `       ${val.name}: ${val.score.toFixed(1)} × ${val.weight.toFixed(3)} = ${val.contribution.toFixed(2)}`,
              )
            })
          } else {
            console.log('       无因子详情')
          }

          results.score.details = scoreResult.details
        } else {
          console.log(`      ❌ 计算失败`)
        }
      }
      results.score.status = '✅'
    }

    // 6. 测试情绪阶段对阈值的影响
    console.log('\n%c6. 检查情绪阶段影响', 'color: #3498db; font-weight: bold')
    const sentiment = window.dragonBreathAnalyzer?.getMarketSentiment?.()
    if (sentiment) {
      console.log(`   当前情绪阶段: ${sentiment.phase} (得分:${sentiment.overall})`)

      // 获取当前阈值乘数
      const thresholdMultiplier = window.dragonBreathAnalyzer?.getCurrentThresholdMultiplier?.()
      if (thresholdMultiplier) {
        console.log('   阈值乘数:')
        console.log(`     总龙头: ${thresholdMultiplier.totalLeader}`)
        console.log(`     连板龙头: ${thresholdMultiplier.continuousLeader}`)
        console.log(`     板块龙头: ${thresholdMultiplier.sectorLeader}`)
        console.log(`     中军龙头: ${thresholdMultiplier.middleLeader}`)
        console.log(`     情绪龙头: ${thresholdMultiplier.emotionLeader}`)
      }
    } else {
      console.log('   ⚠️ 无法获取情绪阶段信息')
    }

    // 7. 综合诊断
    console.log(
      '\n%c========== 诊断结果 ==========',
      'color: #ff4757; font-size: 14px; font-weight: bold',
    )

    const allPass = Object.values(results).every((r) => r.status === '✅')

    console.log(`
   算法管理器: ${results.algorithm.status}
   localStorage: ${results.localStorage.status}
   龙头分析器: ${results.dragonAnalyzer.status}
   分数计算: ${results.score.status}
    `)

    if (allPass) {
      console.log(
        '%c✅ 龙头计算流程完整，数据链条正常',
        'color: #2ecc71; font-size: 16px; font-weight: bold',
      )
    } else {
      console.log('%c⚠️ 部分环节异常，请检查', 'color: #e67e22; font-size: 16px; font-weight: bold')
    }

    // 8. 返回详细结果
    return {
      success: allPass,
      algorithm: results.algorithm.status === '✅',
      localStorage: results.localStorage.config,
      leaders: results.dragonAnalyzer.leaders?.length || 0,
      sample: results.score.details,
      timestamp: Date.now(),
    }
  } catch (error) {
    console.error('❌ 测试过程出错:', error)
    return { success: false, error: error.message }
  }
})()
