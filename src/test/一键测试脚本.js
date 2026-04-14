// ========================================
// 🐲 龙头分析器完整测试脚本
// 复制整个代码到控制台运行
// ========================================

(async function testDragonAnalyzer() {
  console.log('%c========================================', 'color: #ffa502; font-weight: bold');
  console.log('%c🐲 龙头分析器完整测试', 'color: #ffa502; font-size: 16px; font-weight: bold');
  console.log('%c========================================', 'color: #ffa502; font-weight: bold');

  const results = {
    passed: [],
    failed: [],
    warnings: []
  };

  // 辅助函数
  const test = (name, condition, message = '') => {
    if (condition) {
      console.log(`%c✅ ${name}`, 'color: #2ed573');
      results.passed.push(name);
    } else {
      console.log(`%c❌ ${name} ${message}`, 'color: #ff4757');
      results.failed.push(name);
    }
  };

  const warn = (name, message) => {
    console.log(`%c⚠️ ${name}: ${message}`, 'color: #ffa502');
    results.warnings.push(name);
  };

  // ========== 1. 检查依赖服务 ==========
  console.log('\n%c📋 1. 检查依赖服务', 'color: #1e90ff; font-weight: bold');
  
  const deps = {
    dataLayer: !!window.dataLayer,
    dragonBreathAnalyzer: !!window.dragonBreathAnalyzer,
    algorithmManager: !!window.algorithmManager,
    dragonAnalyzer: !!window.dragonAnalyzer,
    sectorAnalyzer: !!window.sectorAnalyzer,
    EventManager: !!window.EventManager
  };
  
  console.table(deps);
  
  Object.entries(deps).forEach(([name, loaded]) => {
    test(`${name} 已加载`, loaded);
  });

  // 如果有缺失依赖，提前返回
  if (Object.values(deps).some(v => !v)) {
    console.log('%c❌ 依赖服务不完整，无法继续测试', 'color: #ff4757');
    return results;
  }

  // ========== 2. 获取基础数据 ==========
  console.log('\n%c📋 2. 获取基础数据', 'color: #1e90ff; font-weight: bold');
  
  const dataLayer = window.dataLayer;
  const stocks = dataLayer?.getStocks?.() || [];
  test('股票数据', stocks.length > 0, `共 ${stocks.length} 只`);
  
  if (stocks.length === 0) {
    console.log('%c❌ 无股票数据，无法继续', 'color: #ff4757');
    return results;
  }

  // 显示股票样本
  console.log('股票样本:', stocks.slice(0, 3).map(s => `${s.code} ${s.name || ''} 涨幅:${s.change || 0}%`));

  // ========== 3. 测试情绪数据 ==========
  console.log('\n%c📋 3. 测试情绪数据', 'color: #1e90ff; font-weight: bold');
  
  const breathAnalyzer = window.dragonBreathAnalyzer;
  const sentiment = breathAnalyzer?.getMarketSentiment?.() || 
                   breathAnalyzer?.getMarketSentinel?.() || 
                   { phase: '未知', overall: 0 };
  
  test('情绪数据', sentiment && sentiment.phase !== '未知', `阶段: ${sentiment.phase}, 分数: ${sentiment.overall}`);
  
  const marketData = breathAnalyzer?.getMarketData?.() || {};
  console.log('市场数据:', {
    涨停: marketData.ztCount || 0,
    跌停: marketData.dtCount || 0,
    炸板率: marketData.zhaban?.rate ? (marketData.zhaban.rate * 100).toFixed(1) + '%' : '未知'
  });

  // ========== 4. 测试 AlgorithmManager.calculateScore ==========
  console.log('\n%c📋 4. 测试 AlgorithmManager.calculateScore', 'color: #1e90ff; font-weight: bold');
  
  const algorithmManager = window.algorithmManager;
  const testStock = stocks[0];
  
  try {
    const scoreResult = await algorithmManager.calculateScore(testStock);
    
    test('calculateScore 返回结果', !!scoreResult);
    test('score 是数字', typeof scoreResult.score === 'number', `实际: ${typeof scoreResult.score}`);
    test('score 不是 NaN', !isNaN(scoreResult.score), `值: ${scoreResult.score}`);
    test('score 在 0-100 之间', scoreResult.score >= 0 && scoreResult.score <= 100, `值: ${scoreResult.score}`);
    
    console.log('分数结果:', {
      股票: `${testStock.code} ${testStock.name}`,
      分数: scoreResult.score,
      算法: scoreResult.algorithm,
      因子数: Object.keys(scoreResult.details || {}).length
    });
  } catch (e) {
    test('calculateScore 执行', false, e.message);
  }

  // ========== 5. 测试 DragonAnalyzer.calculateScore ==========
  console.log('\n%c📋 5. 测试 DragonAnalyzer.calculateScore', 'color: #1e90ff; font-weight: bold');
  
  const dragonAnalyzer = window.dragonAnalyzer;
  
  if (dragonAnalyzer && typeof dragonAnalyzer.calculateScore === 'function') {
    try {
      const scoreResult = await dragonAnalyzer.calculateScore(testStock);
      
      test('DragonAnalyzer.calculateScore 返回结果', !!scoreResult);
      test('返回的 score 是数字', typeof scoreResult.score === 'number', `实际: ${typeof scoreResult.score}`);
      test('score 不是 NaN', !isNaN(scoreResult.score), `值: ${scoreResult.score}`);
      
      console.log('龙头分析器分数:', scoreResult.score);
    } catch (e) {
      test('DragonAnalyzer.calculateScore 执行', false, e.message);
    }
  } else {
    warn('DragonAnalyzer.calculateScore', '方法不存在');
  }

  // ========== 6. 测试龙头级别判定 ==========
  console.log('\n%c📋 6. 测试龙头级别判定', 'color: #1e90ff; font-weight: bold');
  
  if (dragonAnalyzer && typeof dragonAnalyzer.determineLevel === 'function') {
    const testScores = [85, 75, 65, 55, 45];
    const levels = testScores.map(s => dragonAnalyzer.determineLevel(testStock, s));
    
    test('determineLevel 存在', true);
    console.log('级别判定测试:', testScores.map((s, i) => `${s}分 -> ${levels[i] || '无'}`).join(', '));
  } else {
    warn('dragonAnalyzer.determineLevel', '方法不存在');
  }

  // ========== 7. 测试全量更新 ==========
  console.log('\n%c📋 7. 测试全量更新', 'color: #1e90ff; font-weight: bold');
  
  if (dragonAnalyzer && typeof dragonAnalyzer.recalculateAll === 'function') {
    try {
      console.log('触发全量更新...');
      const startTime = Date.now();
      const count = await dragonAnalyzer.recalculateAll();
      const duration = Date.now() - startTime;
      
      test('recalculateAll 执行成功', count > 0 || count === 0, `返回: ${count}, 耗时: ${duration}ms`);
      console.log(`全量更新完成: ${count} 个龙头, 耗时 ${duration}ms`);
    } catch (e) {
      test('recalculateAll 执行', false, e.message);
    }
  } else {
    warn('dragonAnalyzer.recalculateAll', '方法不存在');
  }

  // ========== 8. 测试获取龙头数据 ==========
  console.log('\n%c📋 8. 测试获取龙头数据', 'color: #1e90ff; font-weight: bold');
  
  let leaders = [];
  
  if (dragonAnalyzer && typeof dragonAnalyzer.getAllLeaders === 'function') {
    leaders = dragonAnalyzer.getAllLeaders({ limit: 20 }) || [];
    test('getAllLeaders 返回数组', Array.isArray(leaders), `长度: ${leaders.length}`);
  } else if (dragonAnalyzer && typeof dragonAnalyzer.getAllLeiders === 'function') {
    leaders = dragonAnalyzer.getAllLeiders({ limit: 20 }) || [];
    test('getAllLeiders 返回数组', Array.isArray(leaders), `长度: ${leaders.length}`);
  } else {
    warn('获取龙头数据的方法', '不存在');
  }

  // ========== 9. 验证龙头数据格式 ==========
  console.log('\n%c📋 9. 验证龙头数据格式', 'color: #1e90ff; font-weight: bold');
  
  if (leaders.length > 0) {
    const firstLeader = leaders[0];
    
    test('龙头有 code 字段', !!firstLeader.code);
    test('龙头有 name 字段', !!firstLeader.name);
    test('龙头有 score 字段', typeof firstLeader.score === 'number');
    test('龙头有 level 字段', !!firstLeader.level);
    test('龙头有 levelName 字段', !!firstLeader.levelName);
    
    // 检查级别名称是否正确
    const validLevels = ['TOTAL', 'CONTINUOUS', 'SECTOR', 'MIDDLE', 'EMOTION'];
    const validLevelNames = ['总龙头', '连板龙头', '板块龙头', '中军龙头', '情绪龙头'];
    
    if (firstLeader.level) {
      test('level 值有效', validLevels.includes(firstLeader.level), `实际: ${firstLeader.level}`);
    }
    
    if (firstLeader.levelName) {
      test('levelName 有效', validLevelNames.includes(firstLeader.levelName), `实际: ${firstLeader.levelName}`);
    }
    
    console.log('龙头示例:', {
      代码: firstLeader.code,
      名称: firstLeader.name,
      级别: firstLeader.level,
      级别名称: firstLeader.levelName,
      分数: firstLeader.score,
      涨幅: firstLeader.change,
      连板: firstLeader.continuousDays
    });
    
    // 统计级别分布
    const levelCount = {};
    leaders.forEach(l => {
      levelCount[l.level || '未知'] = (levelCount[l.level || '未知'] || 0) + 1;
    });
    
    console.log('级别分布:', levelCount);
  } else {
    warn('龙头数据为空', '尝试手动生成');
    
    // 手动生成龙头数据
    const manualLeaders = stocks
      .filter(s => (s.change || 0) > 3)
      .map(s => ({
        code: s.code,
        name: s.name || s.code,
        score: 50 + (s.change || 0) * 2,
        level: (s.change || 0) > 7 ? 'TOTAL' : 
               (s.change || 0) > 5 ? 'CONTINUOUS' : 
               (s.change || 0) > 3 ? 'SECTOR' : 'EMOTION',
        levelName: (s.change || 0) > 7 ? '总龙头' : 
                   (s.change || 0) > 5 ? '连板龙头' : 
                   (s.change || 0) > 3 ? '板块龙头' : '情绪龙头',
        change: s.change || 0,
        continuousDays: s.continuousDays || 1
      }))
      .slice(0, 20);
    
    console.log('手动生成的龙头示例:', manualLeaders.slice(0, 3));
  }

  // ========== 10. 测试统计信息 ==========
  console.log('\n%c📋 10. 测试统计信息', 'color: #1e90ff; font-weight: bold');
  
  if (dragonAnalyzer && typeof dragonAnalyzer.getStats === 'function') {
    const stats = dragonAnalyzer.getStats();
    test('getStats 返回对象', !!stats);
    if (stats) {
      console.log('统计信息:', stats);
    }
  } else {
    warn('getStats 方法', '不存在');
  }

  // ========== 11. 测试分布信息 ==========
  console.log('\n%c📋 11. 测试分布信息', 'color: #1e90ff; font-weight: bold');
  
  if (dragonAnalyzer && typeof dragonAnalyzer.getLeaderDistribution === 'function') {
    const distribution = dragonAnalyzer.getLeaderDistribution();
    test('getLeaderDistribution 返回对象', !!distribution);
    if (distribution) {
      console.log('分布信息:', distribution);
    }
  } else {
    warn('getLeaderDistribution 方法', '不存在');
  }

  // ========== 12. 测试变化记录 ==========
  console.log('\n%c📋 12. 测试变化记录', 'color: #1e90ff; font-weight: bold');
  
  if (dragonAnalyzer && typeof dragonAnalyzer.getLeaderChanges === 'function') {
    const changes = dragonAnalyzer.getLeaderChanges(5);
    test('getLeaderChanges 返回数组', Array.isArray(changes));
    if (changes && changes.length > 0) {
      console.log('变化记录:', changes.slice(0, 3));
    }
  } else {
    warn('getLeaderChanges 方法', '不存在');
  }

  // ========== 13. 测试一致性验证 ==========
  console.log('\n%c📋 13. 测试一致性验证', 'color: #1e90ff; font-weight: bold');
  
  if (dragonAnalyzer && typeof dragonAnalyzer.validateConsistency === 'function') {
    try {
      const result = dragonAnalyzer.validateConsistency();
      test('validateConsistency 执行成功', true);
      if (result && !result.valid) {
        warn('数据一致性', `存在 ${result.issues?.length || 0} 个问题`);
      }
    } catch (e) {
      test('validateConsistency 执行', false, e.message);
    }
  } else {
    warn('validateConsistency 方法', '不存在');
  }

  // ========== 总结 ==========
  console.log('\n%c========================================', 'color: #ffa502; font-weight: bold');
  console.log('%c📊 测试总结', 'color: #ffa502; font-size: 16px; font-weight: bold');
  console.log('========================================');
  
  console.log(`✅ 通过: ${results.passed.length} 项`);
  console.log(`⚠️ 警告: ${results.warnings.length} 项`);
  console.log(`❌ 失败: ${results.failed.length} 项`);
  
  if (results.failed.length === 0) {
    console.log('\n%c✅ 所有核心测试通过！', 'color: #2ed573; font-size: 14px; font-weight: bold');
  } else {
    console.log('\n%c❌ 存在失败的测试项', 'color: #ff4757; font-size: 14px; font-weight: bold');
    console.log('失败的测试:', results.failed);
  }
  
  if (leaders.length === 0) {
    console.log('\n%c💡 建议: 龙头数据为空，需要检查 calculateScore 返回的分数', 'color: #ffa502');
  }
  
  console.log('\n%c========================================', 'color: #ffa502; font-weight: bold');
  
  return {
    summary: {
      passed: results.passed.length,
      warnings: results.warnings.length,
      failed: results.failed.length
    },
    leaders: leaders.slice(0, 5),
    details: results
  };
})();