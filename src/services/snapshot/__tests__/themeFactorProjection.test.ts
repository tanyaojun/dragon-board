import { describe, expect, it } from 'vitest'
import { buildSnapshotSectorRows, buildSnapshotStockRows } from '../builders'
import type { SnapshotRecord } from '../types'

function createRecord(payload: Record<string, any>): SnapshotRecord {
  return {
    id: 'half_hour:2026-04-22:10:00',
    type: 'half_hour',
    tradingDate: '2026-04-22',
    slotTime: '10:00',
    timestamp: 1713751200000,
    displayKey: '2026-04-22 10:00',
    captureMode: 'auto',
    source: 'runtime',
    payload,
    qualityFlags: [],
    delayMs: 0,
    createdAt: 1713751200000,
    updatedAt: 1713751200000,
  }
}

describe('theme factor snapshot projection', () => {
  it('preserves stock theme exposure fields in stock rows', () => {
    const record = createRecord({
      hotlist: [
        {
          code: '000001',
          name: '样本股',
          rank: 1,
          themes: [
            {
              id: 'AI',
              name: '人工智能',
              heatScore: 88,
              role: 'leader',
              exposureWeight: 1,
              themeContribution: 16.8,
              riskPenalty: 2,
            },
          ],
        },
      ],
    })

    const [row] = buildSnapshotStockRows(record)

    expect(row.themes?.[0]).toMatchObject({
      id: 'AI',
      name: '人工智能',
      heatScore: 88,
      role: 'leader',
      exposureWeight: 1,
      themeContribution: 16.8,
      riskPenalty: 2,
    })
    expect(row).toMatchObject({
      themeContribution: 16.8,
      themeRole: 'leader',
      themeExposureWeight: 1,
      themeRiskFlags: ['riskPenalty:2'],
    })
  })

  it('uses the strongest projected theme as stock primary theme', () => {
    const record = createRecord({
      hotlist: [
        {
          code: '000001',
          name: '样本股',
          rank: 1,
          themes: [
            {
              id: 'WEAK',
              name: '弱题材',
              role: 'follower',
              exposureWeight: 0.2,
              themeContribution: 3,
            },
            {
              id: 'STRONG',
              name: '强题材',
              role: 'leader',
              exposureWeight: 0.8,
              themeContribution: 13,
              riskPenalty: 1,
            },
          ],
        },
      ],
    })

    const [row] = buildSnapshotStockRows(record)

    expect(row).toMatchObject({
      themeContribution: 13,
      themeRole: 'leader',
      themeExposureWeight: 0.8,
      themeRiskFlags: ['riskPenalty:1'],
    })
  })

  it('stores theme factor fields in sector row metadata', () => {
    const record = createRecord({
      hotThemes: [
        {
          id: 'AI',
          name: '人工智能',
          heatScore: 88,
          momentumScore: 77,
          breadthScore: 64,
          fundScore: 82,
          leadershipScore: 72,
          correlationScore: 69,
          crowdingRisk: 21,
          persistenceScore: 90,
          rotationState: 'mainline',
          qualityFlags: [{ code: 'low_sample', level: 'info', message: '样本偏低' }],
        },
      ],
    })

    const [row] = buildSnapshotSectorRows(record)

    expect(row.entityType).toBe('hot_theme')
    expect(row.metadata?.themeFactor).toMatchObject({
      momentumScore: 77,
      breadthScore: 64,
      fundScore: 82,
      leadershipScore: 72,
      correlationScore: 69,
      crowdingRisk: 21,
      persistenceScore: 90,
      rotationState: 'mainline',
    })
    expect(row.metadata?.themeFactor.qualityFlags).toHaveLength(1)
    expect(row).toMatchObject({
      momentumScore: 77,
      breadthScore: 64,
      fundScore: 82,
      leadershipScore: 72,
      correlationScore: 69,
      crowdingRisk: 21,
      persistenceScore: 90,
      rotationState: 'mainline',
      themeQualityFlags: [{ code: 'low_sample', level: 'info', message: '样本偏低' }],
    })
  })

  it('leaves metadata null when no theme factor or explicit metadata exists', () => {
    const record = createRecord({
      hotThemes: [{ id: 'AI', name: '人工智能', heatScore: 88 }],
    })

    const [row] = buildSnapshotSectorRows(record)

    expect(row.metadata).toBeNull()
    expect(row.momentumScore).toBeUndefined()
    expect(row.themeQualityFlags).toEqual([])
  })

  it('stores partial theme factor fields without requiring the full factor payload', () => {
    const record = createRecord({
      hotThemes: [{ id: 'AI', name: '人工智能', heatScore: 88, rotationState: 'inflow' }],
    })

    const [row] = buildSnapshotSectorRows(record)

    expect(row.metadata?.themeFactor).toEqual({ rotationState: 'inflow' })
  })

  it('prefers top-level stable theme factor fields over legacy metadata payload', () => {
    const record = createRecord({
      hotThemes: [
        {
          id: 'AI',
          name: '人工智能',
          heatScore: 88,
          momentumScore: 77,
          metadata: {
            themeFactor: {
              momentumScore: 12,
              rotationState: 'outflow',
            },
          },
          rotationState: 'mainline',
        },
      ],
    })

    const [row] = buildSnapshotSectorRows(record)

    expect(row.momentumScore).toBe(77)
    expect(row.rotationState).toBe('mainline')
  })

  it('does not build sector rows from retired block cache fallback', () => {
    const record = createRecord({})
    const buildContext = {
      jxbkBlocks: [{ code: 'BKAI', name: '人工智能', strength: 88 }],
    } as any

    expect(buildSnapshotSectorRows(record, buildContext)).toEqual([])
  })

  it('writes complete API theme factors and preserves explicit null scores', () => {
    const record = createRecord({})
    const buildContext = {
      themeHeatFactors: [
        {
          themeId: 'POWER',
          themeName: '电力',
          rank: 2,
          rankEligible: false,
          heatScore: null,
          fundScore: null,
          netInflow: null,
          metadata: { quoteSource: 'tencent', fundSource: 'ths_l2' },
        },
      ],
    } as any

    expect(buildSnapshotSectorRows(record, buildContext)).toEqual([
      expect.objectContaining({
        entityType: 'hot_theme',
        entityKey: 'POWER',
        heatScore: null,
        fundScore: null,
        netInflow: null,
        metadata: expect.objectContaining({ quoteSource: 'tencent', fundSource: 'ths_l2' }),
      }),
    ])
  })

  it('strips runtime THS funds and fund metadata from formal sector rows', () => {
    const record = createRecord({})
    const buildContext = {
      themeHeatFactors: [
        {
          themeId: 'AI',
          themeName: '人工智能',
          heatScore: 88,
          momentumScore: 76,
          fundScore: 82,
          mainNetInflow: 88_000_000,
          netInflow: 88_000_000,
          metadata: {
            quoteSource: 'tencent',
            fundSource: 'ths_main_monitor',
          },
        },
      ],
    } as any

    const [row] = buildSnapshotSectorRows(record, buildContext)

    expect(row.mainNetInflow).toBeUndefined()
    expect(row.netInflow).toBeUndefined()
    expect(row.fundScore).toBeUndefined()
    expect(row.momentumScore).toBe(76)
    expect(row.metadata).toEqual(expect.objectContaining({ quoteSource: 'tencent' }))
    expect(row.metadata).not.toHaveProperty('fundSource')
    expect(row.metadata?.themeFactor).not.toHaveProperty('fundScore')
  })

  it.each(['broker_l2', 'official_l2'])(
    'preserves formal %s funds in sector rows',
    (fundSource) => {
      const record = createRecord({})
      const buildContext = {
        themeHeatFactors: [
          {
            themeId: 'AI',
            themeName: '人工智能',
            heatScore: 88,
            fundScore: 82,
            netInflow: 88_000_000,
            metadata: { fundSource },
          },
        ],
      } as any

      const [row] = buildSnapshotSectorRows(record, buildContext)

      expect(row.netInflow).toBe(88_000_000)
      expect(row.fundScore).toBe(82)
      expect(row.metadata).toEqual(expect.objectContaining({ fundSource }))
      expect(row.metadata?.themeFactor).toEqual(expect.objectContaining({ fundScore: 82 }))
    },
  )
})
