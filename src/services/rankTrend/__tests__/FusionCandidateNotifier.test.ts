import { beforeEach, describe, expect, it, vi } from 'vitest'

import { FusionCandidateNotifier } from '../FusionCandidateNotifier'

function createStock(overrides: Record<string, unknown> = {}) {
  return {
    code: '000001',
    name: '平安银行',
    price: 12.34,
    change: 3.2,
    accDelta: 8,
    rankTrend: {
      meta: {
        sampleQuality: {
          snapshotType: 'half_hour',
          sampleCount: 30,
          requiredSampleCount: 30,
          status: 'ok',
          delayedCount: 0,
          restoredCount: 0,
        },
      },
      jump: { direction: 'buy', confidence: 92 },
      technical: {
        momentumProfile: {
          short: 12,
          mid: 24,
          long: 11,
          acceleration: 12,
        },
        signals: {
          zeroCross: { signal: 'buy' },
        },
      },
      cycle: {
        decision: {
          action: 'allow',
        },
      },
      strategy: {
        candidateTier: 'A_MAIN',
      },
      executionStrategy: {
        candidateTier: 'A_MAIN',
      },
    },
    ...overrides,
  }
}

describe('FusionCandidateNotifier', () => {
  const getOpenCandidateForStock = vi.fn()
  const addCandidateFromStock = vi.fn()
  const now = vi.fn(() => new Date('2026-06-08T10:00:00.000Z'))

  beforeEach(() => {
    vi.clearAllMocks()
    vi.unstubAllGlobals()
    getOpenCandidateForStock.mockResolvedValue(null)
    addCandidateFromStock.mockResolvedValue({ created: true, entry: null })
  })

  it('只为 fusion 命中且无 open candidate 的股票创建 triggered 候选并推送 fusion 候选池消息', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    const notifier = new FusionCandidateNotifier({
      candidateJournal: {
        getOpenCandidateForStock,
        addCandidateFromStock,
      },
      now,
    })

    await notifier.process([
      createStock(),
      createStock({
        code: '000002',
        rankTrend: {
          meta: {
            sampleQuality: {
              snapshotType: 'half_hour',
              sampleCount: 30,
              requiredSampleCount: 30,
              status: 'ok',
              delayedCount: 0,
              restoredCount: 0,
            },
          },
          jump: { direction: 'buy', confidence: 70 },
          technical: {
            momentumProfile: {
              short: 12,
              mid: 24,
              long: 11,
              acceleration: 12,
            },
            signals: {
              zeroCross: { signal: 'buy' },
            },
          },
          cycle: {
            decision: {
              action: 'allow',
            },
          },
          strategy: {
            candidateTier: 'A_MAIN',
          },
        },
      }),
    ])

    expect(getOpenCandidateForStock).toHaveBeenCalledTimes(1)
    expect(getOpenCandidateForStock).toHaveBeenCalledWith('000001')
    expect(addCandidateFromStock).toHaveBeenCalledTimes(1)
    expect(addCandidateFromStock).toHaveBeenCalledWith(
      expect.objectContaining({ code: '000001' }),
      {
        addToFavorites: true,
        source: 'ranktrend_early_big_move_v3_lifecycle_fusion',
        statusOverride: 'triggered',
        signalsSnapshotPatch: {
          triggerMeta: {
            source: 'ranktrend_early_big_move_v3_lifecycle_fusion',
            baseline: 'early_big_move_v5',
            triggerType: 'auto',
            triggeredAt: '2026-06-08T10:00:00.000Z',
            executionCandidateTier: 'A_MAIN',
            lifecycleAction: 'allow',
            jumpConfidence: 92,
            minJumpConfidence: 85,
            blockedReasons: [],
            decisionState: 'auto_add',
          },
        },
      },
    )
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/notifications/jump-signal',
      expect.objectContaining({
        method: 'POST',
        headers: { 'content-type': 'application/json' },
      }),
    )
    const [, request] = fetchMock.mock.calls[0]
    const body = JSON.parse(String(request?.body))
    expect(body).toEqual({
      source: 'ranktrend-fusion-candidate-pool',
      events: [
        expect.objectContaining({
          code: '000001',
          name: '平安银行',
          signalType: 'strategy_candidate',
          signalLabel: 'Fusion 候选池触发',
          candidateTier: 'A_MAIN',
          lifecycleAction: 'allow',
          decisionState: 'auto_add',
          decisionLabel: '自动入池',
          decisionSummary: '满足当前 live 自动入池规则',
          source: 'ranktrend_early_big_move_v3_lifecycle_fusion',
          checks: expect.arrayContaining([
            expect.objectContaining({
              key: 'jump_confidence',
              label: 'Jump置信度',
              status: 'pass',
              actual: 92,
              expected: '>= 85',
            }),
            expect.objectContaining({
              key: 'acceleration',
              label: '加速度',
              status: 'pass',
              actual: '12/8',
              expected: 'acceleration >= 10 或 accDelta >= 8',
            }),
          ]),
          timestamp: Date.parse('2026-06-08T10:00:00.000Z'),
        }),
      ],
    })
    expect(body.events[0].checks).toHaveLength(5)
  })

  it('自动入池和推送记录 executionStrategy 分层，不使用展示分层', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    const notifier = new FusionCandidateNotifier({
      candidateJournal: {
        getOpenCandidateForStock,
        addCandidateFromStock,
      },
      now,
    })

    await notifier.process([
      createStock({
        rankTrend: {
          ...createStock().rankTrend,
          strategy: {
            candidateTier: 'N_NEUTRAL',
          },
          executionStrategy: {
            candidateTier: 'A_MAIN',
          },
        },
      }),
    ])

    expect(addCandidateFromStock).toHaveBeenCalledWith(
      expect.objectContaining({ code: '000001' }),
      expect.objectContaining({
        signalsSnapshotPatch: {
          triggerMeta: expect.objectContaining({
            executionCandidateTier: 'A_MAIN',
          }),
        },
      }),
    )
    const [, request] = fetchMock.mock.calls[0]
    expect(JSON.parse(String(request?.body))).toEqual({
      source: 'ranktrend-fusion-candidate-pool',
      events: [
        expect.objectContaining({
          candidateTier: 'A_MAIN',
          reason: 'A_MAIN 命中，已自动写入候选池',
        }),
      ],
    })
  })

  it('executionStrategy 非 A/B 时即使展示分层 A_MAIN 也不会自动入池', async () => {
    const notifier = new FusionCandidateNotifier({
      candidateJournal: {
        getOpenCandidateForStock,
        addCandidateFromStock,
      },
      now,
    })

    await notifier.process([
      createStock({
        rankTrend: {
          ...createStock().rankTrend,
          strategy: {
            candidateTier: 'A_MAIN',
          },
          executionStrategy: {
            candidateTier: 'N_NEUTRAL',
          },
        },
      }),
    ])

    expect(getOpenCandidateForStock).not.toHaveBeenCalled()
    expect(addCandidateFromStock).not.toHaveBeenCalled()
  })

  it('V5 默认 JumpConfidence 低于 90 时不会自动写入候选池', async () => {
    const notifier = new FusionCandidateNotifier({
      candidateJournal: {
        getOpenCandidateForStock,
        addCandidateFromStock,
      },
      now,
    })

    await notifier.process([
      createStock({
        rankTrend: {
          ...createStock().rankTrend,
          jump: { direction: 'buy', confidence: 79.8 },
        },
      }),
    ])

    expect(getOpenCandidateForStock).not.toHaveBeenCalled()
    expect(addCandidateFromStock).not.toHaveBeenCalled()
  })

  it('balanced 下 change >= 6 只进入观察候选，不自动写入候选池', async () => {
    const notifier = new FusionCandidateNotifier({
      candidateJournal: {
        getOpenCandidateForStock,
        addCandidateFromStock,
      },
      now,
    })

    await notifier.process([createStock({ change: 6.5 })])

    expect(getOpenCandidateForStock).not.toHaveBeenCalled()
    expect(addCandidateFromStock).not.toHaveBeenCalled()
  })

  it('quote-first 判断为涨停时不自动写入候选池', async () => {
    const notifier = new FusionCandidateNotifier({
      candidateJournal: {
        getOpenCandidateForStock,
        addCandidateFromStock,
      },
      now,
    })

    await notifier.process([
      createStock({
        change: 3.2,
        price: 12.34,
        limitUpPrice: 12.34,
      }),
    ])

    expect(getOpenCandidateForStock).not.toHaveBeenCalled()
    expect(addCandidateFromStock).not.toHaveBeenCalled()
  })

  it('lifecycle veto 时即使 RankTrend 和 Jump 很强也不会自动写入候选池', async () => {
    const notifier = new FusionCandidateNotifier({
      candidateJournal: {
        getOpenCandidateForStock,
        addCandidateFromStock,
      },
      now,
    })

    await notifier.process([
      createStock({
        rankTrend: {
          ...createStock().rankTrend,
          jump: { direction: 'buy', confidence: 98 },
          cycle: {
            decision: {
              action: 'veto',
            },
          },
        },
      }),
    ])

    expect(getOpenCandidateForStock).not.toHaveBeenCalled()
    expect(addCandidateFromStock).not.toHaveBeenCalled()
  })

  it('遇到已有 open candidate 时跳过重复创建', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    getOpenCandidateForStock.mockResolvedValue({
      id: 'existing',
      stockCode: '000001',
      status: 'candidate',
    })

    const notifier = new FusionCandidateNotifier({
      candidateJournal: {
        getOpenCandidateForStock,
        addCandidateFromStock,
      },
      now,
    })

    await notifier.process([createStock()])

    expect(getOpenCandidateForStock).toHaveBeenCalledWith('000001')
    expect(addCandidateFromStock).not.toHaveBeenCalled()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('入池服务返回 created=false 时不推送候选池消息', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    addCandidateFromStock.mockResolvedValue({
      created: false,
      entry: {
        id: 'existing',
        stockCode: '000001',
        status: 'triggered',
      },
    })

    const notifier = new FusionCandidateNotifier({
      candidateJournal: {
        getOpenCandidateForStock,
        addCandidateFromStock,
      },
      now,
    })

    await notifier.process([createStock()])

    expect(addCandidateFromStock).toHaveBeenCalledTimes(1)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('飞书推送阻塞时不拖慢候选池主流程', async () => {
    const fetchMock = vi.fn(() => new Promise(() => {}))
    vi.stubGlobal('fetch', fetchMock)

    const notifier = new FusionCandidateNotifier({
      candidateJournal: {
        getOpenCandidateForStock,
        addCandidateFromStock,
      },
      now,
    })

    const outcome = await Promise.race([
      notifier.process([createStock()]).then(() => 'resolved'),
      new Promise((resolve) => setTimeout(() => resolve('timeout'), 0)),
    ])

    expect(outcome).toBe('resolved')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('AbortSignal.timeout 不可用时自动入池后仍推送飞书消息', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    const originalTimeout = AbortSignal.timeout
    ;(AbortSignal as any).timeout = undefined

    try {
      const notifier = new FusionCandidateNotifier({
        candidateJournal: {
          getOpenCandidateForStock,
          addCandidateFromStock,
        },
        now,
      })

      await notifier.process([createStock()])
      await Promise.resolve()

      expect(addCandidateFromStock).toHaveBeenCalledTimes(1)
      expect(fetchMock).toHaveBeenCalledTimes(1)
      expect(fetchMock.mock.calls[0][0]).toBe('/api/notifications/jump-signal')
    } finally {
      ;(AbortSignal as any).timeout = originalTimeout
    }
  })
})
