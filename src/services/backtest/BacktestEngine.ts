// src/services/backtest/BacktestEngine.ts
// 回测引擎核心类 - 用于验证RankTrendAnalyzer信号胜率

import { dataLayer } from '../DataLayer'
import type { MergedStock } from '../DataLayer'

/**
 * 回测配置
 */
export interface BacktestConfig {
  // 时间范围
  startDate?: string // YYYY-MM-DD格式
  endDate?: string // YYYY-MM-DD格式

  // 信号配置
  signalTypes: Array<'direction' | 'acceleration' | 'cross' | 'final'>
  confidenceThreshold: number // 置信度阈值

  // 交易配置
  initialCapital: number // 初始资金
  positionSize: number // 每笔交易仓位比例 (0-1)
  maxPositions: number // 最大持仓数量
  transactionCost: number // 交易成本（百分比）

  // 止损止盈
  stopLoss: number // 止损比例（百分比）
  takeProfit: number // 止盈比例（百分比）
  holdPeriod: number // 持有期（分钟）

  // 过滤条件
  minRank: number // 最小排名（只交易前N名）
  minVolume: number // 最小成交量
  minTurnover: number // 最小成交额
}

/**
 * 交易信号
 */
export interface TradeSignal {
  timestamp: number
  code: string
  name: string
  signalType: 'direction' | 'acceleration' | 'cross' | 'final'
  signal: 'buy' | 'sell' | 'hold'
  confidence: number
  price: number
  rank: number
  technicalIndicators?: any
}

/**
 * 交易记录
 */
export interface TradeRecord {
  id: string
  entryTime: number
  exitTime: number
  code: string
  name: string
  entryPrice: number
  exitPrice: number
  quantity: number
  positionSize: number
  signalType: string
  pnl: number
  pnlPercent: number
  holdTime: number // 持有时间（分钟）
  status: 'win' | 'loss' | 'breakeven'
  stopLossHit: boolean
  takeProfitHit: boolean
}

/**
 * 回测结果
 */
export interface BacktestResult {
  // 基本统计
  totalTrades: number
  winningTrades: number
  losingTrades: number
  breakevenTrades: number

  // 绩效指标
  winRate: number
  totalPnl: number
  totalReturn: number
  averageWin: number
  averageLoss: number
  profitFactor: number
  maxDrawdown: number
  sharpeRatio: number

  // 按信号类型统计
  bySignalType: Record<
    string,
    {
      trades: number
      wins: number
      losses: number
      winRate: number
      totalPnl: number
      averagePnl: number
    }
  >

  // 详细记录
  trades: TradeRecord[]
  signals: TradeSignal[]

  // 配置
  config: BacktestConfig
  startDate: string
  endDate: string
  duration: number // 回测时长（天）
}

/**
 * 回测引擎
 */
export class BacktestEngine {
  private config: BacktestConfig

  constructor(config?: Partial<BacktestConfig>) {
    this.config = {
      signalTypes: ['direction', 'acceleration', 'cross', 'final'],
      confidenceThreshold: 70,
      initialCapital: 100000,
      positionSize: 0.1,
      maxPositions: 10,
      transactionCost: 0.001,
      stopLoss: 0.05,
      takeProfit: 0.1,
      holdPeriod: 60,
      minRank: 100,
      minVolume: 1000000,
      minTurnover: 10000000,
      ...config,
    }
  }

  /**
   * 运行回测
   */
  async runBacktest(): Promise<BacktestResult> {
    console.log('[BacktestEngine] 开始回测...')

    // 1. 加载历史快照
    const snapshots = await this.loadHistoricalSnapshots()
    if (snapshots.length === 0) {
      throw new Error('没有找到历史快照数据')
    }

    console.log(`[BacktestEngine] 加载了 ${snapshots.length} 个快照`)

    // 2. 提取交易信号
    const signals = this.extractSignals(snapshots)
    console.log(`[BacktestEngine] 提取了 ${signals.length} 个交易信号`)

    // 3. 模拟交易
    const trades = this.simulateTrading(signals, snapshots)
    console.log(`[BacktestEngine] 模拟了 ${trades.length} 笔交易`)

    // 4. 计算绩效
    const result = this.calculatePerformance(trades, signals)

    console.log('[BacktestEngine] 回测完成')
    return result
  }

