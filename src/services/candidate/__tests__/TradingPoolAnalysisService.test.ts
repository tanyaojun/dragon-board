import { describe, expect, it } from 'vitest'
import { analyzeTradingPoolCandidate, normalizeResonanceIntensity } from '../TradingPoolAnalysisService'
import type { TradingPoolStatus } from '../types'
import { RANK_TREND_LIVE_STRATEGY_PRESETS } from '@/config/rankTrendLiveStrategyConfig'

describe('TradingPool status contract', () => {
  it('keeps the V1 status vocabulary explicit', () => {
    const statuses: TradingPoolStatus[] = [
      '观察买点',
      '准备介入',
      '涨停观察',
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
  it('keeps the trading decision independent from the observation final', () => {
    const createCandidate = (signal: 'buy' | 'sell') => ({
      code: '601208',
      rankTrend: {
        decision: { final: { signal, confidence: 95 } },
        jump: { direction: 'buy', confidence: 88 },
        technical: {
          macd: { cross: 'golden' },
          signals: {
            direction: { signal: 'buy', confidence: 88 },
            acceleration: { signal: 'buy', confidence: 88 },
            zeroCross: { signal: 'buy', confidence: 88 },
          },
        },
      },
    })
    const buyFinal = analyzeTradingPoolCandidate({ candidates: [createCandidate('buy')] }).rows[0]
    const sellFinal = analyzeTradingPoolCandidate({ candidates: [createCandidate('sell')] }).rows[0]

    expect(sellFinal.decision).toBe(buyFinal.decision)
    expect(sellFinal.status).toBe(buyFinal.status)
    expect(sellFinal.scoringBreakdown.totalScore).toBe(buyFinal.scoringBreakdown.totalScore)
  })

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
            decision: { final: { signal: 'buy', confidence: 88 } },
            jump: { direction: 'buy', confidence: 0.88 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy', confidence: 88 },
                acceleration: { signal: 'buy', confidence: 88 },
                zeroCross: { signal: 'buy', confidence: 88 },
              },
            },
          },
        },
        {
          code: '300433',
          name: '蓝思科技',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 78 } },
            jump: { direction: 'hold', confidence: 0.95 },
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
      ['601208', '准备介入', 'enter'],
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
    expect(result.rows[0].reasons).toContain('strong_consensus')
    expect(result.rows[1].reasons).toContain('consensus_moderate')
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
      source: 'thesis',
    })
    expect(result.rows[0].reasons).toEqual(
      expect.arrayContaining(['strong_consensus']),
    )
  })

  it('keeps jump_blocked_resonance as compat input but never emits it as source', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '002171',
          tradingPoolSource: 'jump_blocked_resonance',
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
          },
        },
      ],
    })

    expect(result.rows[0].signalSnapshot.source).toBe('thesis')
  })

  it('does not coerce unrecognized trading-pool sources into thesis', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '002171',
          tradingPoolSource: 'legacy_unknown',
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
          },
        },
      ],
    })

    expect(result.rows[0].signalSnapshot.source).toBe('unknown')
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
      expect.arrayContaining(['strong_consensus', 'macd_golden_cross']),
    )
  })

  it('keeps high jump alone under the buy-point threshold when continuous resonance is weak', () => {
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
                direction: { signal: 'hold', confidence: 0 },
                acceleration: { signal: 'hold', confidence: 0 },
                zeroCross: { signal: 'hold', confidence: 0 },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('观察中')
    expect(result.rows[0].decision).toBe('watch')
    expect(result.rows[0].signalSnapshot.buyVotes).toBe(0)
    expect(result.rows[0].reasons).toContain('consensus_moderate')
  })

  it('enters buy-point observation when candidate-pool passed candidate has jump from gate checks', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '000988',
          name: '华工科技',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 78 } },
            jump: { direction: 'buy' },
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
      status: '观察买点',
      decision: 'enter',
    })
    expect(result.rows[0].signalSnapshot.jumpConfidence).toBe(95)
    expect(result.rows[0].signalSnapshot.buyVotes).toBe(1)
    expect(result.rows[0].reasons).toContain('strong_consensus')
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

    expect(result.rows[0].status).toBe('准备介入')
    expect(result.rows[0].decision).toBe('enter')
    expect(result.rows[0].signalSnapshot.riskFlags).toEqual(
      expect.arrayContaining(['overheat_sell', 'capital_divergence_sell']),
    )
    expect(result.rows[0].reasons).toContain('strong_consensus')
  })

  it('falls back to compat fields when nested RankTrend technical signals are absent', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          name: '东材科技',
          rankTrend: {
            jump: { direction: 'buy', confidence: 0.88 },
            technical: {},
          },
          finalSignal: 'buy',
          finalConfidence: 88,
          directionSignal: 'buy',
          directionConfidence: 88,
          accelerationSignal: 'buy',
          accelerationConfidence: 88,
          crossSignal: 'buy',
          crossConfidence: 88,
          macdCross: 'golden',
        },
      ],
    })

    expect(result.rows[0]).toMatchObject({
      code: '601208',
      status: '准备介入',
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
            decision: { final: { signal: 'buy', confidence: 88 } },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy', confidence: 88 },
                acceleration: { signal: 'buy', confidence: 88 },
                zeroCross: { signal: 'buy', confidence: 88 },
              },
            },
          },
          jumpDirection: 'buy',
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

  it('routes rankTrend jump limitUp to limit-up observation before stale and scoring', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            jump: { direction: 'buy', confidence: 95, limitUp: true },
          },
        },
      ],
      previousRows: [{ code: '601208', status: '观察买点' }],
    })

    expect(result.rows[0].status).toBe('涨停观察')
    expect(result.rows[0].decision).toBe('watch')
    expect(result.rows[0].signalSnapshot.limitUp).toBe(true)
    expect(result.rows[0].signalSnapshot.riskFlags).toContain('limit_up')
    expect(result.rows[0].reasons).toContain('limit_up')
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
    expect(result.rows[0].reasons).toContain('score_below_exit')
    expect(result.exitedCount).toBe(1)
  })

  it('downgrades when jump confidence weakens', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            jump: { direction: 'buy', confidence: 0.62 },
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
    expect(result.rows[0].decision).toBe('watch')
    expect(result.rows[0].signalSnapshot.riskFlags).not.toContain('jump_confidence_low')
    expect(result.rows[0].scoringBreakdown!.totalScore).toBeLessThan(15)
  })

  it('downgrades when momentum sync is broken', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 91 } },
            jump: { direction: 'buy', confidence: 0.91 },
            technical: {
              momentumProfile: { syncBroken: true },
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy', confidence: 90 },
                acceleration: { signal: 'buy', confidence: 90 },
                zeroCross: { signal: 'buy', confidence: 90 },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('准备介入')
    expect(result.rows[0].decision).toBe('enter')
    expect(result.rows[0].signalSnapshot.momentumSyncBroken).toBe(true)
    expect(result.rows[0].signalSnapshot.riskFlags).not.toContain('momentum_sync_broken')
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

    expect(result.rows[0].status).toBe('已介入')
    expect(result.rows[0].decision).toBe('stale')
    expect(result.rows[0].reasons).toContain('intervened_keep')
  })

  it('recovers to observation of a buy point when signals return', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 90 } },
            jump: { direction: 'buy', confidence: 0.9 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy', confidence: 90 },
                acceleration: { signal: 'buy', confidence: 90 },
                zeroCross: { signal: 'buy', confidence: 90 },
              },
            },
          },
        },
      ],
      previousRows: [{ code: '601208', status: '观察中' }],
    })

    expect(result.rows[0].status).toBe('准备介入')
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
    expect(result.rows[0].signalSnapshot.source).toBe('thesis')
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
    expect(chuJiang!.signalSnapshot.source).toBe('thesis')
    expect(taiJing!.signalSnapshot.source).toBe('live_projection')
    expect(taiJing!.status).toBe('准备介入')
  })
})

