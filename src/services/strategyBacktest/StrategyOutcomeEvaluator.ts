import type { CandidateTier } from '@/services/rankTrend/types'
import type {
  BacktestHorizon,
  ForwardOutcome,
  ForwardValidationReport,
  HorizonValidationReport,
  OutcomeStats,
  ReplayFrame,
  ReplaySignal,
  TierDistributionReport,
} from './types'

const CANDIDATE_TIERS: CandidateTier[] = [
  'A_MAIN',
  'B_IGNITION',
  'C_CROWDED',
  'D_EXIT_RISK',
  'N_NEUTRAL',
]

type SignalOutcome = {
  signal: ReplaySignal
  outcome: ForwardOutcome
}

function average(values: Array<number | null>): number | null {
  const valid = values.filter((value): value is number => Number.isFinite(Number(value)))
  if (!valid.length) return null
  return valid.reduce((sum, value) => sum + value, 0) / valid.length
}

function round(value: number | null, digits = 2): number | null {
  if (value === null || !Number.isFinite(value)) return null
  return Number(value.toFixed(digits))
}

function share(count: number, total: number): number {
  return total > 0 ? Number((count / total).toFixed(4)) : 0
}

function findFrameIndex(frames: ReplayFrame[], snapshotId: string): number {
  return frames.findIndex((frame) => frame.snapshotId === snapshotId)
}

function findStock(frame: ReplayFrame | undefined, code: string) {
  return frame?.stocks.find((stock) => stock.code === code) || null
}

function percentile(rank: number, total: number): number {
  return total > 0 ? ((total - rank + 1) / total) * 100 : 0
}

function momentumBucket(signal: ReplaySignal): string {
  const momentum = signal.rankTrend.strategy?.momentum
  if (!momentum) return 'momentum缺失'
  const short = momentum.short >= 3 ? 'short强' : momentum.short <= -3 ? 'short弱' : 'short中'
  const mid = momentum.mid >= 4 ? 'mid强' : momentum.mid <= -3 ? 'mid弱' : 'mid中'
  const long = momentum.long >= 4 ? 'long高位' : 'long非高位'
  const accel = momentum.acceleration >= 0 ? 'accel正' : 'accel负'
  const shock = Math.abs(momentum.shock) >= 1.5 ? 'shock高' : 'shock低'
  return `${short}/${mid}/${long}/${accel}/${shock}`
}

function statsFor(groupKey: string, items: SignalOutcome[]): OutcomeStats {
  const found = items.filter((item) => item.outcome.found)
  return {
    groupKey,
    sampleCount: items.length,
    foundCount: found.length,
    foundRate: share(found.length, items.length),
    avgRankDelta: round(average(found.map((item) => item.outcome.rankDelta))),
    avgPercentileDelta: round(average(found.map((item) => item.outcome.percentileDelta))),
    avgPriceReturn: round(average(found.map((item) => item.outcome.priceReturn))),
    avgMaxDrawdown: round(average(found.map((item) => item.outcome.maxDrawdown))),
    stayedTop20Rate: share(found.filter((item) => item.outcome.stayedTop20).length, found.length),
    stayedTop50Rate: share(found.filter((item) => item.outcome.stayedTop50).length, found.length),
  }
}

function groupStats(
  pairs: SignalOutcome[],
  selector: (pair: SignalOutcome) => string,
  preferredOrder?: string[],
): OutcomeStats[] {
  const groups = new Map<string, SignalOutcome[]>()
  for (const pair of pairs) {
    const key = selector(pair)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(pair)
  }
  const rows = Array.from(groups.entries()).map(([key, items]) => statsFor(key, items))
  if (preferredOrder?.length) {
    const order = new Map(preferredOrder.map((key, index) => [key, index]))
    rows.sort((a, b) => (order.get(a.groupKey) ?? 999) - (order.get(b.groupKey) ?? 999))
    return rows
  }
  return rows.sort((a, b) => b.sampleCount - a.sampleCount)
}