  /**
   * 加载历史快照
   */
  private async loadHistoricalSnapshots(): Promise<any[]> {
    const records = await dataLayer.listSnapshots({ sort: 'desc' })
    const snapshots = records
      .filter((record) => {
        const dateStr = record.tradingDate || ''
        if (this.config.startDate && dateStr < this.config.startDate) return false
        if (this.config.endDate && dateStr > this.config.endDate) return false
        return true
      })
      .map((record) => {
        const payload = record.payload || {}
        return {
          ...payload,
          originalKey: record.id,
          date: record.displayKey || record.id,
          dateStr: record.tradingDate,
          timeStr: record.slotTime || '00:00',
          type: record.type,
          timestamp: record.timestamp || Date.parse(`${record.tradingDate}T${record.slotTime || '00:00'}:00`),
          hotlist: Array.isArray(payload.hotlist) ? payload.hotlist : [],
          metadata: payload.metadata || null,
        }
      })

    // 按时间排序
    snapshots.sort((a, b) => a.timestamp - b.timestamp)

    return snapshots
  }

  /**
   * 提取交易信号
   */
  private extractSignals(snapshots: any[]): TradeSignal[] {
    const signals: TradeSignal[] = []

    for (const snapshot of snapshots) {
      // 只处理v2.0格式的快照
      if (!snapshot.metadata || snapshot.metadata.version !== '2.0') {
        continue
      }

      const hotlist = snapshot.hotlist || []

      for (const stock of hotlist) {
        // 过滤条件
        if (stock.rank > this.config.minRank) continue
        if (stock.volume < this.config.minVolume) continue
        if (stock.turnover < this.config.minTurnover) continue

        // 检查每个信号类型
        for (const signalType of this.config.signalTypes) {
          const signalData = stock.signals?.[signalType]
          if (!signalData) continue

          const { signal, confidence } = signalData

          // 过滤置信度
          if (confidence < this.config.confidenceThreshold) continue

          // 只处理买入信号
          if (signal !== 'buy') continue

          signals.push({
            timestamp: snapshot.timestamp,
            code: stock.code,
            name: stock.name,
            signalType,
            signal,
            confidence,
            price: stock.price,
            rank: stock.rank,
            technicalIndicators: stock.technicalIndicators,
          })
        }
      }
    }

    return signals
  }

  /**
   * 模拟交易
   */
  private simulateTrading(signals: TradeSignal[], snapshots: any[]): TradeRecord[] {
    const trades: TradeRecord[] = []
    let capital = this.config.initialCapital
    const positions = new Map<string, TradeRecord>() // code -> 持仓记录

    // 按时间顺序处理信号
    const sortedSignals = [...signals].sort((a, b) => a.timestamp - b.timestamp)

    for (const signal of sortedSignals) {
      // 检查是否已有持仓
      if (positions.has(signal.code)) {
        // 检查是否需要平仓（持有期结束）
        const position = positions.get(signal.code)!
        const holdTime = (signal.timestamp - position.entryTime) / (1000 * 60) // 分钟

        if (holdTime >= this.config.holdPeriod) {
          // 平仓
          const exitPrice = this.findExitPrice(signal.code, signal.timestamp, snapshots)
          const trade = this.closePosition(position, exitPrice, signal.timestamp)
          trades.push(trade)
          positions.delete(signal.code)
          capital += trade.pnl
        }
        continue
      }

      // 检查持仓数量限制
      if (positions.size >= this.config.maxPositions) {
        continue
      }

      // 开仓
      const positionSize = capital * this.config.positionSize
      const quantity = Math.floor(positionSize / signal.price)

      if (quantity <= 0) continue

      const trade: TradeRecord = {
        id: `${signal.code}_${signal.timestamp}`,
        entryTime: signal.timestamp,
        exitTime: 0,
        code: signal.code,
        name: signal.name,
        entryPrice: signal.price,
        exitPrice: 0,
        quantity,
        positionSize: positionSize,
        signalType: signal.signalType,
        pnl: 0,
        pnlPercent: 0,
        holdTime: 0,
        status: 'breakeven',
        stopLossHit: false,
        takeProfitHit: false,
      }

      positions.set(signal.code, trade)
      capital -= positionSize
    }

    // 平掉所有剩余持仓（使用最后一个快照的价格）
    if (snapshots.length > 0) {
      const lastSnapshot = snapshots[snapshots.length - 1]
      const lastTimestamp = lastSnapshot.timestamp

      for (const [code, position] of positions.entries()) {
        const exitPrice = this.findExitPrice(code, lastTimestamp, snapshots)
        const trade = this.closePosition(position, exitPrice, lastTimestamp)
        trades.push(trade)
        capital += trade.pnl
      }
    }

    return trades
  }

