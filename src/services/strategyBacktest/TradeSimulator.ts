import type {
  ReplayFrame,
  ReplaySignal,
  SimulatedTrade,
  TradeSimulationConfig,
  TradeSimulationReport,
} from './types'

export const DEFAULT_TRADE_SIMULATION_CONFIG: TradeSimulationConfig = {
  initialCapital: 100000,
  maxPositions: 5,
  positionSize: 0.2,
  feeRate: 0.0003,
  stampTaxRate: 0.0005,
  slippageRate: 0.001,
  maxHoldingBars: 10,
  stopLoss: -5,
  takeProfit: 10,
}

type Position = {
  code: string
  name: string
  entrySnapshotId: string
  entryTime: number
  entryPrice: number
  quantity: number
  holdingBars: number
}

function getPrice(signal: ReplaySignal | undefined): number | null {
  const price = Number(signal?.price)
  return Number.isFinite(price) && price > 0 ? price : null
}

function maxDrawdown(equity: Array<{ equity: number }>): number {
  let peak = equity[0]?.equity || 0
  let maxDd = 0
  for (const point of equity) {
    peak = Math.max(peak, point.equity)
    if (peak > 0) {
      maxDd = Math.min(maxDd, ((point.equity - peak) / peak) * 100)
    }
  }
  return Number(maxDd.toFixed(2))
}

export class TradeSimulator {
  run(
    frames: ReplayFrame[],
    signals: ReplaySignal[],
    configPatch: Partial<TradeSimulationConfig> = {},
  ): TradeSimulationReport {
    const config = { ...DEFAULT_TRADE_SIMULATION_CONFIG, ...configPatch }
    const signalsBySnapshot = new Map<string, ReplaySignal[]>()
    const signalBySnapshotCode = new Map<string, ReplaySignal>()
    for (const signal of signals) {
      if (!signalsBySnapshot.has(signal.snapshotId)) signalsBySnapshot.set(signal.snapshotId, [])
      signalsBySnapshot.get(signal.snapshotId)!.push(signal)
      signalBySnapshotCode.set(`${signal.snapshotId}:${signal.code}`, signal)
    }

    let cash = config.initialCapital
    const positions = new Map<string, Position>()
    const trades: SimulatedTrade[] = []
    const equityHistory: TradeSimulationReport['equityHistory'] = []

    for (let frameIndex = 0; frameIndex < frames.length; frameIndex++) {
      const frame = frames[frameIndex]
      const frameSignals = signalsBySnapshot.get(frame.snapshotId) || []
      const frameSignalByCode = new Map(frameSignals.map((signal) => [signal.code, signal]))

      for (const position of Array.from(positions.values())) {
        position.holdingBars += 1
        const signal = frameSignalByCode.get(position.code)
        const exitPriceRaw = getPrice(signal)
        if (!signal || !exitPriceRaw) continue

        const grossReturn = ((exitPriceRaw - position.entryPrice) / position.entryPrice) * 100
        const shouldExit =
          signal.candidateTier === 'D_EXIT_RISK' ||
          (signal.candidateTier === 'C_CROWDED' &&
            (signal.rankTrend.strategy?.momentum?.acceleration ?? 0) <= 0) ||
          signal.rank > 50 ||
          position.holdingBars >= config.maxHoldingBars ||
          grossReturn <= config.stopLoss ||
          grossReturn >= config.takeProfit

        if (!shouldExit) continue

        const exitPrice = exitPriceRaw * (1 - config.slippageRate)
        const grossAmount = position.quantity * exitPrice
        const exitCost = grossAmount * (config.feeRate + config.stampTaxRate)
        cash += grossAmount - exitCost
        const entryAmount = position.quantity * position.entryPrice
        const netProfit = grossAmount - exitCost - entryAmount

        trades.push({
          code: position.code,
          name: position.name,
          entrySnapshotId: position.entrySnapshotId,
          exitSnapshotId: frame.snapshotId,
          entryTime: position.entryTime,
          exitTime: frame.timestamp,
          entryPrice: position.entryPrice,
          exitPrice,
          quantity: position.quantity,
          grossReturn: Number(grossReturn.toFixed(2)),
          netReturn: Number(((netProfit / entryAmount) * 100).toFixed(2)),
          profit: Number(netProfit.toFixed(2)),
          reason:
            signal.candidateTier === 'D_EXIT_RISK'
              ? 'D_EXIT_RISK'
              : signal.rank > 50
                ? '排名跌出前50'
                : position.holdingBars >= config.maxHoldingBars
                  ? '到达最大持有快照'
                  : grossReturn <= config.stopLoss
                    ? '止损'
                    : grossReturn >= config.takeProfit
                      ? '止盈'
                      : '拥挤且加速度转弱',
        })
        positions.delete(position.code)
      }

      const candidates = frameSignals
        .filter((signal) => {
          if (positions.has(signal.code)) return false
          if (signal.regime === 'retreat') return false
          if (signal.candidateTier === 'A_MAIN') return signal.regime !== 'weak'
          if (signal.candidateTier !== 'B_IGNITION') return false
          const nextFrame = frames[frameIndex + 1]
          const nextSignal = signalBySnapshotCode.get(`${nextFrame?.snapshotId}:${signal.code}`)
          return nextSignal?.candidateTier === 'B_IGNITION' || nextSignal?.candidateTier === 'A_MAIN'
        })
        .sort((a, b) => b.confidence - a.confidence)

      for (const signal of candidates) {
        if (positions.size >= config.maxPositions) break
        const rawPrice = getPrice(signal)
        if (!rawPrice) continue
        const entryPrice = rawPrice * (1 + config.slippageRate)
        const allocation = Math.min(cash, config.initialCapital * config.positionSize)
        if (allocation <= 0) break
        const entryCost = allocation * config.feeRate
        const quantity = Math.floor((allocation - entryCost) / entryPrice)
        if (quantity <= 0) continue
        const usedCash = quantity * entryPrice + entryCost
        cash -= usedCash
        positions.set(signal.code, {
          code: signal.code,
          name: signal.name,
          entrySnapshotId: signal.snapshotId,
          entryTime: signal.timestamp,
          entryPrice,
          quantity,
          holdingBars: 0,
        })
      }

      const marketValue = Array.from(positions.values()).reduce((sum, position) => {
        const signal = frameSignalByCode.get(position.code)
        const price = getPrice(signal)
        return sum + position.quantity * (price || position.entryPrice)
      }, 0)
      equityHistory.push({
        snapshotId: frame.snapshotId,
        timestamp: frame.timestamp,
        equity: Number((cash + marketValue).toFixed(2)),
      })
    }

    const finalEquity = equityHistory[equityHistory.length - 1]?.equity || config.initialCapital
    const winningTrades = trades.filter((trade) => trade.netReturn > 0)

    return {
      enabled: true,
      config,
      totalReturn: Number((((finalEquity - config.initialCapital) / config.initialCapital) * 100).toFixed(2)),
      maxDrawdown: maxDrawdown(equityHistory),
      winRate: trades.length ? Number(((winningTrades.length / trades.length) * 100).toFixed(2)) : 0,
      tradeCount: trades.length,
      trades,
      equityHistory,
      notes: ['交易模拟基于固定假设，只作为候选池验证后的辅助参考。'],
    }
  }
}
