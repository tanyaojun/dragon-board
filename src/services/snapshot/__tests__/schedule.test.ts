import { describe, expect, it } from 'vitest'

import { DAILY_SLOTS, HALF_HOUR_SLOTS, QUARTER_HOUR_SLOTS } from '../schedule'

describe('snapshot schedule', () => {
  it('aligns Shanghai post-close slots with the collector contract', () => {
    expect(QUARTER_HOUR_SLOTS.at(-1)).toBe('15:15')
    // half_hour 盘中序列止于 15:00 收盘定格；15:30 收盘值只由 daily 采集（2026-09-11 口径）
    expect(HALF_HOUR_SLOTS.at(-1)).toBe('15:00')
    expect(HALF_HOUR_SLOTS).not.toContain('15:30')
    expect(DAILY_SLOTS).toEqual(['15:30'])
  })
})
