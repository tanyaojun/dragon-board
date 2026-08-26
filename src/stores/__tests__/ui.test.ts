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

  it('sorts synergy tier by tier level (↑asc=低档在前、↓desc=高档在前)', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: 'D档', rankTrend: { observation: { synergy: { signalTier: 'D' } } } },
      { code: '000002', name: 'B档', rankTrend: { observation: { synergy: { signalTier: 'B' } } } },
      { code: '000003', name: 'S档', rankTrend: { observation: { synergy: { signalTier: 'S' } } } },
      { code: '000004', name: '缺失', rankTrend: { observation: {} } },
    ])

    // asc（↑）：低档在前 → D(1) < B(3) < S(5)，缺失排最后
    uiStore.toggleSort('synergyTier')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000001', '000002', '000003', '000004'])

    // desc（↓）：高档在前 → S(5) > B(3) > D(1)，缺失仍最后
    uiStore.toggleSort('synergyTier')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000002', '000001', '000004'])
  })

  it('keeps missing/unknown synergy tier after real tiers in both directions', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: 'E档', rankTrend: { observation: { synergy: { signalTier: 'E' } } } },
      { code: '000002', name: 'A档', rankTrend: { observation: { synergy: { signalTier: 'A' } } } },
      { code: '000003', name: 'unknown', rankTrend: { observation: { synergy: { signalTier: 'unknown' } } } },
    ])

    uiStore.toggleSort('synergyTier')
    // asc：E(0) < A(4)，unknown(null) 排最后
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000001', '000002', '000003'])

    uiStore.toggleSort('synergyTier')
    // desc：A(4) > E(0)，unknown(null) 仍最后
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000001', '000003'])
  })

  it('sorts lifecycle opportunity by tier groups then score within group', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: 'A档低分', rankTrend: { observation: { lifecycle: { signalTier: 'A', score: 30 } } } },
      { code: '000002', name: 'B档', rankTrend: { observation: { lifecycle: { signalTier: 'B', score: 80 } } } },
      { code: '000003', name: 'A档高分', rankTrend: { observation: { lifecycle: { signalTier: 'A', score: 90 } } } },
      { code: '000004', name: '缺失', rankTrend: { observation: {} } },
    ])

    // asc（↑）：低档在前 → B(3) < A(4)，同档组内分值升序，缺失最后
    uiStore.toggleSort('lifecycleOpportunity')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000001', '000003', '000004'])

    // desc（↓）：高档在前 → A 组（组内分值降序 90 前）> B 组，缺失仍最后
    uiStore.toggleSort('lifecycleOpportunity')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000001', '000002', '000004'])
  })

  it('sorts lifecycle opportunity by tier (stage-derived), not direction group', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '冷却高分', _lifecyclePct: 91, rankTrend: { observation: { lifecycle: { signalTier: 'D', stage: 'cooling', score: 91 } } } },
      { code: '000002', name: '扩散', _lifecyclePct: 63, rankTrend: { observation: { lifecycle: { signalTier: 'A', stage: 'expansion', score: 63 } } } },
      { code: '000003', name: '点火', _lifecyclePct: 55, rankTrend: { observation: { lifecycle: { signalTier: 'A', stage: 'ignition', score: 55 } } } },
      { code: '000004', name: '拥挤', _lifecyclePct: 85, rankTrend: { observation: { lifecycle: { signalTier: 'D', stage: 'crowded', score: 85 } } } },
    ])

    // asc（↑）：D 档(1) 组在前（组内分值升序 85<91），A 档(4) 组在后（55<63）
    uiStore.toggleSort('lifecycleOpportunity')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000004', '000001', '000003', '000002'])

    // desc（↓）：A 档组在前（组内分值降序 63>55），D 档组在后（91>85）
    uiStore.toggleSort('lifecycleOpportunity')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000003', '000001', '000004'])
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
    // desc：方向组固定（buy/up 恒前），组内降序 → [上升88, 上升20, 下降90]
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
    // desc：方向组固定（buy/up 恒前），组内降序 → [上升90, 上升20, 下降30]
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000002', '000001'])
  })

  it('sorts volume-price direction-first: up above down regardless of score (与三指标一致)', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      {
        code: '000001',
        name: '下降高分',
        _volumePriceScore: 90,
        _volumePriceDirection: 'down',
      },
      {
        code: '000002',
        name: '上升低分',
        _volumePriceScore: 20,
        _volumePriceDirection: 'up',
      },
      {
        code: '000003',
        name: '上升高分',
        _volumePriceScore: 88,
        _volumePriceDirection: 'up',
      },
    ])

    uiStore.toggleSort('volumePriceQuadrant')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000003', '000001'])

    uiStore.toggleSort('volumePriceQuadrant')
    // desc：方向组固定（buy/up 恒前），组内降序 → [上升88, 上升20, 下降90]
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000002', '000001'])
  })

  it('sorts cross section by percentile direction-first (方向+数值%)', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '低位', rankTrend: { observation: { crossSection: { percentile: 20 } } } },
      { code: '000002', name: '高位', rankTrend: { observation: { crossSection: { percentile: 88 } } } },
      { code: '000003', name: '中位', rankTrend: { observation: { crossSection: { percentile: 55 } } } },
    ])

    uiStore.toggleSort('crossSection')
    // direction-first：pct<50 归 down 组（后），pct≥50 归 up 组（前）；组内 asc 升序
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000002', '000001'])

    uiStore.toggleSort('crossSection')
    // desc：方向组固定（pct≥50 的 up 组恒前），组内降序 → [高位88, 中位55, 低位20]
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000003', '000001'])
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
    // desc：方向组随 order 反转（冷却/拥挤下降组在前），组内降序 → [冷却91, 拥挤85, 扩散63, 点火55]
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000001', '000004', '000002', '000003'])
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
    // desc：方向组固定（buy 恒前），组内降序 → [上升20, 无方向50, 下降80]
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
