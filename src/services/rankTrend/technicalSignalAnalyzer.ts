import type {
  MacdCross,
  RankSignalDirection,
  RankTrendAnalysisResult,
  RankTrendMomentumProfile,
  RankTrendRuntimeConfig,
} from './types'
import {
  average,
  calculateSignalConfidence,
  calculateWeightedShare,
  clamp,
  getMacdMinSamples,
  normalizeSigned,
} from './utils'

const MOVING_AVERAGE_PERIODS = {
  ma5: 5,
  ma10: 10,
} as const

export type MomentumAnalysisData = {
  values: number[]
  prevValues: number[]
  score: number
  signal: RankSignalDirection
  confidence: number
}

function calculatePeriodMomentum(percentiles: number[], period: number): number {
  if (percentiles.length < period + 1) return 0
  const current = percentiles[percentiles.length - 1]
  const past = percentiles[percentiles.length - 1 - period]
  return current - past
}

function calculateMomentumOrZero(percentiles: number[], period: number): number {
  return percentiles.length >= period + 1 ? calculatePeriodMomentum(percentiles, period) : 0
}

function calculatePrevMomentumOrZero(percentiles: number[], period: number): number {
  return percentiles.length >= period + 2 ? calculatePrevPeriodMomentum(percentiles, period) : 0
}

function averageMomentum(percentiles: number[], periods: number[]): number {
  const values = periods.map((period) => calculateMomentumOrZero(percentiles, period))
  return average(values)
}

function averagePrevMomentum(percentiles: number[], periods: number[]): number {
  const values = periods.map((period) => calculatePrevMomentumOrZero(percentiles, period))
  return average(values)
}

function calculateMomentumRankShock(percentiles: number[]): number {
  if (percentiles.length < 6) return 0
  const velocities: number[] = []
  for (let i = 1; i < percentiles.length; i++) {
    velocities.push(percentiles[i] - percentiles[i - 1])
  }

  const recent = velocities.slice(-10)
  const current = recent[recent.length - 1] ?? 0
  const baseline = recent.slice(0, -1)
  if (baseline.length < 3) return 0

  const mean = average(baseline)
  const variance = average(baseline.map((value) => (value - mean) ** 2))
  const std = Math.sqrt(variance)
  if (!Number.isFinite(std) || std < 1e-6) return 0
  return clamp((current - mean) / std, -5, 5)
}

export function calculateMomentumProfile(percentiles: number[]): RankTrendMomentumProfile {
  const shortPeriods = [1, 3, 5]
  const midPeriods = [5, 8, 13]
  const longPeriods = [13, 21]

  const short = averageMomentum(percentiles, shortPeriods)
  const mid = averageMomentum(percentiles, midPeriods)
  const long = averageMomentum(percentiles, longPeriods)
  const prevShort = averagePrevMomentum(percentiles, shortPeriods)
  const prevMid = averagePrevMomentum(percentiles, midPeriods)
  const acceleration = average([short - prevShort, mid - prevMid])
  const shock = calculateMomentumRankShock(percentiles)
  const composite = clamp(0.35 * short + 0.4 * mid + 0.25 * long + 0.2 * acceleration, -100, 100)

  return {
    short: Number(short.toFixed(2)),
    mid: Number(mid.toFixed(2)),
    long: Number(long.toFixed(2)),
    acceleration: Number(acceleration.toFixed(2)),
    shock: Number(shock.toFixed(2)),
    composite: Number(composite.toFixed(2)),
  }
}

function calculatePrevPeriodMomentum(percentiles: number[], period: number): number {
  if (percentiles.length < period + 2) return 0
  const current = percentiles[percentiles.length - 2]
  const past = percentiles[percentiles.length - 2 - period]
  return current - past
}

function calculateMovingAverage(data: number[], period: number): number {
  if (data.length === 0) return 0
  if (data.length < period) return average(data)
  return average(data.slice(-period))
}