export class StrategyOutcomeEvaluator {
  buildDistribution(signals: ReplaySignal[]): TierDistributionReport {
    const total = signals.length
    const countBy = (selector: (signal: ReplaySignal) => string) => {
      const counts = new Map<string, number>()
      for (const signal of signals) {
        const key = selector(signal)
        counts.set(key, (counts.get(key) || 0) + 1)
      }
      return Array.from(counts.entries())
        .map(([key, count]) => ({ key, count, share: share(count, total) }))
        .sort((a, b) => b.count - a.count)
    }

    const dailyMap = new Map<string, TierDistributionReport['daily'][number]>()
    for (const signal of signals) {
      if (!dailyMap.has(signal.tradingDate)) {
        dailyMap.set(signal.tradingDate, {
          tradingDate: signal.tradingDate,
          total: 0,
          tiers: {
            A_MAIN: 0,
            B_IGNITION: 0,
            C_CROWDED: 0,
            D_EXIT_RISK: 0,
            N_NEUTRAL: 0,
          },
          regimes: {
            strong: 0,
            normal: 0,
            weak: 0,
            retreat: 0,
          },
        })
      }
      const row = dailyMap.get(signal.tradingDate)!
      row.total += 1
      row.tiers[signal.candidateTier] += 1
      row.regimes[signal.regime] += 1
    }

    const weakRetreatSignals = signals.filter(
      (signal) => signal.regime === 'weak' || signal.regime === 'retreat',
    )
    const weakRetreatAB = weakRetreatSignals.filter(
      (signal) => signal.candidateTier === 'A_MAIN' || signal.candidateTier === 'B_IGNITION',
    )
    const warnings: string[] = []
    const aShare = share(signals.filter((signal) => signal.candidateTier === 'A_MAIN').length, total)
    if (aShare > 0.1) warnings.push(`A_MAIN 占比 ${(aShare * 100).toFixed(1)}%，高于 10% 验收警戒线`)
    if (weakRetreatSignals.length && share(weakRetreatAB.length, weakRetreatSignals.length) > 0.12) {
      warnings.push('弱市/退潮环境下 A/B 收缩不充分')
    }

    return {
      totalSignals: total,
      byTier: CANDIDATE_TIERS.map((tier) => ({
        key: tier,
        count: signals.filter((signal) => signal.candidateTier === tier).length,
        share: share(signals.filter((signal) => signal.candidateTier === tier).length, total),
      })),
      byStage: countBy((signal) => signal.stage),
      byRegime: countBy((signal) => signal.regime),
      daily: Array.from(dailyMap.values()).sort((a, b) => a.tradingDate.localeCompare(b.tradingDate)),
      weakRetreatABShare: share(weakRetreatAB.length, weakRetreatSignals.length),
      warnings,
    }
  }

  evaluate(
    frames: ReplayFrame[],
    signals: ReplaySignal[],
    horizons: BacktestHorizon[],
  ): ForwardValidationReport {
    const signalBySnapshotCode = new Map<string, ReplaySignal>()
    for (const signal of signals) {
      signalBySnapshotCode.set(`${signal.snapshotId}:${signal.code}`, signal)
    }

    const horizonReports = horizons.map((horizon) =>
      this.evaluateHorizon(frames, signals, horizon),
    )

    const bSignals = signals.filter((signal) => signal.candidateTier === 'B_IGNITION')
    const bToA = bSignals.filter((signal) => {
      const frameIndex = findFrameIndex(frames, signal.snapshotId)
      const nextFrame = frames[frameIndex + 1]
      return signalBySnapshotCode.get(`${nextFrame?.snapshotId}:${signal.code}`)?.candidateTier === 'A_MAIN'
    })

    const dSignals = signals.filter((signal) => signal.candidateTier === 'D_EXIT_RISK')
    const dDecay = dSignals.filter((signal) => {
      const pair = this.evaluateSignal(frames, signal, 3)
      return pair.found && ((pair.rankDelta ?? 0) < 0 || (pair.percentileDelta ?? 0) < 0)
    })

    return {
      horizons: horizonReports,
      bToATransitionRate: share(bToA.length, bSignals.length),
      dDecayRate: share(dDecay.length, dSignals.length),
      buyBaselineComparison: horizonReports.map((report) => ({
        horizon: report.horizon,
        aMain: report.byTier.find((row) => row.groupKey === 'A_MAIN') || null,
        legacyBuy:
          statsFor(
            'legacyBuy',
            signals
              .filter((signal) => signal.rankTrend.decision.final.signal === 'buy')
              .map((signal) => ({
                signal,
                outcome: this.evaluateSignal(frames, signal, report.horizon),
              })),
          ) || null,
      })),
    }
  }

