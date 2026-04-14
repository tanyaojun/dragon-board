// ========== 测试脚本：获取当日15:30 MACD金叉的股票 ==========

// 1. 获取所有半小时快照
const allDates = await dataLayer.getSnapshotDates()
const halfHourSnapshots = []

for (const date of allDates) {
  const snapshot = await dataLayer.getSnapshotFromDB(date)
  if (snapshot?.type === 'half_hour') {
    halfHourSnapshots.push({ date, timestamp: snapshot.timestamp, snapshot })
  }
}

// 按时间排序（最新的在前）
halfHourSnapshots.sort((a, b) => b.timestamp - a.timestamp)

// 2. 找到当日15:30的快照
let targetSnapshot = null
let targetDate = ''

for (const item of halfHourSnapshots) {
  const d = new Date(item.timestamp)
  // 检查是否是今天（或者最近一天）的15:30
  if (d.getHours() === 15 && d.getMinutes() === 30) {
    targetSnapshot = item.snapshot
    targetDate = item.date
    break
  }
}

if (!targetSnapshot) {
  // 取最新的快照
  targetSnapshot = halfHourSnapshots[0]?.snapshot
  targetDate = halfHourSnapshots[0]?.date
  console.log('未找到15:30快照，使用最新快照:', targetDate)
} else {
  console.log('目标快照:', targetDate)
  console.log('快照时间:', new Date(targetSnapshot.timestamp).toLocaleString())
}

// 3. 从快照中提取MACD金叉的股票
const hotlist = targetSnapshot?.hotlist || []
console.log('热榜股票数量:', hotlist.length)

const goldenCrossStocks = []
const deathCrossStocks = []
const noCrossStocks = []

for (const stock of hotlist) {
  const macdCross = stock.macdCross
  const signals = stock.signals || {}
  const finalSignal = signals.final?.signal
  const finalConfidence = signals.final?.confidence
  
  if (macdCross === 'golden') {
    goldenCrossStocks.push({
      code: stock.code,
      name: stock.name,
      rank: stock.rank,
      change: stock.change,
      finalSignal: finalSignal || '无',
      finalConfidence: Math.round(finalConfidence || 0),
      rankTrend: signals.rankTrend?.signal,
      rankTrendConf: signals.rankTrend?.confidence,
      moneyFlow: signals.money?.signal,
      moneyFlowConf: signals.money?.confidence,
      technical: signals.technical?.signal,
      technicalConf: signals.technical?.confidence,
      volumeRatio: stock.volumeRatio,
      turnoverRate: stock.turnoverRate,
      zlje: stock.zlje
    })
  } else if (macdCross === 'death') {
    deathCrossStocks.push({
      code: stock.code,
      name: stock.name,
      rank: stock.rank,
      change: stock.change
    })
  } else {
    noCrossStocks.push({
      code: stock.code,
      name: stock.name,
      rank: stock.rank,
      change: stock.change
    })
  }
}

// 4. 输出结果
console.log('\n' + '='.repeat(80))
console.log('📊 MACD金叉股票 - ' + targetDate)
console.log('='.repeat(80))

console.log('\n🔴 MACD金叉股票数量:', goldenCrossStocks.length)
if (goldenCrossStocks.length === 0) {
  console.log('没有MACD金叉的股票')
} else {
  console.log('\n详细列表:')
  console.log('-'.repeat(80))
  
  goldenCrossStocks.forEach((s, i) => {
    console.log(`\n${i+1}. ${s.code} ${s.name}`)
    console.log(`   综合排名: ${s.rank}`)
    console.log(`   涨跌幅: ${s.change > 0 ? '+' : ''}${s.change?.toFixed(2)}%`)
    console.log(`   综合信号: ${s.finalSignal} (${s.finalConfidence}%)`)
    console.log(`   排名趋势: ${s.rankTrend || '无'} (${s.rankTrendConf || 0}%)`)
    console.log(`   资金信号: ${s.moneyFlow || '无'} (${s.moneyFlowConf || 0}%)`)
    console.log(`   技术信号: ${s.technical || '无'} (${s.technicalConf || 0}%)`)
    if (s.volumeRatio) console.log(`   量比: ${s.volumeRatio.toFixed(2)}`)
    if (s.turnoverRate) console.log(`   换手率: ${s.turnoverRate.toFixed(2)}%`)
    if (s.zlje) console.log(`   主力净额: ${(s.zlje / 10000).toFixed(0)}万`)
  })
}

// 5. 统计MACD死叉
console.log('\n' + '='.repeat(80))
console.log('🟢 MACD死叉股票数量:', deathCrossStocks.length)
if (deathCrossStocks.length > 0 && deathCrossStocks.length <= 20) {
  console.log(deathCrossStocks.map(s => `${s.code} ${s.name}(${s.change>0?'+':''}${s.change}%)`).join(', '))
} else if (deathCrossStocks.length > 20) {
  console.log(`前20只: ${deathCrossStocks.slice(0,20).map(s => s.code).join(', ')}...`)
}

// 6. 输出金叉股票代码列表
if (goldenCrossStocks.length > 0) {
  console.log('\n📝 MACD金叉股票代码列表:')
  console.log(goldenCrossStocks.map(s => s.code).join(', '))
  
  // 输出带置信度的格式
  console.log('\n📝 带置信度列表:')
  goldenCrossStocks.forEach(s => {
    console.log(`${s.code} ${s.name} | 排名:${s.rank} | 涨幅:${s.change}% | 综合:${s.finalSignal}(${s.finalConfidence}%)`)
  })
}

// 7. 统计汇总
console.log('\n' + '='.repeat(80))
console.log('📈 统计汇总')
console.log('='.repeat(80))
console.log(`热榜股票总数: ${hotlist.length}`)
console.log(`MACD金叉: ${goldenCrossStocks.length} (${(goldenCrossStocks.length/hotlist.length*100).toFixed(1)}%)`)
console.log(`MACD死叉: ${deathCrossStocks.length} (${(deathCrossStocks.length/hotlist.length*100).toFixed(1)}%)`)
console.log(`无交叉: ${noCrossStocks.length} (${(noCrossStocks.length/hotlist.length*100).toFixed(1)}%)`)