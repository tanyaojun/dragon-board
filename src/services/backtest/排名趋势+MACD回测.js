// ========== 回测：昨日收盘买入+MACD金叉的股票今日表现 ==========

// 1. 获取昨天收盘时的半小时快照
const allDates = await dataLayer.getSnapshotDates()
const halfHourSnapshots = []

for (const date of allDates) {
  const snapshot = await dataLayer.getSnapshotFromDB(date)
  if (snapshot?.type === 'half_hour') {
    halfHourSnapshots.push({ date, timestamp: snapshot.timestamp, snapshot })
  }
}
halfHourSnapshots.sort((a, b) => b.timestamp - a.timestamp)

// 找昨天15:30的快照
let targetSnapshot = null
let targetDate = ''

for (const item of halfHourSnapshots) {
  const d = new Date(item.timestamp)
  if (d.getHours() === 15 && d.getMinutes() === 30) {
    targetSnapshot = item.snapshot
    targetDate = item.date
    break
  }
}

if (!targetSnapshot) {
  targetSnapshot = halfHourSnapshots[0]?.snapshot
  targetDate = halfHourSnapshots[0]?.date
}

console.log('回测快照:', targetDate)
console.log('快照时间:', new Date(targetSnapshot?.timestamp).toLocaleString())

// 2. 从快照中筛选买入信号 + MACD金叉的股票
const hotlist = targetSnapshot?.hotlist || []
const buyWithGolden = []

for (const stock of hotlist) {
  const signals = stock.signals || {}
  const finalSignal = signals.final?.signal
  const macdCross = stock.macdCross
  
  if (finalSignal === 'buy' && macdCross === 'golden') {
    buyWithGolden.push({
      code: stock.code,
      name: stock.name,
      rank: stock.rank,
      change: stock.change,
      confidence: Math.round(signals.final?.confidence || 0),
      macdCross: macdCross
    })
  }
}

console.log('\n昨日收盘买入+MACD金叉股票数量:', buyWithGolden.length)
if (buyWithGolden.length === 0) {
  console.log('没有符合条件的股票')
} else {
  console.log('\n股票列表:')
  buyWithGolden.forEach((s, i) => {
    console.log(`${i+1}. ${s.code} ${s.name} (排名${s.rank}, 涨幅${s.change}%, 置信度${s.confidence}%)`)
  })
}

// 3. 获取今天的实时数据
const todayStocks = dataLayer.getStocks()
const todayMap = new Map()
todayStocks.forEach(s => todayMap.set(s.code, s))

// 4. 计算今日表现
console.log('\n' + '='.repeat(80))
console.log('📈 今日表现')
console.log('='.repeat(80))

let upCount = 0
let downCount = 0
let avgChange = 0
const results = []

for (const stock of buyWithGolden) {
  const today = todayMap.get(stock.code)
  if (today) {
    const todayChange = today.change || 0
    avgChange += todayChange
    if (todayChange > 0) upCount++
    else if (todayChange < 0) downCount++
    
    results.push({
      code: stock.code,
      name: stock.name,
      yesterdayRank: stock.rank,
      yesterdayChange: stock.change,
      todayChange: todayChange,
      todayRank: today.compRank,
      todayVolumeRatio: today.volumeRatio,
      todayTurnover: today.turnoverRate
    })
  }
}

// 按今日涨幅排序
results.sort((a, b) => b.todayChange - a.todayChange)

console.log('\n详细表现:')
console.log('-'.repeat(80))

results.forEach((r, i) => {
  const changeColor = r.todayChange > 0 ? '+' : ''
  console.log(`${i+1}. ${r.code} ${r.name}`)
  console.log(`   昨日: 排名${r.yesterdayRank} 涨幅${r.yesterdayChange}%`)
  console.log(`   今日: 涨幅${changeColor}${r.todayChange.toFixed(2)}% 排名${r.todayRank}`)
  if (r.todayVolumeRatio) console.log(`   量比: ${r.todayVolumeRatio.toFixed(2)}`)
  if (r.todayTurnover) console.log(`   换手率: ${r.todayTurnover.toFixed(2)}%`)
  console.log('')
})

// 5. 统计汇总
console.log('='.repeat(80))
console.log('📊 统计汇总')
console.log('='.repeat(80))
console.log(`符合条件的股票总数: ${results.length}`)
console.log(`上涨家数: ${upCount} (${(upCount/results.length*100).toFixed(1)}%)`)
console.log(`下跌家数: ${downCount} (${(downCount/results.length*100).toFixed(1)}%)`)
console.log(`平均涨幅: ${(avgChange/results.length).toFixed(2)}%`)
console.log(`最大涨幅: ${results[0]?.todayChange.toFixed(2)}% (${results[0]?.code} ${results[0]?.name})`)
console.log(`最大跌幅: ${results[results.length-1]?.todayChange.toFixed(2)}% (${results[results.length-1]?.code} ${results[results.length-1]?.name})`)

// 6. 输出股票代码列表
console.log('\n📝 股票代码列表:')
console.log(results.map(r => r.code).join(', '))