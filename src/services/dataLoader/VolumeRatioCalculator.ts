import { A_SHARE_TRADING_MINUTES, VOLUME_RATIO_HISTORY_WEIGHTS } from './constants'

type StockWithVolume = {
  volume?: unknown
}

const clamp = (value: number, min: number, max: number): number => {
  return Math.min(max, Math.max(min, value))
}

export function calculateVolumeRatioValue(
  stock: StockWithVolume,
  code: string,
  volumeHistoryMap: Map<string, number[]>,
  intradayVolumeHistoryMap: Map<string, number[]> = new Map(),
  date: Date = new Date(),
): number | undefined {
  const currentVolume = Number(stock.volume)
  if (!Number.isFinite(currentVolume) || currentVolume <= 0) return undefined

  const intradayVolumes = normalizeVolumeHistory(intradayVolumeHistoryMap.get(code))
  if (intradayVolumes.length >= 2) {
    return calculateWeightedVolumeRatio(currentVolume, intradayVolumes)
  }

  const volumes = resolveVolumeRatioHistory(currentVolume, volumeHistoryMap.get(code))
  if (volumes.length < 2) return undefined

  const expectedVolumeProgress = getAshareExpectedVolumeProgress(date)
  if (!expectedVolumeProgress) return undefined
  const avgDailyVolume = calculateWeightedAverageVolume(volumes)
  if (!avgDailyVolume) return undefined

  const expectedVolume = avgDailyVolume * expectedVolumeProgress
  return calculateRawVolumeRatio(currentVolume, expectedVolume)
}

export function calculateWeightedVolumeRatio(
  currentVolume: number,
  volumes: number[],
): number | undefined {
  const avgVolume = calculateWeightedAverageVolume(volumes)
  if (!avgVolume) return undefined
  return calculateRawVolumeRatio(currentVolume, avgVolume)
}

export function calculateWeightedAverageVolume(volumes: number[]): number | undefined {
  const normalized = normalizeVolumeHistory(volumes)
  const daysToUse = Math.min(normalized.length, VOLUME_RATIO_HISTORY_WEIGHTS.length)
  if (daysToUse === 0) return undefined

  let weightedSum = 0
  let totalWeight = 0

  for (let i = 0; i < daysToUse; i++) {
    const weight = VOLUME_RATIO_HISTORY_WEIGHTS[i]
    weightedSum += normalized[i] * weight
    totalWeight += weight
  }

  if (totalWeight === 0) return undefined

  const avgVolume = weightedSum / totalWeight
  return avgVolume > 0 ? avgVolume : undefined
}

export function calculateRawVolumeRatio(
  currentVolume: number,
  expectedVolume: number,
): number | undefined {
  if (expectedVolume <= 0) return undefined
  let ratio = currentVolume / expectedVolume
  if (!Number.isFinite(ratio) || ratio <= 0) return undefined

  ratio = Math.min(99.99, Math.max(0.01, Number(ratio.toFixed(2))))
  return ratio
}

export function getAshareExpectedVolumeProgress(date: Date = new Date()): number | undefined {
  const elapsedMinutes = getAshareElapsedTradingMinutes(date)
  if (!elapsedMinutes) return undefined

  if (elapsedMinutes <= 30) {
    return clamp(0.06 + (elapsedMinutes / 30) * 0.18, 0.06, 0.24)
  }
  if (elapsedMinutes <= 120) {
    return 0.24 + ((elapsedMinutes - 30) / 90) * 0.26
  }
  if (elapsedMinutes <= 180) {
    return 0.5 + ((elapsedMinutes - 120) / 60) * 0.25
  }

  return clamp(0.75 + ((elapsedMinutes - 180) / 60) * 0.25, 0.75, 1)
}

export function normalizeVolumeHistory(
  volumes?: unknown[],
  limit: number = VOLUME_RATIO_HISTORY_WEIGHTS.length,
): number[] {
  return (volumes || [])
    .map((volume) => Number(volume))
    .filter((volume) => Number.isFinite(volume) && volume > 0)
    .slice(0, limit)
}

export function resolveVolumeRatioHistory(currentVolume: number, volumes?: number[]): number[] {
  if (!volumes?.length) return []

  const normalized = normalizeVolumeHistory(volumes, VOLUME_RATIO_HISTORY_WEIGHTS.length + 1)

  if (!normalized.length) return []

  const latestVolume = normalized[0]
  const relativeDiff = Math.abs(latestVolume - currentVolume) / currentVolume

  if (normalized.length > 1 && relativeDiff <= 0.001) {
    return normalized.slice(1, 4)
  }

  return normalized.slice(0, 3)
}

export function getAshareVolumeClockMinute(date: Date): number | undefined {
  const secondsOfDay = date.getHours() * 3600 + date.getMinutes() * 60 + date.getSeconds()
  const morningStart = 9 * 3600 + 30 * 60
  const morningEnd = 11 * 3600 + 30 * 60
  const afternoonStart = 13 * 3600
  const afternoonEnd = 15 * 3600

  if (secondsOfDay < morningStart) return undefined
  if (secondsOfDay <= morningEnd) return secondsOfDay / 60
  if (secondsOfDay < afternoonStart) return morningEnd / 60
  if (secondsOfDay <= afternoonEnd) return secondsOfDay / 60
  return afternoonEnd / 60
}

function getAshareElapsedTradingMinutes(date: Date = new Date()): number | undefined {
  const secondsOfDay = date.getHours() * 3600 + date.getMinutes() * 60 + date.getSeconds()
  const morningStart = 9 * 3600 + 30 * 60
  const morningEnd = 11 * 3600 + 30 * 60
  const afternoonStart = 13 * 3600
  const afternoonEnd = 15 * 3600

  if (secondsOfDay < morningStart) return A_SHARE_TRADING_MINUTES
  if (secondsOfDay <= morningEnd) {
    return Math.min(120, Math.max(1, Math.ceil((secondsOfDay - morningStart) / 60)))
  }
  if (secondsOfDay < afternoonStart) return 120
  if (secondsOfDay <= afternoonEnd) {
    return Math.min(
      A_SHARE_TRADING_MINUTES,
      120 + Math.max(1, Math.ceil((secondsOfDay - afternoonStart) / 60)),
    )
  }

  return A_SHARE_TRADING_MINUTES
}
