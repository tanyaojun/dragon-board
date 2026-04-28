// src/services/backtest/RotationBacktest.ts

import { dataLayer } from '@/services/DataLayer'
import { rotationService } from '@/services/rotationService'
import type { RotationAnalysis, ThemeRotationStatus } from '@/types/core'

// ========== 类型定义 ==========

export interface BacktestTrade {
  date: string
  sector: string
  leaderCode: string
  leaderName: string
  leaderLevel: string
  action: 'buy' | 'sell'
  price: number
  quantity: number
  returnRate: number
  reason: string
  rotationSpeed: number
  marketPhase: string
}

export interface BacktestResult {
  strategyName: string
  totalReturn: number
  annualizedReturn: number
  winRate: number
  avgWin: number
  avgLoss: number
  maxDrawdown: number
  sharpeRatio: number
  tradeCount: number
  winCount: number
  lossCount: number
  equityCurve: { date: string; equity: number }[]
  monthlyReturns: { month: string; return: number }[]
  trades: BacktestTrade[]
  sectorStats: { sector: string; trades: number; winRate: number; avgReturn: number }[]
  leaderStats: { level: string; trades: number; winRate: number; avgReturn: number }[]
}

export interface StrategyParams {
  // 策略选择
  strategy: 'chase' | 'mainline' | 'rotation_speed' | 'market_phase'
  
  // 通用参数
  holdDays: number
  stopLoss: number
  takeProfit: number
  initialCapital: number
  
  // 追涨策略参数
  minRankChange?: number      // 排名上升阈值（负值，如-5）
  minStrengthScore?: number   // 最小强度分数
  maxRotationSpeed?: number   // 最大轮动速度
  
  // 主线策略参数
  minPersistentDays?: number  // 最小持续天数
  
  // 轮动速度策略参数
  buySpeed?: number           // 买入速度阈值
  sellSpeed?: number          // 卖出速度阈值
}

// ========== 回测引擎 ==========

export class RotationBacktest {
  private snapshots: any[]
  private rotationHistory: RotationAnalysis[]
  private priceCache: Map<string, Map<string, number>> = new Map()

  constructor() {
    this.snapshots = []
    this.rotationHistory = []
  }

  /**
   * 加载数据
   */
  async loadData() {
    const records = await dataLayer.listSnapshots({ sort: 'asc' })
    this.snapshots = records.map((record) => {
      const payload = record.payload || {}
      return {
        ...payload,
        id: record.id,
        date: record.displayKey || record.id,
        tradingDate: record.tradingDate,
        slotTime: record.slotTime,
        timestamp: record.timestamp,
        type: record.type,
        hotlist: Array.isArray(payload.hotlist) ? payload.hotlist : [],
      }
    })
    this.rotationHistory = await dataLayer.getRotationHistory() || []
    
    this.buildPriceCache()
    console.log(`[Backtest] 加载完成: ${this.snapshots.length} 个快照, ${this.rotationHistory.length} 个轮动数据`)
  }

  private buildPriceCache() {
    for (const snapshot of this.snapshots) {
      for (const stock of snapshot.hotlist || []) {
        if (!this.priceCache.has(stock.code)) {
          this.priceCache.set(stock.code, new Map())
        }
        this.priceCache.get(stock.code)!.set(snapshot.date, stock.price)
      }
    }
  }

  private getStockPrice(code: string, date: string): number | null {
    return this.priceCache.get(code)?.get(date) || null
  }

  private getSectorLeader(snapshot: any, sectorName: string): any | null {
    const jxbkStocks = snapshot.jxbkStocks || {}
    const leaders = Object.values(jxbkStocks).filter((s: any) =>
      s.blocks?.includes(sectorName) && s.leadStatus?.includes('龙')
    )
    
    // 按龙一 > 龙二 > 龙三排序
    const order = { '龙一': 1, '龙二': 2, '龙三': 3 }
    leaders.sort((a: any, b: any) => 
      (order[a.leadStatus] || 99) - (order[b.leadStatus] || 99)
    )
    
    return leaders[0] || null
  }

