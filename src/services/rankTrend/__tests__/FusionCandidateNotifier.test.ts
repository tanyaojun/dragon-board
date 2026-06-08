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

  it('只为 fusion 命中且无 open candidate 的股票创建 triggered 候选并推送候选池消息', async () => {
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
            triggerType: 'auto',
            triggeredAt: '2026-06-08T10:00:00.000Z',
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
    expect(JSON.parse(String(request?.body))).toEqual({
      source: 'ranktrend-fusion-candidate-pool',
      events: [
        expect.objectContaining({
          code: '000001',
          name: '平安银行',
          signalType: 'entry',
          signalLabel: '候选池触发',
          timestamp: Date.parse('2026-06-08T10:00:00.000Z'),
        }),
      ],
    })
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
})