  /**
   * 查找退出价格
   */
  private findExitPrice(code: string, timestamp: number, snapshots: any[]): number {
    // 查找指定时间之后的第一个快照
    for (const snapshot of snapshots) {
      if (snapshot.timestamp > timestamp) {
        const stock = snapshot.hotlist?.find((s: any) => s.code === code)
        if (stock && stock.price > 0) {
          return stock.price
        }
      }
    }

    // 如果找不到，使用最后一个快照的价格
    const lastSnapshot = snapshots[snapshots.length - 1]
    const lastStock = lastSnapshot.hotlist?.find((s: any) => s.code === code)
    return lastStock?.price || 0
  }

  /**
   * 平仓
   */
  private closePosition(position: TradeRecord, exitPrice: number, exitTime: number): TradeRecord {
    const holdTime = (exitTime - position.entryTime) / (1000 * 60) // 分钟

    // 计算盈亏
    const grossPnl = (exitPrice - position.entryPrice) * position.quantity
    const transactionCost =
      (position.entryPrice + exitPrice) * position.quantity * this.config.transactionCost
    const netPnl = grossPnl - transactionCost
    const pnlPercent = (netPnl / position.positionSize) * 100

    // 检查止损止盈
    const priceChangePercent = ((exitPrice - position.entryPrice) / position.entryPrice) * 100
    const stopLossHit = priceChangePercent <= -this.config.stopLoss
    const takeProfitHit = priceChangePercent >= this.config.takeProfit

    // 确定交易状态
    let status: 'win' | 'loss' | 'breakeven' = 'breakeven'
    if (netPnl > 0) status = 'win'
    else if (netPnl < 0) status = 'loss'

    return {
      ...position,
      exitTime,
      exitPrice,
      pnl: netPnl,
      pnlPercent,
      holdTime,
      status,
      stopLossHit,
      takeProfitHit,
    }
  }