describe('TradingPoolAnalysisService — config unification', () => {
  it('uses balanced defaults when no thresholds provided', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          name: '东材科技',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 88 } },
            jump: { direction: 'buy', confidence: 0.88 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy', confidence: 88 },
                acceleration: { signal: 'buy', confidence: 88 },
                zeroCross: { signal: 'buy', confidence: 88 },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('准备介入')
    expect(result.rows[0].decision).toBe('enter')
  })

  it('uses the unified default scoring and weights contract', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          name: '东材科技',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 78 } },
            jump: { direction: 'buy', confidence: 0.78 },
            technical: {
              macd: { cross: 'none' },
              signals: {
                direction: { signal: 'buy', confidence: 90 },
                acceleration: { signal: 'buy', confidence: 90 },
                zeroCross: { signal: 'buy', confidence: 90 },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('观察买点')
    expect(result.rows[0].decision).toBe('enter')
    expect(result.rows[0].scoringBreakdown!.totalScore).toBeGreaterThan(0)
  })

  it('does not let sparse raw evidence reach the buy-point threshold', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 83 } },
            jump: { direction: 'buy', confidence: 78 },
            technical: {
              macd: { cross: 'none' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'hold' },
                zeroCross: { signal: 'buy' },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].signalSnapshot.buyVotes).toBe(2)
    expect(result.rows[0].scoringBreakdown!.totalScore).toBeLessThan(15)
    expect(result.rows[0].status).toBe('观察中')
  })
})