function calculateEmaSeries(data: number[], period: number): number[] {
  if (data.length === 0) return []
  const multiplier = 2 / (period + 1)
  const series: number[] = []
  let ema = data[0]
  for (let i = 0; i < data.length; i++) {
    if (i === 0) {
      ema = data[i]
    } else {
      ema = (data[i] - ema) * multiplier + ema
    }
    series.push(ema)
  }
  return series
}

function calculateMacd(
  data: number[],
  config: RankTrendRuntimeConfig,
): RankTrendAnalysisResult['technical']['macd'] {
  const { macdFast: FAST, macdSlow: SLOW, macdSignal: SIGNAL } = config
  if (data.length < getMacdMinSamples(config)) {
    return { dif: 0, dea: 0, histogram: 0, cross: 'none', confirmed: false, rawScore: 0 }
  }

  const emaFastSeries = calculateEmaSeries(data, FAST)
  const emaSlowSeries = calculateEmaSeries(data, SLOW)
  const difSeries = data.map((_, index) => emaFastSeries[index] - emaSlowSeries[index])
  const deaSeries = calculateEmaSeries(difSeries, SIGNAL)
  const histogramSeries = difSeries.map((dif, index) => 2 * (dif - deaSeries[index]))

  const dif = difSeries[difSeries.length - 1] ?? 0
  const dea = deaSeries[deaSeries.length - 1] ?? 0
  const histogram = histogramSeries[histogramSeries.length - 1] ?? 0
  const prevDif = difSeries[difSeries.length - 2] ?? dif
  const prevDea = deaSeries[deaSeries.length - 2] ?? dea
  const prevHistogram = histogramSeries[histogramSeries.length - 2] ?? histogram
  const gap = dif - dea
  const prevGap = prevDif - prevDea

  let detectedCross: MacdCross = 'none'
  if (prevDif <= prevDea && dif > dea) {
    detectedCross = 'golden'
  } else if (prevDif >= prevDea && dif < dea) {
    detectedCross = 'death'
  }

  const warmGaps = histogramSeries.slice(Math.max(0, SLOW - 1)).map((item) => item / 2)
  const gapLookback = warmGaps.slice(-Math.min(Math.max(SIGNAL, 3), warmGaps.length))
  const gapScale = Math.max(1e-6, average(gapLookback.map((value) => Math.abs(value))))
  const strongGapScore = Math.tanh(Math.abs(gap) / gapScale)
  const impulseScore = Math.tanh(Math.abs(gap - prevGap) / gapScale)
  const goldenGapFloor = Math.max(1e-6, gapScale * 0.18)
  const deathGapFloor = Math.max(1e-6, gapScale * 0.12)
  let cross: MacdCross = 'none'
  let rawScore = 0
  let confirmed = false

  if (detectedCross === 'golden') {
    const strongGolden =
      histogram > 0 &&
      gap > 0 &&
      gap > prevGap &&
      histogram >= prevHistogram &&
      strongGapScore >= 0.2 &&
      gap >= goldenGapFloor
    confirmed = strongGolden
    if (strongGolden) {
      cross = 'golden'
      rawScore = clamp(0.7 * strongGapScore + 0.3 * impulseScore, 0, 1)
    }
  } else if (detectedCross === 'death') {
    const validDeath =
      histogram < 0 &&
      gap < 0 &&
      (Math.abs(gap) >= deathGapFloor || strongGapScore >= 0.18)
    confirmed = validDeath && gap < prevGap && histogram <= prevHistogram
    if (validDeath) {
      cross = 'death'
      rawScore = -clamp(0.7 * strongGapScore + 0.3 * impulseScore, 0, 1)
    }
  }

  return { dif, dea, histogram, cross, confirmed, rawScore }
}

