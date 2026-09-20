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

  it('sorts lifecycle opportunity by stage order then score within group', () => {
    // 2026-09-19 修复：周期列显示 stage（点火/扩散/拥挤/反转/冷却），排序值必须与显示
    // 同字段——按生命周期阶段序数聚簇（点火>扩散>拥挤>反转>冷却），不再按 signalTier
    // （tier 与 stage 是两套轴，tier 排序会让同档内 stage 交错，看起来"排序不正确"）。
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '扩散低分', rankTrend: { observation: { lifecycle: { stage: 'expansion', score: 30 } } } },
      { code: '000002', name: '点火', rankTrend: { observation: { lifecycle: { stage: 'ignition', score: 80 } } } },
      { code: '000003', name: '扩散高分', rankTrend: { observation: { lifecycle: { stage: 'expansion', score: 90 } } } },
      { code: '000004', name: '缺失', rankTrend: { observation: {} } },
    ])

    // asc（↑）：低阶段在前 → 扩散组（组内分值升序 30<90）→ 点火 → 缺失最后
    uiStore.toggleSort('lifecycleOpportunity')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000001', '000003', '000002', '000004'])

    // desc（↓）：点火在前 → 扩散组（组内分值降序 90>30）→ 缺失仍最后
    uiStore.toggleSort('lifecycleOpportunity')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000003', '000001', '000004'])
  })

  it('keeps missing limit-up fields last and distinct from real zero when sorting limit-up columns', () => {
    // 2026-09-02 涨停相关列：缺失（非涨停/未覆盖）与真实 0（封单 0、开板 0）语义不同，
    // 缺失恒排最后（fail-visible），不得与 0 混排
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '非涨停', change: 3.2 }, // fengdan 缺失
      { code: '000002', name: '零封单', change: 10.01, fengdan: 0 }, // 真实 0
      { code: '000003', name: '有封单', change: 10.02, fengdan: 42000000 },
    ])

    uiStore.toggleSort('fengdan')

    // 首次点击 = asc：真实 0 > 有封单；缺失恒最后
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000003', '000001'])

    uiStore.toggleSort('fengdan')

    // desc：有封单 > 真实 0 > 缺失
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000002', '000001'])
  })

  it('sorts first limit-up time chronologically and keeps missing rows last in both directions', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '缺失' },
      { code: '000002', name: '早板', firstZtTime: '09:25:00' },
      { code: '000003', name: '晚板', firstZtTime: '13:52:00' },
    ])

    uiStore.toggleSort('firstZtTime')

    // 首次点击 = asc：早板在前；缺失恒最后（缺失按字符串回退时 '0' 前缀会混进最前 → 需按缺失处理）
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000002', '000003', '000001'])

    uiStore.toggleSort('firstZtTime')

    // desc：晚板在前；缺失仍最后
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000002', '000001'])
  })

  it('sorts lifecycle opportunity by stage (display field), not signalTier', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '冷却高分', _lifecyclePct: 91, rankTrend: { observation: { lifecycle: { signalTier: 'D', stage: 'cooling', score: 91 } } } },
      { code: '000002', name: '扩散', _lifecyclePct: 63, rankTrend: { observation: { lifecycle: { signalTier: 'A', stage: 'expansion', score: 63 } } } },
      { code: '000003', name: '点火', _lifecyclePct: 55, rankTrend: { observation: { lifecycle: { signalTier: 'A', stage: 'ignition', score: 55 } } } },
      { code: '000004', name: '拥挤', _lifecyclePct: 85, rankTrend: { observation: { lifecycle: { signalTier: 'D', stage: 'crowded', score: 85 } } } },
    ])

    // asc（↑）：冷却(1) → 拥挤(3) → 扩散(4) → 点火(5)；stage 与 tier 矛盾时以显示的 stage 为准
    uiStore.toggleSort('lifecycleOpportunity')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000001', '000004', '000002', '000003'])

    // desc（↓）：点火 → 扩散 → 拥挤 → 冷却
    uiStore.toggleSort('lifecycleOpportunity')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000002', '000004', '000001'])
  })

  it('keeps unknown/missing lifecycle stage last in both directions', () => {
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '无阶段', rankTrend: { observation: { lifecycle: { stage: null, score: 60 } } } },
      { code: '000002', name: '反转', rankTrend: { observation: { lifecycle: { stage: 'reversal', score: 40 } } } },
      { code: '000003', name: '冷却', rankTrend: { observation: { lifecycle: { stage: 'cooling', score: 70 } } } },
      { code: '000004', name: '无信号' },
    ])

    // asc（↑）：冷却(1) → 反转(2)；无阶段/缺失(null) 恒最后，不伪装成任何阶段
    uiStore.toggleSort('lifecycleOpportunity')
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000002', '000001', '000004'])

    // desc（↓）：反转 → 冷却；无阶段/缺失仍最后
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

  it('sorts lifecycle opportunity by stage from _lifecycleStage projection fallback', () => {
    // 投影回退路径：只有 _lifecycleStage/_lifecyclePct、无 rankTrend.observation 的股票，
    // 排序同样按显示的 stage 序数聚簇（2026-09-19 修复）。
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '冷却高分', _lifecyclePct: 91, _lifecycleStage: 'cooling' },
      { code: '000002', name: '扩散', _lifecyclePct: 63, _lifecycleStage: 'expansion' },
      { code: '000003', name: '点火', _lifecyclePct: 55, _lifecycleStage: 'ignition' },
      { code: '000004', name: '拥挤', _lifecyclePct: 85, _lifecycleStage: 'crowded' },
    ])

    uiStore.toggleSort('lifecycleOpportunity')
    // asc（↑）：冷却(1) → 拥挤(3) → 扩散(4) → 点火(5)
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000001', '000004', '000002', '000003'])

    uiStore.toggleSort('lifecycleOpportunity')
    // desc（↓）：点火 → 扩散 → 拥挤 → 冷却（与列显示 stage 顺序一致）
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000002', '000004', '000001'])
  })

  it('sorts sample-insufficient stocks after all real stages in both directions', () => {
    // 2026-09-20 用户裁决：样本不足（meta.sampleQuality.status=insufficient）的股票
    // 显示覆盖标签「样本不足」，排序归末组——不得按其底层 stage 混入真实阶段聚簇
    // （实测：降序时「样本不足」插在点火组中间，观感即排序错误）。
    const uiStore = useUIStore()
    dataLayer.setMergedStocks([
      { code: '000001', name: '点火正常', rankTrend: { observation: { lifecycle: { stage: 'ignition', score: 80 } } } },
      { code: '000002', name: '样本不足但底层点火', rankTrend: { meta: { sampleQuality: { status: 'insufficient' } }, observation: { lifecycle: { stage: 'ignition', score: 95 } } } },
      { code: '000003', name: '扩散', rankTrend: { observation: { lifecycle: { stage: 'expansion', score: 60 } } } },
      { code: '000004', name: '样本不足底层冷却', rankTrend: { meta: { sampleQuality: { status: 'insufficient' } }, observation: { lifecycle: { stage: 'cooling', score: 40 } } } },
    ])

    uiStore.toggleSort('lifecycleOpportunity')
    // asc（↑）：扩散(4) → 点火(5)；两只样本不足归末组（组内 score 升序 40<95）
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000003', '000001', '000004', '000002'])

    uiStore.toggleSort('lifecycleOpportunity')
    // desc（↓）：点火 → 扩散 → 末组（样本不足，组内 score 降序 95>40）
    expect(uiStore.sortedStocks.map((stock) => stock.code)).toEqual(['000001', '000003', '000002', '000004'])
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
