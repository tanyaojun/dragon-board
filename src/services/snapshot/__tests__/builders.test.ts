import { describe, expect, it } from 'vitest'

import { buildDailySnapshot, buildSnapshotStockRows } from '../builders'
import { createSnapshotRecord } from '../identity'

describe('snapshot builders', () => {
  it('slims daily raw snapshot payload and keeps required hotlist fact fields', () => {
    const snapshot = buildDailySnapshot({
      stocks: [
        {
          code: '600001',
          name: '主题材样本',
          compRank: 1,
          avgRank: '3.2',
          avgRankNum: 3.2,
          price: 12.34,
          change: 7.21,
          turnover: 320000000,
          turnoverRate: 11.6,
          zlje: 56000000,
          volume: 120000,
          volumeRatio: 1.8,
          leadStatus: '龙一',
          lianbanStr: '2连板',
          fengdan: 8600,
          pe: 18.2,
          pb: 3.4,
          mainTheme: '电力',
          themeHeat: 83,
          themeLevel: '热门',
          moneyFlowSource: 'qmt_l2',
          moneyFlowEstimated: false,
          capitalFlowSource: 'broker_l2',
          capitalFlowConfidence: 'high',
          themes: [{ id: 'POWER', name: '电力', heatScore: 83 }],
          tags: [{ Name: '旧标签' }],
          reason: '旧原因',
          rankChange: 5,
          technicalIndicators: { macd: 1 },
          signals: { final: { signal: 'buy', confidence: 0.8 } },
        },
      ],
      breathData: { overall: 62, phase: '修复', phaseName: '修复期' },
      marketData: {
        upCount: 3200,
        downCount: 1700,
        ztCount: 68,
        dtCount: 4,
        totalAmo: 123456789,
        yesterdayZtPerformance: 1.2,
        moneyFlow: { main: 12, retail: -8 },
        indices: {},
        limitData: { yiban: 40, erban: 16, sanban: 8, sibanPlus: 4 },
        zhaban: {},
        yesterdayLimit: {},
      },
      jxbkBlocks: [],
      jxbkStocks: {},
      hotThemes: [
        {
          name: '电力',
          heatScore: 83,
          heatLevel: '热门',
          ztCount: 4,
          leaderCount: 2,
        },
      ],
      rotationAnalysis: {
        marketPhase: '主升',
        rotationSpeed: 0.8,
        summary: { suggestion: '聚焦主线' },
      },
      breathHistory: [],
      breathFactors: [],
      marketMode: 'full',
      stocksVersion: 1,
    })

    expect(snapshot).not.toHaveProperty('hotThemes')
    expect(snapshot).not.toHaveProperty('leaders')
    expect(snapshot).not.toHaveProperty('limitUpStocks')
    expect(snapshot.rotationSummary).toMatchObject({
      marketPhase: '主升',
      rotationSpeed: 0.8,
      suggestion: '聚焦主线',
    })
    expect(snapshot.hotlist[0]).toMatchObject({
      code: '600001',
      avgRank: '3.2',
      avgRankNum: 3.2,
      pe: 18.2,
      pb: 3.4,
      mainTheme: '电力',
      themeHeat: 83,
      themeLevel: '热门',
      moneyFlowSource: 'qmt_l2',
      moneyFlowEstimated: false,
      capitalFlowSource: 'broker_l2',
      capitalFlowConfidence: 'high',
      themes: [{ id: 'POWER', name: '电力', heatScore: 83 }],
      reason: '旧原因',
    })
    expect(snapshot.hotlist[0]).not.toHaveProperty('tags')
    expect(snapshot.hotlist[0]).not.toHaveProperty('signals')
    expect(snapshot.hotlist[0]).not.toHaveProperty('rankChange')
    expect(snapshot.hotlist[0]).not.toHaveProperty('technicalIndicators')
  })

  it('projects compact stock-row signal columns from legacy hotlist payload', () => {
    const record = createSnapshotRecord(
      'quarter_hour',
      new Date('2026-04-24T10:00:00'),
      {
        hotlist: [
          {
            code: '600001',
            name: '样本股',
            rank: 1,
            compRank: 1,
            avgRank: '3.0',
            avgRankNum: 3,
            pe: 18.2,
            pb: 3.4,
            rankChange: 4,
            signals: {
              direction: { signal: 'up', confidence: 0.7 },
              acceleration: { signal: 'up', confidence: 0.6 },
              cross: { signal: 'golden', confidence: 0.8 },
            final: { signal: 'buy', confidence: 0.9 },
            },
            moneyFlowSource: 'tdx_estimate',
            moneyFlowEstimated: true,
            capitalFlowSource: 'estimated_l1',
            capitalFlowConfidence: 'low',
            reason: '涨停原因样本',
          },
        ],
      },
    )

    const rows = buildSnapshotStockRows(record)

    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      code: '600001',
      avgRank: '3.0',
      avgRankNum: 3,
      pe: 18.2,
      pb: 3.4,
      rankChange: 4,
      directionSignal: 'up',
      directionConfidence: 0.7,
      accelerationSignal: 'up',
      accelerationConfidence: 0.6,
      crossSignal: 'golden',
      crossConfidence: 0.8,
      finalSignal: 'buy',
      finalConfidence: 0.9,
      moneyFlowSource: 'tdx_estimate',
      moneyFlowEstimated: true,
      capitalFlowSource: 'estimated_l1',
      capitalFlowConfidence: 'low',
      capital_flow_source: 'estimated_l1',
      capital_flow_confidence: 'low',
      money_flow_estimated: true,
      reason: '涨停原因样本',
    })
  })
})