function calculateContinuousMomentumContribution(
  value: number,
  buyThreshold: number,
  sellThreshold: number,
  weight: number,
): number {
  if (!Number.isFinite(value) || !Number.isFinite(weight) || weight <= 0) return 0
  if (value >= 0) {
    return Math.tanh(value / Math.max(1e-6, Math.abs(buyThreshold))) * 100 * weight
  }
  return -Math.tanh(Math.abs(value) / Math.max(1e-6, Math.abs(sellThreshold))) * 100 * weight
}

export function calculateMomentumDataForPercentiles(
  percentiles: number[],
  config: RankTrendRuntimeConfig,
): MomentumAnalysisData | null {
  const periods = config.momentumPeriods
  const weights = config.momentumWeights
  const maxPeriod = Math.max(...periods)
  if (percentiles.length < maxPeriod + 1) return null

  const values: number[] = []
  const prevValues: number[] = []
  for (let i = 0; i < periods.length; i++) {
    const period = periods[i]
    values.push(calculatePeriodMomentum(percentiles, period))
    prevValues.push(calculatePrevPeriodMomentum(percentiles, period))
  }

  let totalScore = 0
  for (let i = 0; i < periods.length; i++) {
    totalScore += calculateContinuousMomentumContribution(
      values[i],
      config.buyThresholds[i],
      config.sellThresholds[i],
      weights[i],
    )
  }
  totalScore = clamp(totalScore, -100, 100)

  let signal: RankSignalDirection = 'hold'
  if (totalScore >= 35) {
    signal = 'buy'
  } else if (totalScore <= -35) {
    signal = 'sell'
  }

  return {
    values,
    prevValues,
    score: totalScore,
    signal,
    confidence: clamp(50 + Math.abs(totalScore) * 0.45, 50, 95),
  }
}

