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
      jumpConfidence: 88,
      macdCross: 'golden',
      directionSignal: 'buy',
      accelerationSignal: 'buy',
      zeroCrossSignal: 'buy',
      momentumSyncBroken: false,
      lifecycleAction: null,
      dataQuality: 'fresh',
    })
    expect(result.rows[0].reasons).toContain('signal_resonance')
    expect(result.rows[1].reasons).toContain('consensus_not_enough')
    expect(result.staleCount).toBe(0)
    expect(result.exitedCount).toBe(0)
  })

  it('recalls a jump-blocked strong consensus candidate into trading watch', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '002171',
          name: '楚江新材',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 87 } },
            jump: { direction: 'buy', confidence: 82.9 },
            technical: {
              macd: { cross: 'none' },
              signals: {
                direction: { signal: 'buy', confidence: 90 },
                acceleration: { signal: 'buy', confidence: 90 },
                zeroCross: { signal: 'buy', confidence: 90 },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
          candidateEntryDecision: {
            accepted: false,
            checks: [{ key: 'jump_confidence', status: 'fail', hardBlock: true }],
          },
        },
      ],
    })

    expect(result.rows[0]).toMatchObject({
      code: '002171',
      status: '观察买点',
      decision: 'enter',
    })
    expect(result.rows[0].signalSnapshot).toMatchObject({
      finalSignal: 'buy',
      finalConfidence: 87,
      jumpDirection: 'buy',
      jumpConfidence: 82.9,
      buyVotes: 3,
      source: 'jump_blocked_resonance',
    })
    expect(result.rows[0].reasons).toEqual(
      expect.arrayContaining(['strong_consensus', 'jump_blocked_resonance']),
    )
  })

  it('promotes a golden-cross strong consensus candidate to ready state', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '603738',
          name: '泰晶科技',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 91 } },
            jump: { direction: 'buy', confidence: 87.9 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy', confidence: 88.83 },
                acceleration: { signal: 'buy', confidence: 90 },
                zeroCross: { signal: 'buy', confidence: 90 },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
          candidateEntryDecision: {
            accepted: false,
            checks: [{ key: 'jump_confidence', status: 'fail', hardBlock: true }],
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('准备介入')
    expect(result.rows[0].signalSnapshot.buyVotes).toBe(4)
    expect(result.rows[0].reasons).toEqual(
      expect.arrayContaining(['strong_consensus', 'macd_golden_cross', 'jump_blocked_resonance']),
    )
  })

  it('does not enter trading pool on high jump alone without consensus', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '000001',
          rankTrend: {
            decision: { final: { signal: 'hold', confidence: 72 } },
            jump: { direction: 'buy', confidence: 95 },
            technical: {
              macd: { cross: 'none' },
              signals: {
                direction: { signal: 'hold', confidence: 50 },
                acceleration: { signal: 'hold', confidence: 50 },
                zeroCross: { signal: 'hold', confidence: 50 },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('观察中')
    expect(result.rows[0].decision).toBe('downgrade')
    expect(result.rows[0].signalSnapshot.buyVotes).toBe(0)
    expect(result.rows[0].reasons).toContain('consensus_not_enough')
  })

  it('keeps a candidate-pool passed weak resonance candidate observing when jump comes from gate checks', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '000988',
          name: '华工科技',
          rankTrend: {
            decision: { final: { signal: 'hold', confidence: 78 } },
            technical: {
              macd: { cross: 'none' },
              signals: {
                direction: { signal: 'buy', confidence: 90 },
                acceleration: { signal: 'hold', confidence: 53.72 },
                zeroCross: { signal: 'hold', confidence: 50 },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
          candidateEntryDecision: {
            accepted: true,
            checks: [
              {
                key: 'jump_confidence',
                label: 'Jump置信度',
                status: 'pass',
                hardBlock: false,
                actual: 95,
                expected: '>= 85',
                message: 'Jump 置信度满足要求',
              },
            ],
          },
        },
      ],
    })

    expect(result.rows[0]).toMatchObject({
      code: '000988',
      status: '观察中',
      decision: 'watch',
    })
    expect(result.rows[0].signalSnapshot.jumpConfidence).toBe(95)
    expect(result.rows[0].signalSnapshot.buyVotes).toBe(1)
    expect(result.rows[0].reasons).toContain('consensus_not_enough')
  })

  it('keeps double-risk strong consensus in watch instead of ready state', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '300000',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 90 } },
            jump: { direction: 'buy', confidence: 88 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy', confidence: 90 },
                acceleration: { signal: 'buy', confidence: 90 },
                zeroCross: { signal: 'buy', confidence: 90 },
              },
            },
            risk: {
              overheatReversal: { signal: 'sell' },
              capitalDivergence: { signal: 'sell' },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('观察中')
    expect(result.rows[0].decision).toBe('downgrade')
    expect(result.rows[0].signalSnapshot.riskFlags).toEqual(
      expect.arrayContaining(['overheat_sell', 'capital_divergence_sell']),
    )
    expect(result.rows[0].reasons).toContain('double_risk')
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
      jumpConfidence: 88,
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
    expect(result.rows[0].signalSnapshot.jumpConfidence).toBe(86)
  })

  it('normalizes decimal confidences near one into percentage scale', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 0.999 } },
            jump: { confidence: 0.999 },
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

    expect(result.rows[0].signalSnapshot.finalConfidence).toBe(99.9)
    expect(result.rows[0].signalSnapshot.jumpConfidence).toBe(99.9)
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

  it('keeps an intervened candidate when only one risk flag appears', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '603738',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 88 } },
            jump: { direction: 'buy', confidence: 86 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'buy' },
                zeroCross: { signal: 'buy' },
              },
            },
            risk: {
              overheatReversal: { signal: 'sell' },
            },
          },
        },
      ],
      previousRows: [{ code: '603738', status: '已介入' }],
    })

    expect(result.rows[0].status).toBe('已介入')
    expect(result.rows[0].decision).toBe('stale')
    expect(result.rows[0].signalSnapshot.riskFlags).toContain('overheat_sell')
    expect(result.rows[0].reasons).toContain('intervened_keep_with_risk')
  })

  it('downgrades an intervened candidate when final hold confidence weakens', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '603738',
          rankTrend: {
            decision: { final: { signal: 'hold', confidence: 84.9 } },
            jump: { direction: 'buy', confidence: 86 },
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
      previousRows: [{ code: '603738', status: '已介入' }],
    })

    expect(result.rows[0].status).toBe('观察中')
    expect(result.rows[0].decision).toBe('downgrade')
    expect(result.rows[0].reasons).toContain('intervened_consensus_weakened')
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