  /**
   * 计算绩效
   */
  private calculatePerformance(trades: TradeRecord[], signals: TradeSignal[]): BacktestResult {
    if (trades.length === 0) {
      return this.createEmptyResult()
    }

    // 基本统计
    const winningTrades = trades.filter((t) => t.status === 'win')
    const losingTrades = trades.filter((t) => t.status === 'loss')
    const breakevenTrades = trades.filter((t) => t.status === 'breakeven')

    const totalPnl = trades.reduce((sum, t) => sum + t.pnl, 0)
    const totalReturn = (totalPnl / this.config.initialCapital) * 100

    const averageWin =
      winningTrades.length > 0
        ? winningTrades.reduce((sum, t) => sum + t.pnl, 0) / winningTrades.length
        : 0

    const averageLoss =
      losingTrades.length > 0
        ? losingTrades.reduce((sum, t) => sum + t.pnl, 0) / losingTrades.length
        : 0

    const profitFactor =
      Math.abs(averageWin * winningTrades.length) / Math.abs(averageLoss * losingTrades.length) || 0

    // 计算最大回撤
    const maxDrawdown = this.calculateMaxDrawdown(trades)

    // 按信号类型统计
    const bySignalType: Record<string, any> = {}
    for (const signalType of this.config.signalTypes) {
      const typeTrades = trades.filter((t) => t.signalType === signalType)
      const typeWins = typeTrades.filter((t) => t.status === 'win')

      bySignalType[signalType] = {
        trades: typeTrades.length,
        wins: typeWins.length,
        losses: typeTrades.length - typeWins.length,
        winRate: typeTrades.length > 0 ? (typeWins.length / typeTrades.length) * 100 : 0,
        totalPnl: typeTrades.reduce((sum, t) => sum + t.pnl, 0),
        averagePnl:
          typeTrades.length > 0
            ? typeTrades.reduce((sum, t) => sum + t.pnl, 0) / typeTrades.length
            : 0,
      }
    }

    // 计算夏普比率（简化版）
    const sharpeRatio = this.calculateSharpeRatio(trades)

    // 确定时间范围
    const timestamps = trades.map((t) => t.entryTime)
    const startTimestamp = Math.min(...timestamps)
    const endTimestamp = Math.max(...timestamps.map((t) => t.exitTime || t.entryTime))
    const duration = (endTimestamp - startTimestamp) / (1000 * 60 * 60 * 24) // 天

    return {
      totalTrades: trades.length,
      winningTrades: winningTrades.length,
      losingTrades: losingTrades.length,
      breakevenTrades: breakevenTrades.length,

      winRate: trades.length > 0 ? (winningTrades.length / trades.length) * 100 : 0,
      totalPnl,
      totalReturn,
      averageWin,
      averageLoss,
      profitFactor,
      maxDrawdown,
      sharpeRatio,

      bySignalType,
      trades,
      signals,

      config: this.config,
      startDate: new Date(startTimestamp).toISOString().split('T')[0],
      endDate: new Date(endTimestamp).toISOString().split('T')[0],
      duration,
    }
  }

  /**
   * 计算最大回撤
   */
  private calculateMaxDrawdown(trades: TradeRecord[]): number {
    if (trades.length === 0) return 0

    let peak = this.config.initialCapital
    let maxDrawdown = 0
    let currentCapital = this.config.initialCapital

    // 按时间排序的交易
    const sortedTrades = [...trades].sort((a, b) => a.entryTime - b.entryTime)

    for (const trade of sortedTrades) {
      currentCapital += trade.pnl
      peak = Math.max(peak, currentCapital)
      const drawdown = ((peak - currentCapital) / peak) * 100
      maxDrawdown = Math.max(maxDrawdown, drawdown)
    }

    return maxDrawdown
  }

  /**
   * 计算夏普比率（简化版）
   */
  private calculateSharpeRatio(trades: TradeRecord[]): number {
    if (trades.length < 2) return 0

    const returns = trades.map((t) => t.pnlPercent / 100) // 转换为小数
    const avgReturn = returns.reduce((sum, r) => sum + r, 0) / returns.length

    // 计算标准差
    const variance =
      returns.reduce((sum, r) => sum + Math.pow(r - avgReturn, 2), 0) / returns.length
    const stdDev = Math.sqrt(variance)

    // 假设无风险利率为3%
    const riskFreeRate = 0.03 / 252 // 日化无风险利率

    return stdDev > 0 ? ((avgReturn - riskFreeRate) / stdDev) * Math.sqrt(252) : 0
  }

  /**
   * 创建空结果
   */
  private createEmptyResult(): BacktestResult {
    const now = new Date().toISOString().split('T')[0]

    return {
      totalTrades: 0,
      winningTrades: 0,
      losingTrades: 0,
      breakevenTrades: 0,

      winRate: 0,
      totalPnl: 0,
      totalReturn: 0,
      averageWin: 0,
      averageLoss: 0,
      profitFactor: 0,
      maxDrawdown: 0,
      sharpeRatio: 0,

      bySignalType: {},
      trades: [],
      signals: [],

      config: this.config,
      startDate: now,
      endDate: now,
      duration: 0,
    }
  }
}