function analyzeMomentumSignals(
  momentumData: MomentumAnalysisData | null,
  config: RankTrendRuntimeConfig,
): RankTrendAnalysisResult['technical']['signals'] {
  const defaultSignals: RankTrendAnalysisResult['technical']['signals'] = {
    direction: { signal: 'hold', confidence: 50, score: 0 },
    acceleration: { signal: 'hold', confidence: 50, score: 0 },
    zeroCross: { signal: 'hold', confidence: 50, score: 0 },
  }

  if (!momentumData || momentumData.values.length === 0) return defaultSignals

  const periodCount = Math.min(
    momentumData.values.length,
    momentumData.prevValues.length,
    config.momentumWeights.length,
    config.buyThresholds.length,
    config.sellThresholds.length,
  )
  if (periodCount === 0) return defaultSignals

  const values = momentumData.values.slice(0, periodCount)
  const prevValues = momentumData.prevValues.slice(0, periodCount)
  const weights = config.momentumWeights.slice(0, periodCount)
  const buyThresholds = config.buyThresholds.slice(0, periodCount)
  const sellThresholds = config.sellThresholds.slice(0, periodCount)

  const periodScores = values.map((value, index) =>
    normalizeSigned(value, buyThresholds[index], Math.abs(sellThresholds[index])),
  )
  const directionRaw = periodScores.reduce((sum, score, index) => sum + score * weights[index], 0)
  const positiveShare = calculateWeightedShare(periodScores, weights, (score) => score > 0)
  const negativeShare = calculateWeightedShare(periodScores, weights, (score) => score < 0)
  const directionScore = clamp(
    directionRaw * (0.5 + 0.5 * Math.max(positiveShare, negativeShare)),
    -1,
    1,
  )
  const longWindow = periodScores.slice(-Math.min(2, periodScores.length))
  const longOpposesBuy = longWindow.length === 2 && longWindow.every((score) => score <= -0.25)
  const longOpposesSell = longWindow.length === 2 && longWindow.every((score) => score >= 0.25)
  const longAgreementCount =
    directionScore >= 0
      ? longWindow.filter((score) => score >= 0.15).length
      : longWindow.filter((score) => score <= -0.15).length
  let directionSignal: RankSignalDirection = 'hold'
  if (directionScore >= 0.2 && positiveShare >= 0.6 && !longOpposesBuy) {
    directionSignal = 'buy'
  } else if (directionScore <= -0.2 && negativeShare >= 0.6 && !longOpposesSell) {
    directionSignal = 'sell'
  }

  const accelerations = values.map((value, index) => {
    const prevValue = prevValues[index]
    return Number.isFinite(prevValue) ? value - prevValue : 0
  })
  const accelScores = accelerations.map((value, index) =>
    normalizeSigned(value, buyThresholds[index], Math.abs(sellThresholds[index])),
  )
  const accelerationRaw = accelScores.reduce((sum, score, index) => sum + score * weights[index], 0)
  const shortScores = accelScores.slice(0, Math.min(2, accelScores.length))
  const shortBoost = average(shortScores.map((score) => Math.abs(score)))
  const accelerationScore = clamp(accelerationRaw * (0.7 + 0.3 * shortBoost), -1, 1)
  let accelerationSignal: RankSignalDirection = 'hold'
  if (accelerationScore >= 0.18 && shortScores.some((score) => score > 0)) {
    accelerationSignal = 'buy'
  } else if (accelerationScore <= -0.18 && shortScores.some((score) => score < 0)) {
    accelerationSignal = 'sell'
  }
  const shortAgreementCount =
    accelerationSignal === 'buy'
      ? shortScores.filter((score) => score > 0).length
      : accelerationSignal === 'sell'
        ? shortScores.filter((score) => score < 0).length
        : 0

  let zeroCrossSignal: RankSignalDirection = 'hold'
  let zeroCrossScore = 0
  let zeroCrossConfidence = 50
  if (periodCount >= 2) {
    const triggerNow = values[0]
    const triggerPrev = prevValues[0] ?? 0
    const confirmNow = values[1]
    const confirmScore = normalizeSigned(
      confirmNow,
      buyThresholds[1],
      Math.abs(sellThresholds[1]),
    )
    const triggerStrength = Math.min(
      1,
      Math.abs(
        normalizeSigned(triggerNow, buyThresholds[0], Math.abs(sellThresholds[0])),
      ),
    )
    const confirmStrength = Math.min(1, Math.abs(confirmScore))
    const isGoldenCross = triggerPrev <= 0 && triggerNow > 0
    const isDeathCross = triggerPrev >= 0 && triggerNow < 0

    if (isGoldenCross && confirmScore >= -0.15) {
      zeroCrossSignal = 'buy'
      zeroCrossScore = clamp(0.7 * triggerStrength + 0.3 * Math.max(0, confirmStrength), -1, 1)
    } else if (isDeathCross && confirmScore <= 0.15) {
      zeroCrossSignal = 'sell'
      zeroCrossScore = -clamp(0.7 * triggerStrength + 0.3 * Math.max(0, confirmStrength), 0, 1)
    }
    const strongConfirm =
      (zeroCrossSignal === 'buy' && confirmScore > 0.15) ||
      (zeroCrossSignal === 'sell' && confirmScore < -0.15)
    zeroCrossConfidence = calculateSignalConfidence(zeroCrossScore, strongConfirm ? 5 : 0)
  }

  return {
    direction: {
      signal: directionSignal,
      confidence: calculateSignalConfidence(
        directionScore,
        directionSignal === 'hold' ? 0 : clamp(longAgreementCount * 2.5, 0, 5),
      ),
      score: directionScore,
    },
    acceleration: {
      signal: accelerationSignal,
      confidence: calculateSignalConfidence(
        accelerationScore,
        clamp(shortAgreementCount * 2.5, 0, 5),
      ),
      score: accelerationScore,
    },
    zeroCross: {
      signal: zeroCrossSignal,
      confidence: zeroCrossConfidence,
      score: zeroCrossScore,
    },
  }
}