  /**
   * 策略1：追涨杀跌 - 买入排名快速上升的板块龙头
   */
  async runChaseStrategy(params: StrategyParams): Promise<BacktestResult> {
    const trades: BacktestTrade[] = []
    const equityCurve: { date: string; equity: number }[] = []
    let equity = params.initialCapital
    let position: BacktestTrade | null = null
    let holdDays = 0

    for (let i = 0; i < this.rotationHistory.length - 1; i++) {
      const rotation = this.rotationHistory[i]
      const today = this.snapshots[i]
      const tomorrow = this.snapshots[i + 1]
      
      if (!rotation || !today) continue

      // ========== 检查持仓 ==========
      if (position) {
        holdDays++
        const sellPrice = this.getStockPrice(position.leaderCode, tomorrow.date)
        
        if (sellPrice) {
          const returnRate = ((sellPrice - position.price) / position.price) * 100
          
          if (returnRate <= params.stopLoss || returnRate >= params.takeProfit || holdDays >= params.holdDays) {
            equity = equity * (1 + returnRate / 100)
            trades.push({
              ...position,
              date: tomorrow.date,
              action: 'sell',
              price: sellPrice,
              returnRate,
              reason: returnRate <= params.stopLoss ? '止损' : returnRate >= params.takeProfit ? '止盈' : `持有${holdDays}天`
            })
            position = null
            holdDays = 0
          }
        }
      }

      // ========== 买入信号 ==========
      if (!position) {
        const surging = rotation.inflowThemes.filter(s =>
          s.rankChange <= (params.minRankChange || -3) &&
          (s.strengthScore || 0) >= (params.minStrengthScore || 50) &&
          rotation.rotationSpeed <= (params.maxRotationSpeed || 70)
        )
        
        if (surging.length > 0) {
          surging.sort((a, b) => a.rankChange - b.rankChange)
          const target = surging[0]
          const leader = this.getSectorLeader(today, target.themeName)
          
          if (leader) {
            const buyPrice = this.getStockPrice(leader.code, today.date)
            if (buyPrice) {
              position = {
                date: today.date,
                sector: target.themeName,
                leaderCode: leader.code,
                leaderName: leader.name,
                leaderLevel: leader.leadStatus,
                action: 'buy',
                price: buyPrice,
                quantity: equity / buyPrice,
                returnRate: 0,
                reason: `资金涌入 (排名↑${-target.rankChange})`,
                rotationSpeed: rotation.rotationSpeed,
                marketPhase: rotation.marketPhase
              }
              trades.push(position)
            }
          }
        }
      }
      
      let totalValue = equity
      if (position) {
        const currentPrice = this.getStockPrice(position.leaderCode, tomorrow.date)
        if (currentPrice) {
          totalValue = equity * (currentPrice / position.price)
        }
      }
      equityCurve.push({ date: tomorrow.date, equity: totalValue })
    }

    return this.calculateResults('追涨杀跌策略', trades, equityCurve)
  }

  /**
   * 策略2：主线龙头 - 买入持续主线的龙一
   */
  async runMainlineStrategy(params: StrategyParams): Promise<BacktestResult> {
    const trades: BacktestTrade[] = []
    const equityCurve: { date: string; equity: number }[] = []
    let equity = params.initialCapital
    let position: BacktestTrade | null = null
    let holdDays = 0

    for (let i = 0; i < this.rotationHistory.length - 1; i++) {
      const rotation = this.rotationHistory[i]
      const today = this.snapshots[i]
      const tomorrow = this.snapshots[i + 1]
      
      if (!rotation || !today) continue

      if (position) {
        holdDays++
        const sellPrice = this.getStockPrice(position.leaderCode, tomorrow.date)
        
        if (sellPrice) {
          const returnRate = ((sellPrice - position.price) / position.price) * 100
          const stillMainline = rotation.mainLines.some(m => m.themeName === position.sector)
          
          if (!stillMainline || returnRate <= params.stopLoss || returnRate >= params.takeProfit || holdDays >= params.holdDays) {
            equity = equity * (1 + returnRate / 100)
            trades.push({
              ...position,
              date: tomorrow.date,
              action: 'sell',
              price: sellPrice,
              returnRate,
              reason: !stillMainline ? '板块掉出主线' : (returnRate <= params.stopLoss ? '止损' : returnRate >= params.takeProfit ? '止盈' : `持有${holdDays}天`)
            })
            position = null
            holdDays = 0
          }
        }
      }

      if (!position) {
        const mainline = rotation.mainLines.find(m => m.persistentDays >= (params.minPersistentDays || 3))
        
        if (mainline) {
          const leader = this.getSectorLeader(today, mainline.themeName)
          
          if (leader) {
            const buyPrice = this.getStockPrice(leader.code, today.date)
            if (buyPrice) {
              position = {
                date: today.date,
                sector: mainline.themeName,
                leaderCode: leader.code,
                leaderName: leader.name,
                leaderLevel: leader.leadStatus,
                action: 'buy',
                price: buyPrice,
                quantity: equity / buyPrice,
                returnRate: 0,
                reason: `主线板块 (持续${mainline.persistentDays}天)`,
                rotationSpeed: rotation.rotationSpeed,
                marketPhase: rotation.marketPhase
              }
              trades.push(position)
            }
          }
        }
      }
      
      let totalValue = equity
      if (position) {
        const currentPrice = this.getStockPrice(position.leaderCode, tomorrow.date)
        if (currentPrice) {
          totalValue = equity * (currentPrice / position.price)
        }
      }
      equityCurve.push({ date: tomorrow.date, equity: totalValue })
    }

    return this.calculateResults('主线龙头策略', trades, equityCurve)
  }

