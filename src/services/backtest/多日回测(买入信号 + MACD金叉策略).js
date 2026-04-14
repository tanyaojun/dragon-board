// ========== 多日回测：买入信号 + MACD金叉策略 ==========

// 1. 获取所有半小时快照
const allDates = await dataLayer.getSnapshotDates()
const halfHourSnapshots = []

for (const date of allDates) {
  const snapshot = await dataLayer.getSnapshotFromDB(date)
  if (snapshot?.type === 'half_hour') {
    halfHourSnapshots.push({ date, timestamp: snapshot.timestamp, snapshot })
  }
}
halfHourSnapshots.sort((a, b) => a.timestamp - b.timestamp)

console.log('总快照数:', halfHourSnapshots.length)

// 2. 获取每天15:30的快照（收盘快照）
const dailyCloseSnapshots = []
const snapshotMap = new Map() // date -> snapshot

for (const item of halfHourSnapshots) {
  const d = new Date(item.timestamp)
  if (d.getHours() === 15 && d.getMinutes() === 30) {
    dailyCloseSnapshots.push(item)
    snapshotMap.set(item.date, item.snapshot)
  }
}

console.log('收盘快照数:', dailyCloseSnapshots.length)
console.log('日期范围:', dailyCloseSnapshots[0]?.date, '~', dailyCloseSnapshots[dailyCloseSnapshots.length-1]?.date)

// 3. 回测参数
const RESULTS = []

// 4. 对每个收盘快照进行回测
for (let i = 0; i < dailyCloseSnapshots.length - 1; i++) {
  const current = dailyCloseSnapshots[i]
  const next = dailyCloseSnapshots[i + 1]
  
  const currentDate = current.date
  const nextDate = next.date
  const currentSnapshot = current.snapshot
  const nextSnapshot = next.snapshot
  
  // 从当前快照中筛选买入信号 + MACD金叉的股票
  const hotlist = currentSnapshot?.hotlist || []
  const buySignals = []
  
  for (const stock of hotlist) {
    const signals = stock.signals || {}
    const finalSignal = signals.final?.signal
    const macdCross = stock.macdCross
    
    if (finalSignal === 'buy' && macdCross === 'golden') {
      buySignals.push({
        code: stock.code,
        name: stock.name,
        rank: stock.rank,
        change: stock.change,
        confidence: Math.round(signals.final?.confidence || 0)
      })
    }
  }
  
  if (buySignals.length === 0) continue
  
  // 获取下一个交易日这些股票的表现
  const nextHotlist = nextSnapshot?.hotlist || []
  const nextMap = new Map()
  nextHotlist.forEach((s, idx) => {
    nextMap.set(s.code, { rank: idx + 1, change: s.change })
  })
  
  // 计算表现
  let upCount = 0
  let downCount = 0
  let totalChange = 0
  const dayResults = []
  
  for (const stock of buySignals) {
    const next = nextMap.get(stock.code)
    let todayChange = 0
    let todayRank = 999
    
    if (next) {
      todayChange = next.change || 0
      todayRank = next.rank
    }
    
    if (todayChange > 0) upCount++
    else if (todayChange < 0) downCount++
    totalChange += todayChange
    
    dayResults.push({
      code: stock.code,
      name: stock.name,
      yesterdayChange: stock.change,
      yesterdayRank: stock.rank,
      todayChange: todayChange,
      todayRank: todayRank,
      confidence: stock.confidence
    })
  }
  
  const avgChange = totalChange / buySignals.length
  const winRate = (upCount / buySignals.length) * 100
  
  RESULTS.push({
    date: currentDate,
    nextDate: nextDate,
    signalCount: buySignals.length,
    upCount,
    downCount,
    winRate: winRate.toFixed(1),
    avgChange: avgChange.toFixed(2),
    stocks: dayResults.sort((a, b) => b.todayChange - a.todayChange)
  })
}

// 5. 输出每日结果
console.log('\n' + '='.repeat(100))
console.log('📊 多日回测结果 - 买入信号+MACD金叉策略')
console.log('='.repeat(100))

let totalSignals = 0
let totalUp = 0
let totalDown = 0
let totalChangeSum = 0

for (const day of RESULTS) {
  console.log(`\n📅 ${day.date} → ${day.nextDate}`)
  console.log(`   信号股票: ${day.signalCount}只`)
  console.log(`   上涨: ${day.upCount}只 (${day.winRate}%)`)
  console.log(`   下跌: ${day.downCount}只`)
  console.log(`   平均涨幅: ${day.avgChange}%`)
  
  // 显示前3只表现最好的股票
  if (day.stocks.length > 0) {
    console.log(`   最佳表现:`)
    day.stocks.slice(0, 3).forEach(s => {
      const changeStr = s.todayChange > 0 ? `+${s.todayChange}%` : `${s.todayChange}%`
      console.log(`     ${s.code} ${s.name}: 昨日${s.yesterdayChange}% → 今日${changeStr}`)
    })
  }
  
  totalSignals += day.signalCount
  totalUp += day.upCount
  totalDown += day.downCount
  totalChangeSum += parseFloat(day.avgChange) * day.signalCount
}

// 6. 总体统计
const overallWinRate = (totalUp / totalSignals) * 100
const overallAvgChange = totalChangeSum / totalSignals

console.log('\n' + '='.repeat(100))
console.log('📈 总体统计')
console.log('='.repeat(100))
console.log(`回测天数: ${RESULTS.length}天`)
console.log(`总信号数量: ${totalSignals}个`)
console.log(`上涨次数: ${totalUp}次 (${overallWinRate.toFixed(1)}%)`)
console.log(`下跌次数: ${totalDown}次 (${(100 - overallWinRate).toFixed(1)}%)`)
console.log(`平均涨幅: ${overallAvgChange.toFixed(2)}%`)

// 7. 输出所有信号股票代码（用于验证）
console.log('\n' + '='.repeat(100))
console.log('📝 所有信号股票列表（按日期）')
console.log('='.repeat(100))

for (const day of RESULTS) {
  console.log(`\n${day.date}:`)
  console.log(day.stocks.map(s => `${s.code}(${s.todayChange>0?'+':''}${s.todayChange}%)`).join(', '))
}

// 8. 计算策略收益曲线（累计收益）
let cumulativeReturn = 0
console.log('\n' + '='.repeat(100))
console.log('📈 策略收益曲线（等权买入）')
console.log('='.repeat(100))

for (const day of RESULTS) {
  const dayReturn = parseFloat(day.avgChange)
  cumulativeReturn += dayReturn
  console.log(`${day.date}: +${dayReturn}% → 累计: ${cumulativeReturn.toFixed(2)}%`)
}

console.log(`\n累计收益率: ${cumulativeReturn.toFixed(2)}%`)
console.log(`平均每交易日收益: ${(cumulativeReturn / RESULTS.length).toFixed(2)}%`)