function computeFallbackDirectionScores(input: {
  displayScore: number
  priceScore: number
  volumeScore: number
  capitalScore: number
}): RankTrendAnalysisResult['technical']['signals']['direction'] {
  const { displayScore, priceScore, volumeScore, capitalScore } = input
  const directionScore = clamp(
    displayScore * 0.4 + priceScore * 0.3 + capitalScore * 0.2 + volumeScore * 0.1,
    -1,
    1,
  )
  const directionSignal: RankSignalDirection =
    directionScore >= 0.2 ? 'buy' : directionScore <= -0.2 ? 'sell' : 'hold'
  const directionAgreement =
    directionSignal === 'buy'
      ? Number(displayScore > 0) + Number(priceScore > 0) + Number(capitalScore >= 0)
      : directionSignal === 'sell'
        ? Number(displayScore < 0) + Number(priceScore < 0) + Number(capitalScore <= 0)
        : 0

  return {
    signal: directionSignal,
    confidence: calculateSignalConfidence(directionScore, clamp(directionAgreement * 1.5, 0, 5)),
    score: directionScore,
  }
}

function computeFallbackAccelerationScores(input: {
  displayScore: number
  priceScore: number
  volumeScore: number
}): RankTrendAnalysisResult['technical']['signals']['acceleration'] {
  const { displayScore, priceScore, volumeScore } = input
  const accelerationScore = clamp(
    displayScore * 0.55 + priceScore * 0.25 + volumeScore * 0.2,
    -1,
    1,
  )
  const accelerationSignal: RankSignalDirection =
    accelerationScore >= 0.18 && (displayScore > 0 || priceScore > 0)
      ? 'buy'
      : accelerationScore <= -0.18 && (displayScore < 0 || priceScore < 0)
        ? 'sell'
        : 'hold'
  const accelerationAgreement =
    accelerationSignal === 'buy'
      ? Number(displayScore > 0) + Number(priceScore > 0) + Number(volumeScore > 0)
      : accelerationSignal === 'sell'
        ? Number(displayScore < 0) + Number(priceScore < 0) + Number(volumeScore < 0)
        : 0

  return {
    signal: accelerationSignal,
    confidence: calculateSignalConfidence(accelerationScore, clamp(accelerationAgreement * 1.5, 0, 5)),
    score: accelerationScore,
  }
}

function computeFallbackZeroCrossScores(input: {
  displayScore: number
  priceScore: number
  volumeScore: number
}): RankTrendAnalysisResult['technical']['signals']['zeroCross'] {
  const { displayScore, priceScore, volumeScore } = input
  let zeroCrossScore = 0
  let zeroCrossSignal: RankSignalDirection = 'hold'
  const zeroCrossBase = clamp(
    displayScore * 0.5 + priceScore * 0.35 + volumeScore * 0.15,
    -1,
    1,
  )
  if (displayScore > 0.15 && priceScore > 0 && volumeScore >= -0.2) {
    zeroCrossSignal = 'buy'
    zeroCrossScore = Math.max(0, zeroCrossBase)
  } else if (displayScore < -0.15 && priceScore < 0 && volumeScore <= 0.2) {
    zeroCrossSignal = 'sell'
    zeroCrossScore = Math.min(0, zeroCrossBase)
  }
  const zeroCrossAgreement =
    zeroCrossSignal === 'buy'
      ? Number(priceScore > 0) + Number(volumeScore > 0)
      : zeroCrossSignal === 'sell'
        ? Number(priceScore < 0) + Number(volumeScore < 0)
        : 0

  return {
    signal: zeroCrossSignal,
    confidence: calculateSignalConfidence(zeroCrossScore, clamp(zeroCrossAgreement * 2.5, 0, 5)),
    score: zeroCrossScore,
  }
}