describe('TradingPoolAnalysisService — jump hold relaxation (方向E)', () => {
  it('allows jumpDirection=hold into strongConsensus when confidence meets hold threshold', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 88 } },
            jump: { direction: 'hold', confidence: 65 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy', confidence: 85 },
                acceleration: { signal: 'buy', confidence: 85 },
                zeroCross: { signal: 'buy', confidence: 85 },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
        },
      ],
    })

    expect(result.rows[0].signalSnapshot.buyVotes).toBe(4)
    expect(result.rows[0].status).toBe('观察买点')
  })

  it('blocks jumpDirection=sell regardless of confidence', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 90 } },
            jump: { direction: 'sell', confidence: 95 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'buy' },
                zeroCross: { signal: 'buy' },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('已退出')
  })

  it('blocks jumpDirection=hold when confidence below hold threshold', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '000001',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 88 } },
            jump: { direction: 'hold', confidence: 45 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'buy' },
                zeroCross: { signal: 'buy' },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('观察中')
    expect(result.rows[0].signalSnapshot.riskFlags).not.toContain('jump_confidence_low')
  })
})

describe('TradingPoolThresholds presets contract', () => {
  it('provides three distinct strategy modes with meaningful threshold gradients', () => {
    const recall = RANK_TREND_LIVE_STRATEGY_PRESETS.recall_first.tradingPool
    const balanced = RANK_TREND_LIVE_STRATEGY_PRESETS.balanced.tradingPool
    const strict = RANK_TREND_LIVE_STRATEGY_PRESETS.strict_execution.tradingPool

    // recall_first has the loosest bars
    expect(recall.recallJumpMin).toBeLessThan(balanced.recallJumpMin)
    expect(recall.scoring.readyJumpMin).toBeLessThan(balanced.scoring.readyJumpMin)
    expect(recall.buyVotesMin).toBe(2)

    // balanced sits in the middle
    expect(balanced.buyVotesMin).toBe(3)
    expect(balanced.recallJumpMin).toBe(80)

    // strict_execution has the tightest bars
    expect(strict.recallJumpMin).toBeGreaterThan(balanced.recallJumpMin)
    expect(strict.scoring.readyJumpMin).toBeGreaterThan(balanced.scoring.readyJumpMin)
    expect(strict.readyFinalMin).toBeGreaterThan(balanced.readyFinalMin)

    // All modes keep risk-related thresholds in sensible ranges
    for (const t of [recall, balanced, strict]) {
      expect(t.exitFinalSell).toBeGreaterThanOrEqual(70)
      expect(t.exitFinalSell).toBeLessThanOrEqual(85)
      expect(t.downgradeJumpMin).toBeLessThan(t.recallJumpMin)
    }
  })
})

