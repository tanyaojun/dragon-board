import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { dataLayer } from '../../services/DataLayer'
import { AppEvents } from '../../types'
import { EventManager } from '../../utils/eventManager'
import { useUIStore } from '../ui'

describe('UIStore data version', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    dataLayer.reset()
  })

  it('reacts to DataLayer stock version notifications without data events', () => {
    vi.useFakeTimers()
    const uiStore = useUIStore()
    const dispose = uiStore.init()

    try {
      dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' }])

      expect(uiStore.dataVersion).toBe(0)

      vi.advanceTimersByTime(50)

      expect(uiStore.dataVersion).toBe(1)
      expect(uiStore.rawStocks).toEqual([expect.objectContaining({ code: '000001' })])
    } finally {
      dispose()
      dataLayer.reset()
      vi.useRealTimers()
    }
  })

  it('does not double-count when data event arrives before DataLayer version notification', () => {
    vi.useFakeTimers()
    const uiStore = useUIStore()
    const dispose = uiStore.init()

    try {
      dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' }])
      EventManager.emit(AppEvents.DATA.MERGED, { count: 1 })

      expect(uiStore.dataVersion).toBe(1)

      vi.advanceTimersByTime(50)

      expect(uiStore.dataVersion).toBe(1)
    } finally {
      dispose()
      dataLayer.reset()
      vi.useRealTimers()
    }
  })

  it('does not double-count when realtime data update arrives before DataLayer version notification', () => {
    vi.useFakeTimers()
    const uiStore = useUIStore()
    const dispose = uiStore.init()

    try {
      dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' }])
      EventManager.emit(AppEvents.DATA.UPDATED, { quotes: 1, source: 'tdx_l2' })

      expect(uiStore.dataVersion).toBe(1)

      vi.advanceTimersByTime(50)

      expect(uiStore.dataVersion).toBe(1)
    } finally {
      dispose()
      dataLayer.reset()
      vi.useRealTimers()
    }
  })
})

describe('UIStore table sorting', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    dataLayer.reset()
  })

  it('sorts rank-trend strength by the displayed observation score', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '低强度', _rankTrendPct: 18 },
      { code: '000002', name: '高强度', _rankTrendPct: 84 },
      { code: '000003', name: '中强度', rankTrend: { observation: { rankTrend: { score: 56 } } } },
    ])

    uiStore.toggleSort('rankTrendStrength')

    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000001', '000003', '000002'])

    uiStore.toggleSort('rankTrendStrength')

    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000003', '000001'])
  })

  it('sorts lifecycle opportunity by the displayed observation score', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '低成熟', _lifecyclePct: 21 },
      { code: '000002', name: '高成熟', _lifecyclePct: 91 },
      { code: '000003', name: '中成熟', rankTrend: { observation: { lifecycle: { score: 63 } } } },
    ])

    uiStore.toggleSort('lifecycleOpportunity')

    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000001', '000003', '000002'])
  })

  it('keeps missing observation scores after real values in both sort directions', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '缺失' },
      { code: '000002', name: '低强度', _rankTrendPct: 18 },
      { code: '000003', name: '高强度', _rankTrendPct: 84 },
    ])

    uiStore.toggleSort('rankTrendStrength')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000003', '000001'])

    uiStore.toggleSort('rankTrendStrength')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000002', '000001'])
  })

  it('does not substitute candidate-pool score when resonance is missing', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '缺失共振', candidatePoolProjection: { entryDecision: {} } },
      { code: '000002', name: '真实共振', _resonancePct: 18 },
    ])

    uiStore.toggleSort('resonanceIntensity')

    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000001'])
  })

  it('sorts resonance intensity direction-first: buy above sell regardless of score', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      {
        code: '000001',
        name: '下降高分',
        _resonancePct: 90,
        rankTrend: { resonance: { status: 'ok', direction: 'sell', score: 90 } },
      },
      {
        code: '000002',
        name: '上升低分',
        _resonancePct: 20,
        rankTrend: { resonance: { status: 'ok', direction: 'buy', score: 20 } },
      },
      {
        code: '000003',
        name: '上升高分',
        _resonancePct: 88,
        rankTrend: { resonance: { status: 'ok', direction: 'buy', score: 88 } },
      },
    ])

    uiStore.toggleSort('resonanceIntensity')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000003', '000001'])

    uiStore.toggleSort('resonanceIntensity')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000002', '000001'])
  })

  it('sorts rank-trend strength direction-first: buy above sell regardless of score', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '下降30', _rankTrendPct: 30, _rankTrendDirection: 'sell' },
      { code: '000002', name: '上升20', _rankTrendPct: 20, _rankTrendDirection: 'buy' },
      { code: '000003', name: '上升90', _rankTrendPct: 90, _rankTrendDirection: 'buy' },
    ])

    uiStore.toggleSort('rankTrendStrength')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000003', '000001'])

    uiStore.toggleSort('rankTrendStrength')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000002', '000001'])
  })

  it('sorts lifecycle opportunity direction-first by attention stage', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '冷却高分', _lifecyclePct: 91, _lifecycleStage: 'cooling' },
      { code: '000002', name: '扩散', _lifecyclePct: 63, _lifecycleStage: 'expansion' },
      { code: '000003', name: '点火', _lifecyclePct: 55, _lifecycleStage: 'ignition' },
      { code: '000004', name: '拥挤', _lifecyclePct: 85, _lifecycleStage: 'crowded' },
    ])

    uiStore.toggleSort('lifecycleOpportunity')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000002', '000004', '000001'])

    uiStore.toggleSort('lifecycleOpportunity')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000003', '000001', '000004'])
  })

  it('keeps missing observation direction between up and down groups in both sort directions', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '无方向', _rankTrendPct: 50 },
      { code: '000002', name: '上升', _rankTrendPct: 20, _rankTrendDirection: 'buy' },
      { code: '000003', name: '下降', _rankTrendPct: 80, _rankTrendDirection: 'sell' },
    ])

    uiStore.toggleSort('rankTrendStrength')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000001', '000003'])

    uiStore.toggleSort('rankTrendStrength')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000001', '000003'])
  })

  it('uses the three observation columns in the default table view', () => {
    const uiStore = useUIStore()

    expect(uiStore.view.showColumns).toEqual(
      expect.arrayContaining(['resonanceIntensity', 'rankTrendStrength', 'lifecycleOpportunity']),
    )
    expect(uiStore.view.showColumns).not.toEqual(expect.arrayContaining(['rankChange', 'confidence']))
  })
})
