import { SnapshotReplayLoader } from './SnapshotReplayLoader'
import { RankTrendReplayEngine } from './RankTrendReplayEngine'
import { StrategyOutcomeEvaluator } from './StrategyOutcomeEvaluator'
import { TradeSimulator } from './TradeSimulator'
import { DEFAULT_RANK_TREND_SNAPSHOT_TYPE } from '@/type/rankTrendDefaults'
import type {
  BacktestHorizon,
  BacktestSnapshotType,
  ReplaySignal,
  StrategyBacktestReport,
  StrategyBacktestRunOptions,
  ValidateLatestOptions,
} from './types'

export * from './types'
export { DEFAULT_TRADE_SIMULATION_CONFIG } from './TradeSimulator'

const DEFAULT_HORIZONS: BacktestHorizon[] = [1, 3, 5, 10]

function formatDate(date: Date): string {
  const yyyy = date.getFullYear()
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

class StrategyBacktestService {
  private readonly loader = new SnapshotReplayLoader()
  private readonly engine = new RankTrendReplayEngine()
  private readonly evaluator = new StrategyOutcomeEvaluator()
  private readonly simulator = new TradeSimulator()

  async run(options: StrategyBacktestRunOptions = {}): Promise<StrategyBacktestReport> {
    const loaded = await this.loader.load(options)
    const horizons = options.horizons?.length ? options.horizons : DEFAULT_HORIZONS
    const signals = this.engine.replay(loaded.frames, {
      warmupCount: options.warmupCount,
      windowSize: 50,
      meta: loaded.meta,
    })
    const distribution = this.evaluator.buildDistribution(signals)
    const forwardValidation = this.evaluator.evaluate(loaded.frames, signals, horizons)
    const report: StrategyBacktestReport = {
      meta: loaded.meta,
      distribution,
      forwardValidation,
    }

    if (options.enableTradeSimulation) {
      report.tradeSimulation = this.simulator.run(
        loaded.frames,
        signals,
        options.tradeConfig,
      )
    }

    return report
  }

  async validateLatestAvailable(options: ValidateLatestOptions = {}): Promise<StrategyBacktestReport> {
    const days = Math.max(1, options.days ?? 10)
    const start = new Date()
    start.setDate(start.getDate() - days * 2)
    const snapshotType: BacktestSnapshotType = options.snapshotType || DEFAULT_RANK_TREND_SNAPSHOT_TYPE
    return this.run({
      snapshotTypes: [snapshotType],
      startDate: formatDate(start),
      horizons: DEFAULT_HORIZONS,
      enableTradeSimulation: false,
    })
  }

  async replayFrame(snapshotId: string): Promise<ReplaySignal[]> {
    const singleFrame = await this.loader.loadSingleFrame(snapshotId)
    if (!singleFrame) return []
    const loaded = await this.loader.load({
      snapshotTypes: [singleFrame.type],
      endDate: singleFrame.tradingDate,
    })
    const frameIndex = loaded.frames.findIndex((frame) => frame.snapshotId === snapshotId)
    if (frameIndex < 0) return []
    return this.engine.replayFrameAt(loaded.frames, frameIndex, {
      windowSize: 50,
      meta: loaded.meta,
    })
  }

  async explainSignal(snapshotId: string, code: string): Promise<ReplaySignal | null> {
    const signals = await this.replayFrame(snapshotId)
    return signals.find((signal) => signal.code === code) || null
  }
}

export const strategyBacktest = new StrategyBacktestService()

if (typeof window !== 'undefined') {
  ;(window as any).strategyBacktest = strategyBacktest
}
