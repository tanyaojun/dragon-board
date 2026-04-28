import type { ReviewFrame } from './types'
import { getSegmentForIndex } from './helpers'

export class SessionSegmenter {
  assign(frames: ReviewFrame[]): ReviewFrame[] {
    const sorted = [...frames].sort((a, b) => a.timestamp - b.timestamp)
    const intradayFrames = sorted.filter((frame) => frame.source !== 'close')
    const total = intradayFrames.length

    return sorted.map((frame) => {
      if (frame.source === 'close') {
        return {
          ...frame,
          segment: 'late',
        }
      }

      const index = intradayFrames.findIndex((item) => item.id === frame.id)
      return {
        ...frame,
        segment: getSegmentForIndex(index >= 0 ? index : total - 1, total),
      }
    })
  }
}

export const sessionSegmenter = new SessionSegmenter()
