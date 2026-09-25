// ============================================
// 龙头计算完整流程一键测试 (可直接粘贴运行)
// ============================================
;(async function testDragonChain() {
  console.log(
    '%c========== 龙头计算流程测试 ==========',
    'color: #ff4757; font-size: 14px; font-weight: bold',
  )

  const results = {
    dragonReviewService: { status: '❌', leaders: null },
  }

  try {
    // 1. 获取股票列表
    console.log('\n%c1. 获取股票数据', 'color: #3498db; font-weight: bold')
    const stocks = window.dataLayer?.getStocks?.() || []
    console.log(`✅ 获取到 ${stocks.length} 只股票`)

    // 2. 测试龙头分析器
    console.log('\n%c2. 测试龙头分析器', 'color: #3498db; font-weight: bold')
    if (window.dragonReviewService) {
      const leaders = window.dragonReviewService?.getAllLeaders?.()
      console.log(`✅ 当前龙头数量: ${leaders?.length || 0} 个`)

      if (leaders?.length > 0) {
        console.log('\n   龙头列表(前5):')
        leaders.slice(0, 5).forEach((l, i) => {
          console.log(
            `   ${i + 1}. ${l.name}(${l.code}) - ${l.levelName} - 得分:${l.score.toFixed(1)}`,
          )
        })
      }

      results.dragonReviewService.leaders = leaders
      results.dragonReviewService.status = '✅'
    } else {
      console.log('❌ DragonReviewService 未加载（分析服务为首帧空闲后延迟挂载，请稍后重试）')
    }

    // 3. 检查情绪阶段对阈值的影响
    console.log('\n%c3. 检查情绪阶段影响', 'color: #3498db; font-weight: bold')
    const sentiment = window.dragonBreathAnalyzer?.getMarketSentiment?.()
    if (sentiment) {
      console.log(`   当前情绪阶段: ${sentiment.phaseName || sentiment.phase}`)

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

    // 4. 综合诊断
    console.log(
      '\n%c========== 诊断结果 ==========',
      'color: #ff4757; font-size: 14px; font-weight: bold',
    )

    const allPass = Object.values(results).every((r) => r.status === '✅')

    console.log(`
   龙头分析器: ${results.dragonReviewService.status}
    `)

    if (allPass) {
      console.log(
        '%c✅ 龙头计算流程完整，数据链条正常',
        'color: #2ecc71; font-size: 16px; font-weight: bold',
      )
    } else {
      console.log('%c⚠️ 部分环节异常，请检查', 'color: #e67e22; font-size: 16px; font-weight: bold')
    }

    // 5. 返回详细结果
    return {
      success: allPass,
      leaders: results.dragonReviewService.leaders?.length || 0,
      timestamp: Date.now(),
    }
  } catch (error) {
    console.error('❌ 测试过程出错:', error)
    return { success: false, error: error.message }
  }
})()
