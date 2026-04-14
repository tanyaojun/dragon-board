// src/services/dragon/ContextBuilder.ts

/**
 * 构建市场上下文
 */
export function buildMarketContext(): MarketContext {
  const stocks = window.allData?.merged || []
  const breath = dragonBreathAnalyzer.getMarketData?.()
  
  // 计算连板分布
  const limitDist = {
    yiban: 0, erban: 0, sanban: 0, sibanPlus: 0
  }
  
  stocks.forEach(s => {
    if (s.change > 9.5) {
      if (s.continuousDays === 1) limitDist.yiban++
      else if (s.continuousDays === 2) limitDist.erban++
      else if (s.continuousDays === 3) limitDist.sanban++
      else if (s.continuousDays >= 4) limitDist.sibanPlus++
    }
  })
  
  // 计算晋级率
  const passRate = limitDist.erban > 0 
    ? (limitDist.sanban / limitDist.erban) * 100 
    : 0
  
  return {
    marketPhase: breath?.phase || '震荡期',
    marketSentiment: breath?.overall || 50,
    upCount: stocks.filter(s => s.change > 0).length,
    downCount: stocks.filter(s => s.change < 0).length,
    totalZtCount: stocks.filter(s => s.change > 9.5).length,
    limitDistribution: limitDist,
    passRate,
    zhabanRate: breath?.zhabanRate || 0,
    fengbanRate: breath?.fengbanRate || 0,
    mainInflow: stocks.reduce((sum, s) => sum + (s.zlje || 0), 0),
    turnoverTop10: stocks
      .sort((a, b) => b.turnover - a.turnover)
      .slice(0, 10)
      .reduce((sum, s) => sum + s.turnover, 0)
  }
}

/**
 * 构建题材上下文
 */
export function buildSectorContext(themeName: string): SectorContext {
  const sectorInfo = sectorAnalyzer.getThemeDetail?.(themeName)
  const stocks = window.allData?.merged || []
  
  // 找出该题材的所有股票
  const sectorStocks = stocks.filter(s => 
    s.themes?.some(t => t.name === themeName)
  )
  
  // 找出涨停股
  const ztStocks = sectorStocks.filter(s => s.change > 9.5)
  
  // 找出最先涨停的
  const sortedByTime = [...ztStocks].sort((a, b) => 
    (a.limitTime || '9999') < (b.limitTime || '9999') ? -1 : 1
  )
  
  // 找出封单最大的
  const sortedByFengdan = [...ztStocks].sort((a, b) => 
    (b.fengdan || 0) - (a.fengdan || 0)
  )
  
  return {
    sectorName: themeName,
    sectorHeat: sectorInfo?.heatScore || 0,
    sectorMomentum: sectorInfo?.momentum || 0,
    sectorZtCount: ztStocks.length,
    sectorLeaderCount: sectorInfo?.leaders?.length || 0,
    firstLimitTime: sortedByTime[0]?.limitTime || '无',
    firstLimitCode: sortedByTime[0]?.code || '',
    maxFengdan: sortedByFengdan[0]?.fengdan || 0,
    maxFengdanCode: sortedByFengdan[0]?.code || '',
    followerCodes: ztStocks.slice(1).map(s => s.code),
    ztIncrease: 0  // 需要对比昨日数据
  }
}

/**
 * 构建个股上下文
 */
export function buildStockContext(stock: Stock): StockContext {
  // 计算均线（需要历史数据）
  const history = stock.history || []
  const closes = history.map(h => h.close)
  
  const ma5 = closes.length >= 5 
    ? closes.slice(-5).reduce((a, b) => a + b, 0) / 5 
    : stock.price
  
  const ma10 = closes.length >= 10
    ? closes.slice(-10).reduce((a, b) => a + b, 0) / 10
    : stock.price
  
  const ma20 = closes.length >= 20
    ? closes.slice(-20).reduce((a, b) => a + b, 0) / 20
    : stock.price
  
  // 提取属性标签
  const attributes: string[] = []
  if (stock.totalMV < 30e8) attributes.push('小盘')
  if (stock.totalMV < 10e8) attributes.push('微盘')
  if (stock.price < 10) attributes.push('低价')
  if (stock.volumeRatio > 2) attributes.push('放量')
  if (stock.ipoDate && (Date.now() - stock.ipoDate) < 180 * 24 * 60 * 60 * 1000) {
    attributes.push('次新')
  }
  
  return {
    code: stock.code,
    name: stock.name,
    ma5,
    ma10,
    ma20,
    volumeRatio: stock.volumeRatio || 1,
    turnoverRate: stock.turnoverRate || 0,
    fengdan: stock.fengdan || 0,
    zlje: stock.zlje || 0,
    longhu: stock.longhu || [],
    themes: stock.themes?.map(t => ({
      name: typeof t === 'string' ? t : t.name,
      heat: t.heatScore || 0,
      rank: t.rank || 999
    })) || [],
    attributes,
    limitTime: stock.limitTime,
    limitType: stock.limitType,
    limitDays: stock.continuousDays || 1,
    turnoverRank: stock.turnoverRank || 999,
    totalMV: stock.totalMV || 0,
    compRank: stock.compRank || 999,
    change: stock.change || 0
  }
}