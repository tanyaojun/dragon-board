import { describe, expect, it, vi } from 'vitest'

vi.mock('../FrameNormalizer', () => ({
  frameNormalizer: {
    normalize: vi.fn(
      () =>
        new Promise((resolve) => {
          setTimeout(
            () =>
              resolve({
                reviewDate: '2026-05-08',
                frames: [],
                missingData: ['review_frames'],
              }),
            10,
          )
        }),
    ),
  },
}))

import { dragonReviewService } from '../DragonReviewService'
import { refreshResourceLocks } from '../../refresh/RefreshResourceLocks'
import { frameNormalizer } from '../FrameNormalizer'

describe('DragonReviewService resource lock integration', () => {
  it('holds the dragon-review resource while rebuilding review data', async () => {
    const run = dragonReviewService.runFullUpdate('2026-05-08')

    await vi.waitFor(() => {
      expect(refreshResourceLocks.isLocked('dragon-review')).toBe(true)
    })

    await run

    expect(frameNormalizer.normalize).toHaveBeenCalledTimes(1)
    expect(refreshResourceLocks.isLocked('dragon-review')).toBe(false)
  })
})