describe('TradingPoolAnalysisService — live projection pipeline', () => {
  it('marks DataLayer live projection stocks with live_projection source', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [],
      liveStocks: [
        {
          code: '002171',
          name: '楚江新材',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 87 } },
            jump: { direction: 'buy', confidence: 82.9 },
            technical: {
              macd: { cross: 'none' },
              signals: {
                direction: { signal: 'buy', confidence: 90 },
                acceleration: { signal: 'buy', confidence: 90 },
                zeroCross: { signal: 'buy', confidence: 90 },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
        },
      ],
    })

    expect(result.rows).toHaveLength(1)
    expect(result.rows[0].code).toBe('002171')
    expect(result.rows[0].signalSnapshot.source).toBe('live_projection')
  })

  it('deduplicates live projection when thesis candidate exists for same code', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '603738',
          name: '泰晶科技-thesis',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 91 } },
            jump: { direction: 'buy', confidence: 87.9 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy', confidence: 88 },
                acceleration: { signal: 'buy', confidence: 90 },
                zeroCross: { signal: 'buy', confidence: 90 },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
          candidateEntryDecision: {
            accepted: false,
            checks: [{ key: 'jump_confidence', status: 'fail', hardBlock: true }],
          },
        },
      ],
      liveStocks: [
        {
          code: '603738',
          name: '泰晶科技-live',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 88 } },
            jump: { direction: 'buy', confidence: 84 },
            technical: {
              macd: { cross: 'none' },
              signals: {
                direction: { signal: 'buy', confidence: 80 },
                acceleration: { signal: 'buy', confidence: 80 },
                zeroCross: { signal: 'buy', confidence: 80 },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
        },
      ],
    })

    expect(result.rows).toHaveLength(1)
    expect(result.rows[0].name).toBe('泰晶科技-thesis')
    expect(result.rows[0].signalSnapshot.source).toBe('jump_blocked_resonance')
  })

  it('handles live projection stock without rankTrend gracefully', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [],
      liveStocks: [
        {
          code: '000001',
          name: '无信号票',
        },
      ],
    })

    expect(result.rows).toHaveLength(1)
    expect(result.rows[0].signalSnapshot.dataQuality).toBe('stale')
    expect(result.rows[0].status).toBe('观察中')
  })

  it('processes mixed thesis and live projection inputs correctly', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '002171',
          name: '楚江-thesis',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 87 } },
            jump: { direction: 'buy', confidence: 82.9 },
            technical: {
              macd: { cross: 'none' },
              signals: {
                direction: { signal: 'buy', confidence: 90 },
                acceleration: { signal: 'buy', confidence: 90 },
                zeroCross: { signal: 'buy', confidence: 90 },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
          candidateEntryDecision: {
            accepted: false,
            checks: [{ key: 'jump_confidence', status: 'fail', hardBlock: true }],
          },
        },
      ],
      liveStocks: [
        {
          code: '603738',
          name: '泰晶-live',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 91 } },
            jump: { direction: 'buy', confidence: 87.9 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy', confidence: 88 },
                acceleration: { signal: 'buy', confidence: 90 },
                zeroCross: { signal: 'buy', confidence: 90 },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
        },
      ],
    })

    expect(result.rows).toHaveLength(2)
    const chuJiang = result.rows.find((r) => r.code === '002171')
    const taiJing = result.rows.find((r) => r.code === '603738')
    expect(chuJiang!.signalSnapshot.source).toBe('jump_blocked_resonance')
    expect(taiJing!.signalSnapshot.source).toBe('live_projection')
    expect(taiJing!.status).toBe('准备介入')
  })
})
