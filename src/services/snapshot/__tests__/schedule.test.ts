import { describe, expect, it } from 'vitest'

import { DAILY_SLOTS, HALF_HOUR_SLOTS, QUARTER_HOUR_SLOTS } from '../schedule'

describe('snapshot schedule', () => {
  it('aligns Shanghai post-close slots with the collector contract', () => {
    expect(QUARTER_HOUR_SLOTS.at(-1)).toBe('15:15')
    expect(HALF_HOUR_SLOTS.at(-1)).toBe('15:30')
    expect(DAILY_SLOTS).toEqual(['15:30'])
  })
})
