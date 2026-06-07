import { beforeEach, describe, expect, it, vi } from 'vitest'

const addCandidateFromStock = vi.fn().mockResolvedValue({ entry: null })
const getOpenCandidateForStock = vi.fn().mockResolvedValue(null)
const saveCandidateReview = vi.fn().mockResolvedValue(null)
const isTradingTime = vi.fn(() => true)

vi.mock('@/services/candidate/CandidateJournalService', () => ({
  candidateJournalService: {
    addCandidateFromStock,
    getOpenCandidateForStock,
    saveCandidateReview,
  },
}))

vi.mock('@/utils/time', () => ({
  isTradingTime,
}))

describe('JumpSignalNotifier', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    isTradingTime.mockReturnValue(true)
  })

  it('does not push feishu messages outside trading time', async () => {
    isTradingTime.mockReturnValue(false)
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)

    const { jumpSignalNotifier } = await import('../JumpSignalNotifier')

    await jumpSignalNotifier.notifyEntry(
      {
        code: '002552',
        name: '宝鼎科技',
        price: 10.35,
        change: 3.5,
      },
      {
        jump: { event: 'jump', direction: 'buy', confidence: 92, sustained: true, magnitude: 20 },
        isEntry: true,
        isExit: false,
        exitReason: '',
      } as any,
    )

    expect(fetchMock).not.toHaveBeenCalled()
    expect(addCandidateFromStock).toHaveBeenCalledTimes(1)
  })

  it('does not consume feishu cooldown when outside trading time', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)

    const { jumpSignalNotifier } = await import('../JumpSignalNotifier')

    isTradingTime.mockReturnValue(false)
    await jumpSignalNotifier.notifyEntry(
      {
        code: '002552',
        name: '宝鼎科技',
        price: 10.35,
        change: 3.5,
      },
      {
        jump: { event: 'jump', direction: 'buy', confidence: 92, sustained: true, magnitude: 20 },
        isEntry: true,
        isExit: false,
        exitReason: '',
      } as any,
    )

    isTradingTime.mockReturnValue(true)
    await jumpSignalNotifier.notifyEntry(
      {
        code: '002552',
        name: '宝鼎科技',
        price: 10.42,
        change: 3.8,
      },
      {
        jump: { event: 'jump', direction: 'buy', confidence: 94, sustained: true, magnitude: 21 },
        isEntry: true,
        isExit: false,
        exitReason: '',
      } as any,
    )

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