  private evaluateHorizon(
    frames: ReplayFrame[],
    signals: ReplaySignal[],
    horizon: BacktestHorizon,
  ): HorizonValidationReport {
    const pairs = signals.map((signal) => ({
      signal,
      outcome: this.evaluateSignal(frames, signal, horizon),
    }))

    return {
      horizon,
      byTier: groupStats(pairs, (pair) => pair.signal.candidateTier, CANDIDATE_TIERS),
      byStage: groupStats(pairs, (pair) => pair.signal.stage),
      byRegime: groupStats(pairs, (pair) => pair.signal.regime),
      byTierStage: groupStats(
        pairs,
        (pair) => `${pair.signal.candidateTier}/${pair.signal.stage}`,
      ),
      byTierRegime: groupStats(
        pairs,
        (pair) => `${pair.signal.candidateTier}/${pair.signal.regime}`,
      ),
      byMomentumBucket: groupStats(pairs, (pair) => momentumBucket(pair.signal)),
    }
  }

  private evaluateSignal(
    frames: ReplayFrame[],
    signal: ReplaySignal,
    horizon: BacktestHorizon,
  ): ForwardOutcome {
    const entryIndex = findFrameIndex(frames, signal.snapshotId)
    const futureIndex = entryIndex + horizon
    const currentFrame = frames[entryIndex]
    const futureFrame = frames[futureIndex]
    const currentStock = findStock(currentFrame, signal.code)
    const futureStock = findStock(futureFrame, signal.code)

    if (entryIndex < 0 || !currentStock || !futureStock || !futureFrame) {
      return {
        code: signal.code,
        entrySnapshotId: signal.snapshotId,
        horizon,
        found: false,
        rankDelta: null,
        percentileDelta: null,
        priceReturn: null,
        maxDrawdown: null,
        stayedTop20: false,
        stayedTop50: false,
      }
    }

    const currentRank = Number(currentStock.rank)
    const futureRank = Number(futureStock.rank)
    const currentPercentile = percentile(currentRank, currentFrame.stocks.length)
    const futurePercentile = percentile(futureRank, futureFrame.stocks.length)
    const entryPrice = Number(currentStock.price)
    const futurePrice = Number(futureStock.price)
    let priceReturn: number | null = null
    let maxDrawdown: number | null = null

    if (Number.isFinite(entryPrice) && entryPrice > 0 && Number.isFinite(futurePrice)) {
      priceReturn = ((futurePrice - entryPrice) / entryPrice) * 100
      const prices = frames
        .slice(entryIndex, futureIndex + 1)
        .map((frame) => Number(findStock(frame, signal.code)?.price))
        .filter((price) => Number.isFinite(price) && price > 0)
      if (prices.length) {
        const minPrice = Math.min(...prices)
        maxDrawdown = ((minPrice - entryPrice) / entryPrice) * 100
      }
    }

    const pathStocks = frames
      .slice(entryIndex, futureIndex + 1)
      .map((frame) => findStock(frame, signal.code))
    const stayedTop20 = pathStocks.length > 0 && pathStocks.every((stock) => stock && stock.rank <= 20)
    const stayedTop50 = pathStocks.length > 0 && pathStocks.every((stock) => stock && stock.rank <= 50)

    return {
      code: signal.code,
      entrySnapshotId: signal.snapshotId,
      horizon,
      found: true,
      rankDelta: currentRank - futureRank,
      percentileDelta: futurePercentile - currentPercentile,
      priceReturn: round(priceReturn),
      maxDrawdown: round(maxDrawdown),
      stayedTop20,
      stayedTop50,
    }
  }
}
