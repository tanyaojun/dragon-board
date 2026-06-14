import { describe, expect, it } from 'vitest'
import { analyzeTradingPoolCandidate } from '../TradingPoolAnalysisService'
import type { TradingPoolStatus } from '../types'

describe('TradingPool status contract', () => {
  it('keeps the V1 status vocabulary explicit', () => {
    const statuses: TradingPoolStatus[] = [
      '观察买点',
      '准备介入',
      '已介入',
      '持仓观察',
      '观察中',
      '已退出',
      '已完成',
    ]

    expect(statuses).toContain('观察买点')
    expect(statuses).toContain('观察中')
    expect(statuses).toContain('已退出')
  })
})

describe('TradingPoolAnalysisService', () => {
  it('returns an empty result for empty candidate input', () => {
    const result = analyzeTradingPoolCandidate({ candidates: [] })

    expect(result).toEqual({ rows: [], staleCount: 0, exitedCount: 0 })
  })

  it('skips candidates without a usable stock code', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '',
          rankTrend: {
            jump: { confidence: 0.9 },
          },
        },
      ],
    })

    expect(result.rows).toEqual([])
  })

  it('treats an explicitly undefined rankTrend as stale instead of fresh', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: undefined,
        },
      ],
    })

    expect(result.rows[0].decision).toBe('stale')
    expect(result.rows[0].signalSnapshot.dataQuality).toBe('stale')
    expect(result.rows[0].signalSnapshot.directionSignal).toBeNull()
  })

  it('uses real nested RankTrend paths and enters on full resonance', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          name: '东材科技',
          rankTrend: {
            jump: { confidence: 0.88 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'buy' },
                zeroCross: { signal: 'buy' },
              },
            },
          },
        },
        {
          code: '300433',
          name: '蓝思科技',
          rankTrend: {
            jump: { confidence: 0.95 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'hold' },
                zeroCross: { signal: 'hold' },
              },
            },
          },
        },
      ],
    })

    expect(result.rows.map((item) => [item.code, item.status, item.decision])).toEqual([
      ['601208', '观察买点', 'enter'],
      ['300433', '观察中', 'watch'],
    ])
    expect(result.rows[0].signalSnapshot).toMatchObject({
      jumpConfidence: 0.88,
      macdCross: 'golden',
      directionSignal: 'buy',
      accelerationSignal: 'buy',
      zeroCrossSignal: 'buy',
      momentumSyncBroken: false,
      lifecycleAction: null,
      dataQuality: 'fresh',
    })
    expect(result.rows[0].reasons).toContain('signal_resonance')
    expect(result.rows[1].reasons).toContain('resonance_incomplete')
    expect(result.staleCount).toBe(0)
    expect(result.exitedCount).toBe(0)
  })

  it('falls back to compat fields when nested RankTrend technical signals are absent', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          name: '东材科技',
          rankTrend: {
            jump: { confidence: 0.88 },
            technical: {},
          },
          directionSignal: 'buy',
          accelerationSignal: 'buy',
          crossSignal: 'buy',
          macdCross: 'golden',
        },
      ],
    })

    expect(result.rows[0]).toMatchObject({
      code: '601208',
      status: '观察买点',
      decision: 'enter',
    })
    expect(result.rows[0].signalSnapshot).toMatchObject({
      directionSignal: 'buy',
      accelerationSignal: 'buy',
      zeroCrossSignal: 'buy',
      macdCross: 'golden',
      jumpConfidence: 0.88,
      dataQuality: 'fresh',
    })
  })

  it('uses the compat jump confidence when nested jump confidence is absent', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'buy' },
                zeroCross: { signal: 'buy' },
              },
            },
          },
          jumpConfidence: 0.86,
        },
      ],
    })

    expect(result.rows[0].decision).toBe('enter')
    expect(result.rows[0].signalSnapshot.jumpConfidence).toBe(0.86)
  })

  it('exits immediately on lifecycle veto', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            cycle: { decision: { action: 'veto' } },
            jump: { confidence: 0.91 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'buy' },
                zeroCross: { signal: 'buy' },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('已退出')
    expect(result.rows[0].decision).toBe('exit')
    expect(result.rows[0].reasons).toContain('lifecycle_veto')
  })

  it('exits when MACD death cross combines with at least two hard exit reasons', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '002129',
          rankTrend: {
            jump: { confidence: 0.73 },
            technical: {
              macd: { cross: 'death' },
              signals: {
                direction: { signal: 'hold' },
                acceleration: { signal: 'hold' },
                zeroCross: { signal: 'sell' },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('已退出')
    expect(result.rows[0].decision).toBe('exit')
    expect(result.rows[0].reasons).toEqual(expect.arrayContaining(['macd_death_cross', 'direction_weak', 'zero_cross_sell']))
    expect(result.exitedCount).toBe(1)
  })

  it('downgrades when jump confidence weakens', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            jump: { confidence: 0.62 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'buy' },
                zeroCross: { signal: 'buy' },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('观察中')
    expect(result.rows[0].decision).toBe('downgrade')
    expect(result.rows[0].reasons).toContain('jump_confidence_low')
  })

  it('downgrades when momentum sync is broken', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            jump: { confidence: 0.91 },
            technical: {
              momentumProfile: { syncBroken: true },
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'buy' },
                zeroCross: { signal: 'buy' },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('观察中')
    expect(result.rows[0].decision).toBe('downgrade')
    expect(result.rows[0].reasons).toContain('momentum_sync_broken')
  })

  it('lets death cross priority win over buy resonance', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '000001',
          rankTrend: {
            jump: { confidence: 0.91 },
            technical: {
              macd: { cross: 'death' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'sell' },
                zeroCross: { signal: 'sell' },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('已退出')
    expect(result.rows[0].decision).toBe('exit')
  })

  it('keeps previous status on stale data without forcing exit', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: null,
        },
      ],
      previousRows: [
        {
          code: '601208',
          status: '观察买点',
        },
      ],
    })

    expect(result.rows[0].status).toBe('观察买点')
    expect(result.rows[0].decision).toBe('stale')
    expect(result.rows[0].signalSnapshot.dataQuality).toBe('stale')
    expect(result.rows[0].reasons).toContain('signal_stale')
    expect(result.staleCount).toBe(1)
  })

  it('recovers to observation of a buy point when signals return', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            jump: { confidence: 0.9 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'buy' },
                zeroCross: { signal: 'buy' },
              },
            },
          },
        },
      ],
      previousRows: [{ code: '601208', status: '观察中' }],
    })

    expect(result.rows[0].status).toBe('观察买点')
    expect(result.rows[0].decision).toBe('enter')
  })
})