describe('TradingPoolAnalysisService — 方向感知连续评分', () => {
  it('太辰光型：final卖出+方向卖出+加速度卖出，置信度高也应得低分/负分，不能观察买点', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '300570',
          name: '太辰光',
          rankTrend: {
            decision: { final: { signal: 'sell', confidence: 74 } },
            jump: { direction: 'buy', confidence: 78 },
            technical: {
              macd: { cross: 'none' },
              signals: {
                direction: { signal: 'sell', confidence: 62.93 },
                acceleration: { signal: 'sell', confidence: 70.26 },
                zeroCross: { signal: 'hold', confidence: 50 },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
        },
      ],
    })

    const b = result.rows[0].scoringBreakdown!
    // 观察 final 不进入交易池连续分
    expect(b.continuousDetail.finalConfidence).toBe(0)
    // 方向卖出 应贡献负连续分
    expect(b.continuousDetail.directionConfidence).toBeLessThan(0)
    // 加速度卖出 应贡献负连续分
    expect(b.continuousDetail.accelerationConfidence).toBeLessThan(0)
    // 零线观望 贡献接近 0
    expect(Math.abs(b.continuousDetail.zeroCrossConfidence)).toBeLessThan(0.01)
    // 总分不应达到观察买点 (≥15)
    expect(b.totalScore).toBeLessThan(15)
    expect(result.rows[0].status).not.toBe('观察买点')
  })

  it('圣泉集团型：MACD死叉+五路全空，高分连续置信度也不应入池', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '605589',
          name: '圣泉集团',
          rankTrend: {
            decision: { final: { signal: 'sell', confidence: 81 } },
            jump: { direction: 'buy', confidence: 73.6 },
            technical: {
              macd: { cross: 'death' },
              signals: {
                direction: { signal: 'sell', confidence: 63.92 },
                acceleration: { signal: 'sell', confidence: 63.27 },
                zeroCross: { signal: 'sell', confidence: 80.78 },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
        },
      ],
    })

    const b = result.rows[0].scoringBreakdown!
    // 离散分应为负（MACD死叉-3 + Jump买+2 = -1）
    expect(b.discreteScore).toBe(-1)
    // 连续分应为负（四路卖出+一路买入）
    expect(b.continuousScore).toBeLessThan(0)
    // 总分应为负
    expect(b.totalScore).toBeLessThan(0)
    // 状态必须为已退出
    expect(result.rows[0].status).toBe('已退出')
  })

  it('Jump卖出高置信度拉低总分，而非加分', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '002709',
          name: '天赐材料',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 84 } },
            jump: { direction: 'sell', confidence: 89 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy', confidence: 90 },
                acceleration: { signal: 'buy', confidence: 90 },
                zeroCross: { signal: 'hold', confidence: 50 },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
        },
      ],
    })

    const b = result.rows[0].scoringBreakdown!
    // Jump置信连续分应为负（方向=sell，89%置信度）
    expect(b.continuousDetail.jumpConfidence).toBeLessThan(0)
    // MACD金叉+3 与 Jump卖-2 相抵，离散分=1
    expect(b.discreteScore).toBe(1)
    // 连续分：Jump卖负 + final买正 + 方向买正 + 加速度买正 + 零线0，应互有抵消
    // 总分不应达到准备介入（≥20）
    expect(b.totalScore).toBeLessThan(20)
  })

  it('全买信号高置信度依然拿高分，不受方向感知负向影响', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          name: '东材科技',
          rankTrend: {
            decision: { final: { signal: 'buy', confidence: 88 } },
            jump: { direction: 'buy', confidence: 88 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy', confidence: 88 },
                acceleration: { signal: 'buy', confidence: 88 },
                zeroCross: { signal: 'buy', confidence: 88 },
              },
            },
            cycle: { decision: { action: 'allow' } },
          },
        },
      ],
    })

    const b = result.rows[0].scoringBreakdown!
    expect(b.totalScore).toBeGreaterThan(20)
    expect(b.continuousScore).toBeGreaterThan(15)
    expect(b.continuousDetail.jumpConfidence).toBeGreaterThan(0)
    expect(b.continuousDetail.finalConfidence).toBe(0)
    expect(b.continuousDetail.directionConfidence).toBeGreaterThan(0)
    expect(b.continuousDetail.accelerationConfidence).toBeGreaterThan(0)
    expect(b.continuousDetail.zeroCrossConfidence).toBeGreaterThan(0)
    expect(result.rows[0].status).toBe('准备介入')
  })
})

