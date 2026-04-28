import { afterEach, describe, expect, it, vi } from 'vitest'

import { replaceProjectionBundleRows } from '../store'
import type { SnapshotProjectionBundle } from '../types'

type FakeRequest<T> = {
  result?: T
  error?: unknown
  onsuccess?: (() => void) | null
  onerror?: (() => void) | null
}

function createAsyncRequest<T>(factory: () => T): FakeRequest<T> {
  const request: FakeRequest<T> = {
    onsuccess: null,
    onerror: null,
  }
  queueMicrotask(() => {
    try {
      request.result = factory()
      request.onsuccess?.()
    } catch (error) {
      request.error = error
      request.onerror?.()
    }
  })
  return request
}

function createRecordStore(initialRows: Array<{ id: string; [key: string]: unknown }> = []) {
  const rows = new Map(initialRows.map((row) => [row.id, { ...row }]))
  return {
    rows,
    put: vi.fn((row: { id: string; [key: string]: unknown }) => {
      rows.set(row.id, { ...row })
    }),
    delete: vi.fn((id: string) => {
      rows.delete(id)
    }),
  }
}

function createSnapshotChildStore(initialRows: Array<{ id: string; snapshotId: string; [key: string]: unknown }> = []) {
  const rows = new Map(initialRows.map((row) => [row.id, { ...row }]))
  return {
    rows,
    put: vi.fn((row: { id: string; snapshotId: string; [key: string]: unknown }) => {
      rows.set(row.id, { ...row })
    }),
    delete: vi.fn((id: string) => {
      rows.delete(id)
    }),
    index: vi.fn((name: string) => {
      if (name !== 'snapshotId') {
        throw new Error(`unexpected_index:${name}`)
      }
      return {
        getAllKeys: (range: { value: string }) =>
          createAsyncRequest(() =>
            Array.from(rows.values())
              .filter((row) => row.snapshotId === range.value)
              .map((row) => row.id),
          ),
      }
    }),
  }
}

