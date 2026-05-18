import { describe, expect, it } from 'vitest'

import { getTrustedVolumeRatio } from '../VolumeRatioTrust'

describe('VolumeRatioTrust', () => {
  it('keeps legacy naked volume ratios compatible when metadata is absent', () => {
    expect(getTrustedVolumeRatio({ volumeRatio: 1.8 })).toBe(1.8)
  })

  it('trusts fresh structured volume ratios', () => {
    expect(
      getTrustedVolumeRatio({
        volumeRatio: 2.2,
        volumeRatioMeta: {
          status: 'fresh',
          source: 'intraday_snapshot',
          calculatedAt: Date.now(),
          currentVolume: 100000,
        },
      }),
    ).toBe(2.2)
  })

  it('rejects stale, suspicious, unavailable and invalid volume ratios', () => {
    expect(getTrustedVolumeRatio({ volumeRatio: 99.99, volumeRatioMeta: { status: 'suspicious' } })).toBe(0)
    expect(getTrustedVolumeRatio({ volumeRatio: 1.8, volumeRatioMeta: { status: 'stale' } })).toBe(0)
    expect(getTrustedVolumeRatio({ volumeRatio: undefined, volumeRatioMeta: { status: 'unavailable' } })).toBe(0)
    expect(getTrustedVolumeRatio({ volumeRatio: Number.POSITIVE_INFINITY })).toBe(0)
  })
})