  /**
   * 策略3：轮动速度择时
   */
  async runRotationSpeedStrategy(params: StrategyParams): Promise<BacktestResult> {
    const trades: BacktestTrade[] = []
    const equityCurve: { date: string; equity: number }[] = []
    let equity = params.initialCapital
    let inMarket = false
    let buyDate = ''
    let buyPrice = 0
    let buyIndex = 0

    for (let i = 0; i < this.rotationHistory.length - 1; i++) {
      const rotation = this.rotationHistory[i]
      const tomorrow = this.snapshots[i + 1]
      const speed = rotation.rotationSpeed
      
      if (!inMarket && speed <= (params.buySpeed || 30)) {
        // 买入信号：轮动慢速，买市场指数
        inMarket = true
        buyDate = tomorrow.date
        buyPrice = 1
        buyIndex = i
        trades.push({
          date: buyDate,
          sector: '市场',
          leaderCode: 'INDEX',
          leaderName: '市场指数',
          leaderLevel: '',
          action: 'buy',
          price: 1,
          quantity: equity,
          returnRate: 0,
          reason: `轮动慢速 ${speed}%`,
          rotationSpeed: speed,
          marketPhase: rotation.marketPhase
        })
      } else if (inMarket && (speed >= (params.sellSpeed || 60) || i - buyIndex >= params.holdDays)) {
        // 卖出信号
        const returnRate = 0 // 简化，实际用指数收益
        equity = equity * (1 + returnRate / 100)
        trades.push({
          date: tomorrow.date,
          sector: '市场',
          leaderCode: 'INDEX',
          leaderName: '市场指数',
          leaderLevel: '',
          action: 'sell',
          price: 1,
          quantity: equity,
          returnRate,
          reason: speed >= (params.sellSpeed || 60) ? `轮动快速 ${speed}%` : `持有${i - buyIndex}天`,
          rotationSpeed: speed,
          marketPhase: rotation.marketPhase
        })
        inMarket = false
      }
      
      equityCurve.push({ date: tomorrow.date, equity })
    }

    return this.calculateResults('轮动速度择时策略', trades, equityCurve)
  }

  /**
   * 策略4：市场阶段策略
   */
  async runMarketPhaseStrategy(params: StrategyParams): Promise<BacktestResult> {
    const trades: BacktestTrade[] = []
    const equityCurve: { date: string; equity: number }[] = []
    let equity = params.initialCapital
    let inMarket = false
    let buyDate = ''
    let buyPrice = 0

    for (let i = 0; i < this.rotationHistory.length - 1; i++) {
      const rotation = this.rotationHistory[i]
      const tomorrow = this.snapshots[i + 1]
      const phase = rotation.marketPhase
      
      const isBuyPhase = phase === 'rising' || phase === 'climax'
      const isSellPhase = phase === 'ice' || phase === 'falling'
      
      if (!inMarket && isBuyPhase) {
        inMarket = true
        buyDate = tomorrow.date
        buyPrice = 1
        trades.push({
          date: buyDate,
          sector: '市场',
          leaderCode: 'INDEX',
          leaderName: '市场指数',
          leaderLevel: '',
          action: 'buy',
          price: 1,
          quantity: equity,
          returnRate: 0,
          reason: `${phase === 'rising' ? '上升期' : '高潮期'}，进攻`,
          rotationSpeed: rotation.rotationSpeed,
          marketPhase: phase
        })
      } else if (inMarket && isSellPhase) {
        const returnRate = 0
        equity = equity * (1 + returnRate / 100)
        trades.push({
          date: tomorrow.date,
          sector: '市场',
          leaderCode: 'INDEX',
          leaderName: '市场指数',
          leaderLevel: '',
          action: 'sell',
          price: 1,
          quantity: equity,
          returnRate,
          reason: phase === 'ice' ? '冰点期，空仓' : '退潮期，空仓',
          rotationSpeed: rotation.rotationSpeed,
          marketPhase: phase
        })
        inMarket = false
      }
      
      equityCurve.push({ date: tomorrow.date, equity })
    }

    return this.calculateResults('市场阶段策略', trades, equityCurve)
  }

  /**
   * 运行指定策略
   */
  async run(params: StrategyParams): Promise<BacktestResult> {
    await this.loadData()
    
    switch (params.strategy) {
      case 'chase':
        return this.runChaseStrategy(params)
      case 'mainline':
        return this.runMainlineStrategy(params)
      case 'rotation_speed':
        return this.runRotationSpeedStrategy(params)
      case 'market_phase':
        return this.runMarketPhaseStrategy(params)
      default:
        throw new Error(`Unknown strategy: ${params.strategy}`)
    }
  }

