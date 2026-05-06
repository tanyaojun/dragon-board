import { describe, expect, it } from 'vitest'
import {
  calculateRawVolumeRatio,
  calculateVolumeRatioValue,
  calculateWeightedAverageVolume,
  calculateWeightedVolumeRatio,
  getAshareExpectedVolumeProgress,
  getAshareVolumeClockMinute,
  normalizeVolumeHistory,
  resolveVolumeRatioHistory,
} from '../VolumeRatioCalculator'

describe('VolumeRatioCalculator', () => {
  it('calculates weighted averages from the latest three positive finite volumes', () => {
    expect(calculateWeightedAverageVolume([100, 80, 60, 40])).toBe(86)
    expect(calculateWeightedAverageVolume([0, Number.NaN, -1])).toBeUndefined()
  })

  it('uses intraday history first when at least two values are available', () => {
    const dayHistory = new Map([['600000', [1000, 900, 800]]])
    const intradayHistory = new Map([['600000', [100, 80]]])

    const ratio = calculateVolumeRatioValue(
      { volume: 200 },
      '600000',
      dayHistory,
      intradayHistory,
      new Date('2026-05-06T10:00:00+08:00'),
    )

    expect(ratio).toBe(2.16)
  })

  it('falls back to daily history with A-share expected progress and drops same-volume latest day', () => {
    const history = resolveVolumeRatioHistory(500, [500.2, 1000, 800, 600])

    expect(history).toEqual([1000, 800, 600])
    expect(getAshareExpectedVolumeProgress(new Date('2026-05-06T10:00:00+08:00'))).toBe(0.24)
    expect(
      calculateVolumeRatioValue(
        { volume: 500 },
        '600000',
        new Map([['600000', [500.2, 1000, 800, 600]]]),
        undefined,
        new Date('2026-05-06T10:00:00+08:00'),
      ),
    ).toBe(2.42)
  })

  it('uses full-day progress outside trading hours when daily history is available', () => {
    expect(getAshareExpectedVolumeProgress(new Date('2026-05-06T05:13:00+08:00'))).toBe(1)
    expect(
      calculateVolumeRatioValue(
        { volume: 500 },
        '600000',
        new Map([['600000', [1000, 800, 600]]]),
        undefined,
        new Date('2026-05-06T05:13:00+08:00'),
      ),
    ).toBe(0.58)
  })

  it('normalizes histories and clips raw ratios to the supported range', () => {
    expect(normalizeVolumeHistory([100, '90', 0, -1, Number.NaN, 80], 2)).toEqual([100, 90])
    expect(calculateWeightedVolumeRatio(200, [100, 80])).toBe(2.16)
    expect(calculateRawVolumeRatio(1, 1000)).toBe(0.01)
    expect(calculateRawVolumeRatio(100000, 1)).toBe(99.99)
    expect(calculateRawVolumeRatio(100, 0)).toBeUndefined()
  })

  it('maps A-share trading time to elapsed progress and quote clock minute', () => {
    expect(getAshareExpectedVolumeProgress(new Date('2026-05-06T09:29:59+08:00'))).toBe(1)
    expect(getAshareExpectedVolumeProgress(new Date('2026-05-06T13:30:00+08:00'))).toBe(0.625)
    expect(getAshareExpectedVolumeProgress(new Date('2026-05-06T15:30:00+08:00'))).toBe(1)
    expect(getAshareVolumeClockMinute(new Date('2026-05-06T11:45:00+08:00'))).toBe(690)
  })
})
