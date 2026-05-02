import { describe, expect, it } from 'vitest'

import {
  evaluateSnapshotQualityGate,
  normalizeSnapshotPayload,
  resolveSnapshotFeatureCoverage,
  resolveSnapshotFormalValidationCoverage,
  resolveSnapshotSeriesFeatureCoverage,
  selectFormalValidationSnapshots,
  summarizeSnapshotSeriesFormalValidationCoverage,
} from '../snapshotQualityGate'

describe('snapshotQualityGate', () => {
  it('normalizes legacy snapshots into partial but replayable payloads', () => {
    const normalized = normalizeSnapshotPayload(
      {
        type: 'quarter_hour',
        hotlist: [
          {
            securityCode: '600001',
            currentRank: 3,
            latestPrice: 12.3,
          },
        ],
      },
      '[一刻快照] 2026/04/21 09:30',
    )

    expect(normalized?.type).toBe('quarter_hour')
    expect(normalized?.metadata?.version).toBe('2.0')
    expect(normalized?.metadata?.featureCoverage).toBe('partial')
    expect(normalized?.hotlist?.[0]).toMatchObject({
      code: '600001',
      rank: 3,
      price: 12.3,
    })
    expect(Number(normalized?.timestamp)).toBeGreaterThan(0)
  })

  it('does not infer snapshot type from legacy chinese key prefixes alone', () => {
    const normalized = normalizeSnapshotPayload(
      {
        hotlist: [{ code: '600001', rank: 1, price: 10.2 }],
      },
      '[一刻快照] 2026/04/21 09:30',
    )

    expect(normalized?.type).toBeUndefined()
    expect(Number(normalized?.timestamp)).toBeGreaterThan(0)
  })

  it('passes quality gate for partial snapshots when core replay fields are present', () => {
    const snapshots = [
      {
        date: '2026/04/21 09:30',
        snapshot: {
          type: 'quarter_hour',
          timestamp: Date.parse('2026-04-21T09:30:00'),
          hotlist: [{ code: '600001', rank: 1, price: 10.5 }],
        },
      },
      {
        date: '2026/04/21 10:00',
        snapshot: {
          type: 'quarter_hour',
          timestamp: Date.parse('2026-04-21T10:00:00'),
          hotlist: [{ code: '600002', rank: 2, price: 11.2 }],
        },
      },
    ]

    const result = evaluateSnapshotQualityGate(snapshots, {
      minHotlistSize: 1,
      minSnapshotCount: 2,
      requiredType: 'quarter_hour',
    })

    expect(result.passed).toBe(true)
    expect(result.severity).toBe('pass')
    expect(result.stats.partialFeatureCoverageCount).toBe(2)
    expect(result.stats.fullFeatureCoverageCount).toBe(0)
  })

  it('treats same timestamp snapshots as duplicates even if date labels differ', () => {
    const timestamp = Date.parse('2026-04-21T09:30:00')
    const result = evaluateSnapshotQualityGate(
      [
        {
          date: '[一刻快照] 2026-04-21 09:30',
          snapshot: {
            type: 'quarter_hour',
            timestamp,
            hotlist: [{ code: '600001', rank: 1, price: 10.5 }],
          },
        },
        {
          date: '2026/04/21 09:30',
          snapshot: {
            type: 'quarter_hour',
            timestamp,
            hotlist: [{ code: '600002', rank: 2, price: 11.2 }],
          },
        },
      ],
      {
        minHotlistSize: 1,
        minSnapshotCount: 2,
        requiredType: 'quarter_hour',
      },
    )

    expect(result.passed).toBe(false)
    expect(result.stats.duplicateKeyCount).toBe(1)
    expect(result.issues).toContain('Duplicate (type + timestamp) key: 1')
  })

  it('infers full coverage for v2.1-style hotlist breadth fields', () => {
    const normalized = normalizeSnapshotPayload(
      {
        type: 'quarter_hour',
        hotlist: [
          { code: '600001', rank: 1, compRank: 1, price: 10.2, platforms: 4, avgRankNum: 2 },
          { code: '600002', rank: 2, compRank: 2, price: 11.4, platforms: 5, avgRankNum: 3 },
        ],
      },
      '2026/04/21 10:30',
    )

    expect(resolveSnapshotFeatureCoverage(normalized)).toBe('full')
    expect(normalized?.metadata?.version).toBe('2.1')
    expect(normalized?.metadata?.featureCoverage).toBe('full')
  })

  it('downgrades declared full coverage when breadth fields are actually missing', () => {
    const normalized = normalizeSnapshotPayload(
      {
        type: 'quarter_hour',
        metadata: {
          version: '2.1',
          featureCoverage: 'full',
        },
        hotlist: [{ code: '600001', rank: 1, price: 10.2 }],
      },
      '2026/04/21 11:00',
    )

    expect(resolveSnapshotFeatureCoverage(normalized)).toBe('partial')
    expect(normalized?.metadata?.featureCoverage).toBe('partial')
    expect(normalized?.metadata?.version).toBe('2.1')
  })

  it('ignores empty hotlist snapshots when resolving series coverage', () => {
    const featureCoverage = resolveSnapshotSeriesFeatureCoverage([
      {
        date: '2026/04/21 09:30',
        snapshot: {
          type: 'quarter_hour',
          hotlist: [],
        },
      },
      {
        date: '2026/04/21 10:00',
        snapshot: {
          type: 'quarter_hour',
          hotlist: [
            { code: '600001', rank: 1, compRank: 1, price: 10.2, platforms: 4, avgRankNum: 2 },
            { code: '600002', rank: 2, compRank: 2, price: 11.4, platforms: 5, avgRankNum: 3 },
            { code: '600003', rank: 3, compRank: 3, price: 9.8, platforms: 4, avgRankNum: 4 },
          ],
        },
      },
    ])

    expect(featureCoverage).toBe('full')
  })

  it('auto-selects the latest full-coverage suffix for formal validation', () => {
    const selection = selectFormalValidationSnapshots(
      [
        {
          date: '2026/04/20 09:30',
          snapshot: {
            type: 'quarter_hour',
            hotlist: [{ code: '600000', rank: 1, price: 9.8 }],
          },
        },
        {
          date: '2026/04/20 10:00',
          snapshot: {
            type: 'quarter_hour',
            hotlist: [],
          },
        },
        {
          date: '2026/04/20 10:30',
          snapshot: {
            type: 'quarter_hour',
            hotlist: [
              { code: '600001', rank: 1, compRank: 1, price: 10.2, platforms: 4, avgRankNum: 2 },
              { code: '600002', rank: 2, compRank: 2, price: 11.4, platforms: 5, avgRankNum: 3 },
              { code: '600003', rank: 3, compRank: 3, price: 9.8, platforms: 4, avgRankNum: 4 },
            ],
          },
        },
        {
          date: '2026/04/20 11:00',
          snapshot: {
            type: 'quarter_hour',
            hotlist: [
              { code: '600011', rank: 1, compRank: 1, price: 10.8, platforms: 4, avgRankNum: 2 },
              { code: '600012', rank: 2, compRank: 2, price: 12.1, platforms: 5, avgRankNum: 3 },
              { code: '600013', rank: 3, compRank: 3, price: 9.3, platforms: 4, avgRankNum: 4 },
            ],
          },
        },
      ],
      2,
    )

    expect(selection.autoAdjusted).toBe(true)
    expect(selection.selectedCount).toBe(3)
    expect(selection.legacyCompatibleCount).toBe(1)
    expect(selection.emptyHotlistCount).toBe(1)
    expect(selection.selectedStartDate).toBe('2026/04/20 10:00')
    expect(selection.selectedEndDate).toBe('2026/04/20 11:00')
    expect(resolveSnapshotSeriesFeatureCoverage(selection.snapshots)).toBe('full')
  })

  it('keeps the requested window when the latest full suffix is too short', () => {
    const selection = selectFormalValidationSnapshots(
      [
        {
          date: '2026/04/20 09:30',
          snapshot: {
            type: 'quarter_hour',
            hotlist: [{ code: '600000', rank: 1, price: 9.8 }],
          },
        },
        {
          date: '2026/04/20 10:00',
          snapshot: {
            type: 'quarter_hour',
            hotlist: [
              { code: '600001', rank: 1, compRank: 1, price: 10.2, platforms: 4, avgRankNum: 2 },
              { code: '600002', rank: 2, compRank: 2, price: 11.4, platforms: 5, avgRankNum: 3 },
              { code: '600003', rank: 3, compRank: 3, price: 9.8, platforms: 4, avgRankNum: 4 },
            ],
          },
        },
      ],
      3,
    )

    expect(selection.autoAdjusted).toBe(false)
    expect(selection.requestedCount).toBe(2)
    expect(selection.selectedCount).toBe(2)
    expect(resolveSnapshotSeriesFeatureCoverage(selection.snapshots)).toBe('partial')
  })

  it('treats legacy snapshots with candidate-core fields as formal-validation compatible', () => {
    const coverage = resolveSnapshotFormalValidationCoverage(
      {
        type: 'quarter_hour',
        hotlist: [
          {
            code: '600001',
            rank: 1,
            price: 10.2,
            change: 4.1,
            speed: 1.2,
            turnover: 200_000_000,
            turnoverRate: 5.3,
            volumeRatio: 2.1,
            zlje: 30_000_000,
            zljzb: 6.5,
            cddje: 10_000_000,
            cddjzb: 2.4,
          },
          {
            code: '600002',
            rank: 2,
            price: 11.6,
            change: 3.7,
            speed: 0.8,
            turnover: 180_000_000,
            turnoverRate: 4.1,
            volumeRatio: 1.8,
            zlje: 25_000_000,
            zljzb: 5.9,
            cddje: 8_000_000,
            cddjzb: 2.1,
          },
        ],
      },
      2,
    )

    expect(coverage).toBe('legacy_core')
  })

  it('summarizes a legacy-core series as formally compatible', () => {
    const summary = summarizeSnapshotSeriesFormalValidationCoverage(
      [
        {
          date: '2026/04/20 09:30',
          snapshot: {
            type: 'quarter_hour',
            hotlist: [
              {
                code: '600001',
                rank: 1,
                price: 10.2,
                change: 4.1,
                speed: 1.2,
                turnover: 200_000_000,
                turnoverRate: 5.3,
                volumeRatio: 2.1,
                zlje: 30_000_000,
                zljzb: 6.5,
                cddje: 10_000_000,
                cddjzb: 2.4,
              },
            ],
          },
        },
        {
          date: '2026/04/20 10:00',
          snapshot: {
            type: 'quarter_hour',
            hotlist: [
              {
                code: '600002',
                rank: 2,
                price: 11.6,
                change: 3.7,
                speed: 0.8,
                turnover: 180_000_000,
                turnoverRate: 4.1,
                volumeRatio: 1.8,
                zlje: 25_000_000,
                zljzb: 5.9,
                cddje: 8_000_000,
                cddjzb: 2.1,
              },
            ],
          },
        },
      ],
      1,
    )

    expect(summary.coverage).toBe('legacy_core')
    expect(summary.legacyCoreSnapshotCount).toBe(2)
    expect(summary.incompatibleSnapshotCount).toBe(0)
  })
})