  private calculateResults(name: string, trades: BacktestTrade[], equityCurve: { date: string; equity: number }[]): BacktestResult {
    const finalEquity = equityCurve[equityCurve.length - 1]?.equity || 100000
    const totalReturn = ((finalEquity - 100000) / 100000) * 100
    const years = (equityCurve.length / 252) || 1
    const annualizedReturn = Math.pow(1 + totalReturn / 100, 1 / years) - 1
    
    const sellTrades = trades.filter(t => t.action === 'sell')
    const winTrades = sellTrades.filter(t => t.returnRate > 0)
    const lossTrades = sellTrades.filter(t => t.returnRate < 0)
    
    const winRate = sellTrades.length > 0 ? (winTrades.length / sellTrades.length) * 100 : 0
    const avgWin = winTrades.length > 0 ? winTrades.reduce((s, t) => s + t.returnRate, 0) / winTrades.length : 0
    const avgLoss = lossTrades.length > 0 ? lossTrades.reduce((s, t) => s + t.returnRate, 0) / lossTrades.length : 0
    
    let maxDrawdown = 0
    let peak = equityCurve[0]?.equity || 100000
    for (const point of equityCurve) {
      if (point.equity > peak) peak = point.equity
      const drawdown = ((peak - point.equity) / peak) * 100
      if (drawdown > maxDrawdown) maxDrawdown = drawdown
    }
    
    const dailyReturns: number[] = []
    for (let i = 1; i < equityCurve.length; i++) {
      dailyReturns.push(((equityCurve[i].equity - equityCurve[i-1].equity) / equityCurve[i-1].equity) * 100)
    }
    const avgReturn = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length
    const variance = dailyReturns.reduce((sum, r) => sum + Math.pow(r - avgReturn, 2), 0) / dailyReturns.length
    const stdDev = Math.sqrt(variance)
    const sharpeRatio = stdDev > 0 ? (avgReturn / stdDev) * Math.sqrt(252) : 0
    
    const sectorStatsMap = new Map<string, { trades: number; wins: number; totalReturn: number }>()
    for (const trade of sellTrades) {
      const stats = sectorStatsMap.get(trade.sector) || { trades: 0, wins: 0, totalReturn: 0 }
      stats.trades++
      if (trade.returnRate > 0) stats.wins++
      stats.totalReturn += trade.returnRate
      sectorStatsMap.set(trade.sector, stats)
    }
    const sectorStats = Array.from(sectorStatsMap.entries()).map(([sector, stats]) => ({
      sector,
      trades: stats.trades,
      winRate: (stats.wins / stats.trades) * 100,
      avgReturn: stats.totalReturn / stats.trades
    })).sort((a, b) => b.avgReturn - a.avgReturn)
    
    const leaderStatsMap = new Map<string, { trades: number; wins: number; totalReturn: number }>()
    for (const trade of sellTrades) {
      const level = trade.leaderLevel || '普通'
      const stats = leaderStatsMap.get(level) || { trades: 0, wins: 0, totalReturn: 0 }
      stats.trades++
      if (trade.returnRate > 0) stats.wins++
      stats.totalReturn += trade.returnRate
      leaderStatsMap.set(level, stats)
    }
    const leaderStats = Array.from(leaderStatsMap.entries()).map(([level, stats]) => ({
      level,
      trades: stats.trades,
      winRate: (stats.wins / stats.trades) * 100,
      avgReturn: stats.totalReturn / stats.trades
    })).sort((a, b) => b.avgReturn - a.avgReturn)
    
    const monthMap = new Map<string, { start: number; end: number }>()
    for (const point of equityCurve) {
      const month = point.date.slice(0, 7)
      if (!monthMap.has(month)) {
        monthMap.set(month, { start: point.equity, end: point.equity })
      } else {
        monthMap.get(month)!.end = point.equity
      }
    }
    const monthlyReturns = Array.from(monthMap.entries()).map(([month, { start, end }]) => ({
      month,
      return: ((end - start) / start) * 100
    })).sort((a, b) => a.month.localeCompare(b.month))
    
    return {
      strategyName: name,
      totalReturn,
      annualizedReturn: annualizedReturn * 100,
      winRate,
      avgWin,
      avgLoss,
      maxDrawdown,
      sharpeRatio,
      tradeCount: sellTrades.length,
      winCount: winTrades.length,
      lossCount: lossTrades.length,
      equityCurve,
      monthlyReturns,
      trades,
      sectorStats,
      leaderStats
    }
  }
}
