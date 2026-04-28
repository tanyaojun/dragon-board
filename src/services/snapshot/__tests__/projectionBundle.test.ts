import { describe, expect, it } from 'vitest'

import { createSnapshotRecord } from '../identity'
import { buildCanonicalProjectionBundle } from '../projectionBundle'
import type { SnapshotStockRow } from '../types'

describe('buildCanonicalProjectionBundle', () => {
  it('preserves existing lightweight signal columns when raw hotlist no longer carries them', () => {
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
            avgRank: '2.8',
            avgRankNum: 2.8,
            pe: 18.2,
            pb: 3.4,
            price: 12.3,
          },
        ],
      },
      {
        captureMode: 'delayed',
      },
    )

    const existingRow: SnapshotStockRow = {
      id: 'legacy-row',
      snapshotId: 'legacy-snapshot',
      type: 'quarter_hour',
      tradingDate: '2026-04-01',
      slotTime: '09:45',
      timestamp: Date.parse('2026-04-01T09:45:00'),
      captureMode: 'real_time',
      source: 'browser_runtime',
      code: '600001',
      name: '样本股',
      rank: 3,
      compRank: 3,
      platforms: 0,
      avgRank: '3.0',
      avgRankNum: 3,
      price: 10,
      change: 0,
      volume: 100,
      turnover: 0,
      turnoverRate: 0,
      totalMV: 0,
      cirMV: 0,
      zlje: 0,
      zljzb: 0,
      cddje: 0,
      cddjzb: 0,
      pe: 18,
      pb: 3,
      volumeRatio: 0,
      speed: 0,
      leadStatus: '',
      leadTimes: 0,
      lianbanStr: '',
      fengdan: 0,
      maxFengdan: 0,
      popularity: 0,
      popularityChange: 0,
      institutionBuy: 0,
      bigMoney300: 0,
      themes: [],
      isNew: false,
      firstZtTime: '',
      lastZtTime: '',
      boardHeight: 0,
      highDays: 0,
      hotness: 0,
      rankChange: 7,
      directionSignal: 'buy',
      directionConfidence: 0.88,
      accelerationSignal: 'buy',
      accelerationConfidence: 0.76,
      crossSignal: 'golden',
      crossConfidence: 0.63,
      finalSignal: 'buy',
      finalConfidence: 0.92,
    }

    const bundle = buildCanonicalProjectionBundle(record, {
      existingStockRows: [existingRow],
    })

    expect(bundle.stockRows).toHaveLength(1)
    expect(bundle.stockRows[0]).toMatchObject({
      id: `${record.id}:600001`,
      snapshotId: record.id,
      tradingDate: '2026-04-24',
      slotTime: '10:00',
      timestamp: Date.parse('2026-04-24T10:00:00'),
      captureMode: 'delayed',
      source: 'browser_runtime',
      code: '600001',
      rankChange: 7,
      directionSignal: 'buy',
      directionConfidence: 0.88,
      accelerationSignal: 'buy',
      accelerationConfidence: 0.76,
      crossSignal: 'golden',
      crossConfidence: 0.63,
      finalSignal: 'buy',
      finalConfidence: 0.92,
    })
  })
})