function calculateFallbackProxySignals(input: {
  displayChange: number
  stockChange: number
  volumeRatio: number
  zlje: number
  zljzb: number
  macdData: RankTrendAnalysisResult['technical']['macd']
  macdAvailable: boolean
}): {
  direction: RankTrendAnalysisResult['technical']['signals']['direction']
  acceleration: RankTrendAnalysisResult['technical']['signals']['acceleration']
  zeroCross: RankTrendAnalysisResult['technical']['signals']['zeroCross']
  macdCross: MacdCross
  macdScore: number
  momentumScore: number
} {
  const { displayChange, stockChange, volumeRatio, zlje, zljzb, macdData, macdAvailable } = input
  const displayScore = normalizeSigned(displayChange, 8, 8)
  const priceScore = normalizeSigned(stockChange, 6, 6)
  const volumeScore = clamp(Math.tanh((volumeRatio - 1) / 0.75), -1, 1)
  const capitalBias =
    (zlje > 0 ? 0.6 : zlje < 0 ? -0.6 : 0) + (zljzb > 0 ? 0.4 : zljzb < 0 ? -0.4 : 0)
  const capitalScore = clamp(capitalBias, -1, 1)

  const direction = computeFallbackDirectionScores({ displayScore, priceScore, volumeScore, capitalScore })
  const acceleration = computeFallbackAccelerationScores({ displayScore, priceScore, volumeScore })
  const zeroCross = computeFallbackZeroCrossScores({ displayScore, priceScore, volumeScore })

  return {
    direction,
    acceleration,
    zeroCross,
    macdCross: macdAvailable ? macdData.cross : 'none',
    macdScore: macdAvailable ? clamp(macdData.rawScore, -1, 1) : 0,
    momentumScore: clamp((displayScore * 0.45 + priceScore * 0.35 + capitalScore * 0.2) * 100, -100, 100),
  }
}

export function analyzeTechnicalSignals(
  percentiles: number[],
  config: RankTrendRuntimeConfig,
): RankTrendAnalysisResult['technical'] {
  const ma5 = calculateMovingAverage(percentiles, MOVING_AVERAGE_PERIODS.ma5)
  const ma10 = calculateMovingAverage(percentiles, MOVING_AVERAGE_PERIODS.ma10)
  const macd = calculateMacd(percentiles, config)
  const momentumData = calculateMomentumDataForPercentiles(percentiles, config)
  const signals = analyzeMomentumSignals(momentumData, config)
  const momentumProfile = calculateMomentumProfile(percentiles)

  return {
    movingAverage: {
      ma5,
      ma10,
      trend: ma5 > ma10 ? 'up' : ma5 < ma10 ? 'down' : 'steady',
    },
    macd,
    signals,
    momentumScore: momentumData?.score ?? 0,
    momentumProfile,
  }
}

export function analyzeFallbackTechnicalSignals(input: {
  percentiles: number[]
  displayChange: number
  stockChange: number
  volumeRatio: number
  zlje: number
  zljzb: number
  config: RankTrendRuntimeConfig
}): RankTrendAnalysisResult['technical'] {
  const { percentiles, displayChange, stockChange, volumeRatio, zlje, zljzb, config } = input
  const ma5 = calculateMovingAverage(percentiles, MOVING_AVERAGE_PERIODS.ma5)
  const ma10 = calculateMovingAverage(percentiles, MOVING_AVERAGE_PERIODS.ma10)
  const macd = calculateMacd(percentiles, config)
  const macdAvailable = percentiles.length >= getMacdMinSamples(config)
  const momentumProfile = calculateMomentumProfile(percentiles)
  const proxy = calculateFallbackProxySignals({
    displayChange,
    stockChange,
    volumeRatio,
    zlje,
    zljzb,
    macdData: macd,
    macdAvailable,
  })

  return {
    movingAverage: {
      ma5,
      ma10,
      trend: ma5 > ma10 ? 'up' : ma5 < ma10 ? 'down' : 'steady',
    },
    macd: {
      ...macd,
      cross: proxy.macdCross,
      rawScore: proxy.macdScore,
    },
    signals: {
      direction: proxy.direction,
      acceleration: proxy.acceleration,
      zeroCross: proxy.zeroCross,
    },
    momentumScore: proxy.momentumScore,
    momentumProfile,
  }
}