describe('replaceProjectionBundleRows', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('replaces stock and sector rows by snapshotId before writing the next bundle', async () => {
    vi.stubGlobal('IDBKeyRange', {
      only: (value: string) => ({ value }),
    })

    const snapshotStore = createRecordStore([
      { id: 'quarter_hour:2026-04-24:10:00', payloadVersion: 'old' },
      { id: 'quarter_hour:2026-04-24:10:15', payloadVersion: 'neighbor' },
    ])
    const frameStore = createRecordStore([
      { id: 'quarter_hour:2026-04-24:10:00', snapshotId: 'quarter_hour:2026-04-24:10:00', stockRowCount: 2 },
      { id: 'quarter_hour:2026-04-24:10:15', snapshotId: 'quarter_hour:2026-04-24:10:15', stockRowCount: 1 },
    ])
    const stockStore = createSnapshotChildStore([
      { id: 'quarter_hour:2026-04-24:10:00:600001', snapshotId: 'quarter_hour:2026-04-24:10:00', code: '600001' },
      { id: 'quarter_hour:2026-04-24:10:00:600002', snapshotId: 'quarter_hour:2026-04-24:10:00', code: '600002' },
      { id: 'quarter_hour:2026-04-24:10:15:600003', snapshotId: 'quarter_hour:2026-04-24:10:15', code: '600003' },
    ])
    const sectorStore = createSnapshotChildStore([
      {
        id: 'quarter_hour:2026-04-24:10:00:sector:BK001',
        snapshotId: 'quarter_hour:2026-04-24:10:00',
        entityKey: 'BK001',
      },
      {
        id: 'quarter_hour:2026-04-24:10:00:hot_theme:HT001',
        snapshotId: 'quarter_hour:2026-04-24:10:00',
        entityKey: 'HT001',
      },
      {
        id: 'quarter_hour:2026-04-24:10:15:sector:BK002',
        snapshotId: 'quarter_hour:2026-04-24:10:15',
        entityKey: 'BK002',
      },
    ])

    const bundle: SnapshotProjectionBundle = {
      record: {
        id: 'quarter_hour:2026-04-24:10:00',
        type: 'quarter_hour',
        tradingDate: '2026-04-24',
        slotTime: '10:00',
        timestamp: Date.parse('2026-04-24T10:00:00'),
        displayKey: '2026-04-24 10:00',
        captureMode: 'real_time',
        capturedAt: Date.parse('2026-04-24T10:00:05'),
        dataTimestamp: Date.parse('2026-04-24T10:00:00'),
        delayMs: 0,
        qualityFlags: [],
        source: 'browser_runtime',
        payload: { hotlist: [{ code: '600001' }] },
      },
      frame: {
        id: 'quarter_hour:2026-04-24:10:00',
        snapshotId: 'quarter_hour:2026-04-24:10:00',
        type: 'quarter_hour',
        tradingDate: '2026-04-24',
        slotTime: '10:00',
        timestamp: Date.parse('2026-04-24T10:00:00'),
        displayKey: '2026-04-24 10:00',
        captureMode: 'real_time',
        source: 'browser_runtime',
        qualityFlags: [],
        delayMs: 0,
        metadata: null,
        marketStats: null,
        sentiment: null,
        moneyFlow: null,
        indices: null,
        limitSummary: null,
        rotationSummary: null,
        stockRowCount: 1,
        sectorRowCount: 1,
      },
      stockRows: [
        {
          id: 'quarter_hour:2026-04-24:10:00:600001',
          snapshotId: 'quarter_hour:2026-04-24:10:00',
          type: 'quarter_hour',
          tradingDate: '2026-04-24',
          slotTime: '10:00',
          timestamp: Date.parse('2026-04-24T10:00:00'),
          captureMode: 'real_time',
          source: 'browser_runtime',
          code: '600001',
          name: '样本股',
          rank: 1,
          compRank: 1,
          platforms: 0,
          avgRankNum: 0,
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
          pe: 0,
          pb: 0,
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
          rankChange: 3,
          directionSignal: 'buy',
          directionConfidence: 0.8,
          accelerationSignal: 'buy',
          accelerationConfidence: 0.7,
          crossSignal: 'golden',
          crossConfidence: 0.6,
          finalSignal: 'buy',
          finalConfidence: 0.9,
        },
      ],
      sectorRows: [
        {
          id: 'quarter_hour:2026-04-24:10:00:sector:BK001',
          snapshotId: 'quarter_hour:2026-04-24:10:00',
          type: 'quarter_hour',
          tradingDate: '2026-04-24',
          slotTime: '10:00',
          timestamp: Date.parse('2026-04-24T10:00:00'),
          captureMode: 'real_time',
          source: 'browser_runtime',
          entityType: 'sector',
          entityKey: 'BK001',
          entityName: '电力',
          rank: 1,
          strength: 80,
          heatScore: 80,
          change: 2,
        },
      ],
    }

    await replaceProjectionBundleRows(
      snapshotStore as any,
      frameStore as any,
      stockStore as any,
      sectorStore as any,
      [bundle],
    )

    expect(Array.from(stockStore.rows.keys()).sort()).toEqual([
      'quarter_hour:2026-04-24:10:00:600001',
      'quarter_hour:2026-04-24:10:15:600003',
    ])
    expect(Array.from(sectorStore.rows.keys()).sort()).toEqual([
      'quarter_hour:2026-04-24:10:00:sector:BK001',
      'quarter_hour:2026-04-24:10:15:sector:BK002',
    ])
    expect(snapshotStore.rows.get('quarter_hour:2026-04-24:10:00')).toMatchObject({
      payload: { hotlist: [{ code: '600001' }] },
    })
    expect(snapshotStore.rows.get('quarter_hour:2026-04-24:10:00')).not.toHaveProperty('payloadVersion')
    expect(frameStore.rows.get('quarter_hour:2026-04-24:10:00')).toMatchObject({
      stockRowCount: 1,
      sectorRowCount: 1,
    })
  })
})
