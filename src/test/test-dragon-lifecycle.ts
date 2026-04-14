// D:\dragon-board\src\test\test-dragon-lifecycle.ts

// ✅ 修正导入路径 - 从 services 目录导入
import { dragonLifecycle } from '../services/DragonLifecycle'

// ========== 模拟数据 ==========
const mockLeaders = [
  {
    code: '000001',
    name: '平安银行',
    continuousDays: 3,
    score: 88,
    level: 'SECTOR',
    sentimentInfo: { phase: '活跃期', overall: 75 }
  },
  {
    code: '000002',
    name: '万科A',
    continuousDays: 2,
    score: 85,
    level: 'SECTOR',
    sentimentInfo: { phase: '活跃期', overall: 75 }
  },
  {
    code: '000003',
    name: '中兴通讯',
    continuousDays: 1,
    score: 68,
    level: 'POTENTIAL',
    sentimentInfo: { phase: '震荡期', overall: 50 }
  }
]

// ========== 测试函数 ==========
async function testDragonLifecycle() {
  console.log('='.repeat(60))
  console.log('🚀 开始测试龙头生命周期追踪器')
  console.log('='.repeat(60))

  // 测试1: 查看规则
  console.log('\n📌 测试1: 查看当前规则')
  console.log('-'.repeat(40))
  
  const rules = dragonLifecycle.getConfirmRules()
  console.log('快速通道:', rules.FAST_TRACK.map(r => r.desc))
  console.log('S级要求:', rules.SCORE_REQUIREMENTS.S)
  console.log('主队列观察期:', rules.OBSERVATION_HOURS.primary)

  // 测试2: 队列状态
  console.log('\n📌 测试2: 查看队列状态')
  console.log('-'.repeat(40))
  
  const stats = dragonLifecycle.getObservationStats()
  console.log('队列统计:', stats)

  // 测试3: 配置更新
  console.log('\n📌 测试3: 测试配置更新')
  console.log('-'.repeat(40))
  
  const oldRules = dragonLifecycle.getConfirmRules()
  console.log('原S级要求:', oldRules.SCORE_REQUIREMENTS.S)

  dragonLifecycle.updateConfirmRules({
    SCORE_REQUIREMENTS: {
      ...oldRules.SCORE_REQUIREMENTS,
      S: { min: 70, time: 15, count: 2 }
    }
  })

  const newRules = dragonLifecycle.getConfirmRules()
  console.log('新S级要求:', newRules.SCORE_REQUIREMENTS.S)
  console.log('配置更新:', oldRules.SCORE_REQUIREMENTS.S.min !== newRules.SCORE_REQUIREMENTS.S.min ? '✅成功' : '❌失败')

  // 测试4: 统计信息
  console.log('\n📌 测试4: 查看统计信息')
  console.log('-'.repeat(40))
  
  const status = dragonLifecycle.getStatus()
  console.log('系统状态:', {
    trackedCount: status.trackedCount,
    confirmedCount: status.confirmedCount,
    activeCount: status.activeCount,
    observationCount: status.observationCount
  })

  console.log('\n' + '='.repeat(60))
  console.log('✅ 测试完成！')
  console.log('='.repeat(60))
}

// 运行测试
testDragonLifecycle().catch(console.error)