import { describe, expect, it } from 'vitest'

import { buildDailySnapshot, buildSnapshotFrameRow, buildSnapshotStockRows } from '../builders'
import { createSnapshotRecord } from '../identity'

describe('snapshot builders', () => {
  it('excludes runtime THS fund fields from formal snapshot payloads', () => {
    const snapshot = buildDailySnapshot({
      stocks: [{
        code: '000001',
        name: '运行态资金样本',
        zlje: 88_000_000,
        zljzb: 8.8,
        cddje: 30_000_000,
        cddjzb: 3,
        moneyFlowSource: 'ths_main_monitor',
        moneyFlowEstimated: false,
        capitalFlowSource: 'ths_main_monitor',
        capitalFlowConfidence: 'high',
      }],
      hotThemes: [],
      breathHistory: [],
      breathFactors: [],
    } as any)

    expect(snapshot.hotlist[0]).not.toHaveProperty('zlje')
    expect(snapshot.hotlist[0]).not.toHaveProperty('zljzb')
    expect(snapshot.hotlist[0]).not.toHaveProperty('cddje')
    expect(snapshot.hotlist[0]).not.toHaveProperty('cddjzb')
    expect(snapshot.hotlist[0]).not.toHaveProperty('moneyFlowSource')
    expect(snapshot.hotlist[0]).not.toHaveProperty('capitalFlowSource')
  })

  it('slims daily raw snapshot payload and keeps required hotlist fact fields', () => {
    const snapshot = buildDailySnapshot({
      stocks: [
        {
          code: '600001',
          name: '主题材样本',
          compRank: 1,
          platforms: 3,
          avgRank: '3.2',
          avgRankNum: 3.2,
          emRank: 4,
          thsRank: 2,
          kplRank: 9,
          tdxRank: 999,
          xqRank: 999,
          clsRank: 999,
          tgbRank: 999,
          dzhRank: 999,
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
        thsLimitUpPools: {
          source: 'ths-limitup-pools',
          degraded: false,
          errors: [],
          poolCounts: {
            one: 40,
            two: 16,
            three: 8,
            four: 4,
            high: 2,
            failed: 6,
            rushing: 5,
            drawdown: 3,
          },
          failedCount: 6,
          rushingCount: 5,
          drawdownCount: 3,
          drawdownRiskLabel: '涨停股回撤榜',
          maxDrawdown: -11.2,
          avgDrawdown: -5.6,
        },
      },
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
      compRank: 1,
      platforms: 3,
      emRank: 4,
      thsRank: 2,
      kplRank: 9,
      tdxRank: 999,
      xqRank: 999,
      clsRank: 999,
      tgbRank: 999,
      dzhRank: 999,
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

    expect(snapshot.limitSummary.thsPools).toMatchObject({
      failedCount: 6,
      drawdownCount: 3,
      drawdownRiskLabel: '涨停股回撤榜',
    })

    const frame = buildSnapshotFrameRow(createSnapshotRecord('daily', new Date('2026-04-24T15:00:00'), snapshot))
    expect(frame?.limitSummary.thsPools).toMatchObject({
      failedCount: 6,
      drawdownCount: 3,
      drawdownRiskLabel: '涨停股回撤榜',
    })
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
            platforms: 2,
            avgRank: '3.0',
            avgRankNum: 3,
            emRank: 5,
            thsRank: 7,
            kplRank: 999,
            tdxRank: 999,
            xqRank: 999,
            clsRank: 999,
            tgbRank: 999,
            dzhRank: 999,
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
      platforms: 2,
      emRank: 5,
      thsRank: 7,
      kplRank: 999,
      tdxRank: 999,
      xqRank: 999,
      clsRank: 999,
      tgbRank: 999,
      dzhRank: 999,
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

  it('strips runtime THS funds while projecting formal stock rows', () => {
    const record = createSnapshotRecord(
      'half_hour',
      new Date('2026-07-24T15:00:00'),
      {
        hotlist: [{
          code: '000001',
          name: '运行态资金样本',
          zlje: 88_000_000,
          moneyFlowSource: 'ths_main_monitor',
          capitalFlowSource: 'ths_main_monitor',
        }],
      },
    )

    const rows = buildSnapshotStockRows(record)

    expect(rows[0].zlje).toBe(0)
    expect(rows[0].moneyFlowSource).toBeUndefined()
    expect(rows[0].capitalFlowSource).toBeUndefined()
    expect(rows[0].money_flow_source).toBeUndefined()
  })
})