describe('normalizeResonanceIntensity', () => {
  it('maps ≥27 to 非常强 (≥90%)', () => {
    expect(normalizeResonanceIntensity(27).label).toBe('非常强')
    expect(normalizeResonanceIntensity(27).pct).toBe(90)
    expect(normalizeResonanceIntensity(30).pct).toBe(100)
    expect(normalizeResonanceIntensity(35).pct).toBe(100) // 封顶
  })

  it('maps 20-26 to 强 (67-89%)', () => {
    expect(normalizeResonanceIntensity(20).label).toBe('强')
    expect(normalizeResonanceIntensity(20).pct).toBe(67)
    expect(normalizeResonanceIntensity(26).label).toBe('强')
    expect(normalizeResonanceIntensity(26).pct).toBe(87)
  })

  it('maps 15-19 to 中等 (50-66%)', () => {
    expect(normalizeResonanceIntensity(15).label).toBe('中等')
    expect(normalizeResonanceIntensity(15).pct).toBe(50)
    expect(normalizeResonanceIntensity(19).label).toBe('中等')
    expect(normalizeResonanceIntensity(19).pct).toBe(63)
  })

  it('maps 8-14 to 较弱 (27-49%)', () => {
    expect(normalizeResonanceIntensity(8).label).toBe('较弱')
    expect(normalizeResonanceIntensity(8).pct).toBe(27)
    expect(normalizeResonanceIntensity(14).label).toBe('较弱')
    expect(normalizeResonanceIntensity(14).pct).toBe(47)
  })

  it('maps <8 to 非常弱 (<27%)', () => {
    expect(normalizeResonanceIntensity(7).label).toBe('非常弱')
    expect(normalizeResonanceIntensity(7).pct).toBe(23)
    expect(normalizeResonanceIntensity(0).label).toBe('非常弱')
    expect(normalizeResonanceIntensity(0).pct).toBe(0)
  })

  it('clamps negative scores to 0%', () => {
    expect(normalizeResonanceIntensity(-10).pct).toBe(0)
    expect(normalizeResonanceIntensity(-10).label).toBe('非常弱')
  })

  it('华天科技型 ~22 分 → 强 73%', () => {
    const r = normalizeResonanceIntensity(22)
    expect(r.label).toBe('强')
    expect(r.pct).toBe(73)
  })

  it('天赐材料型 7.4 分 → 非常弱 25%', () => {
    const r = normalizeResonanceIntensity(7.4)
    expect(r.label).toBe('非常弱')
    expect(r.pct).toBe(25)
  })

  it('太辰光型 -2.4 分 → 非常弱 0%', () => {
    const r = normalizeResonanceIntensity(-2.4)
    expect(r.label).toBe('非常弱')
    expect(r.pct).toBe(0)
  })
})
