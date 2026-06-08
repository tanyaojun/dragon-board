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
    vi.unstubAllGlobals()
  })

  it('legacy notifier no longer writes candidate pool or pushes feishu', async () => {
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
    expect(addCandidateFromStock).not.toHaveBeenCalled()
    expect(getOpenCandidateForStock).not.toHaveBeenCalled()
    expect(saveCandidateReview).not.toHaveBeenCalled()
  })
})
