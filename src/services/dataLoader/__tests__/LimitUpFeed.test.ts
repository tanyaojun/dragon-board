import { describe, expect, it, vi } from 'vitest'

import { loadLimitUpData, mapLimitUpItems } from '../LimitUpFeed'

describe('LimitUpFeed', () => {
  it('maps limit-up API rows to DataLayer update fields', () => {
    expect(
      mapLimitUpItems([
        {
          code: 'SZ000001',
          reason_type: '机器人',
          is_new: 1,
          first_limit_up_time: '09:31:00',
          last_limit_up_time: '14:55:00',
          continue_day: 2,
          high_days: 3,
        },
      ]),
    ).toEqual([
      {
        code: '000001',
        reason: '机器人',
        isNew: true,
        firstZtTime: '09:31:00',
        lastZtTime: '14:55:00',
        boardHeight: 2,
        highDays: 3,
      },
    ])
  })

  it('writes mapped rows when API response contains info', async () => {
    const updateLimitUpData = vi.fn()
    await loadLimitUpData({
      api: {
        getLimitUp: vi.fn().mockResolvedValue({
          data: {
            info: [
              {
                code: '600001',
                reason_type: '算力',
                is_new: 0,
                first_limit_up_time: '10:00:00',
                last_limit_up_time: '10:00:00',
                continue_day: 1,
                high_days: 1,
              },
            ],
          },
        }),
      },
      dataLayer: { updateLimitUpData },
    })

    expect(updateLimitUpData).toHaveBeenCalledWith([
      expect.objectContaining({
        code: '600001',
        reason: '算力',
        isNew: false,
      }),
    ])
  })

  it('ignores empty responses and warns without throwing on API failure', async () => {
    const updateLimitUpData = vi.fn()
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    await loadLimitUpData({
      api: { getLimitUp: vi.fn().mockResolvedValue({ data: {} }) },
      dataLayer: { updateLimitUpData },
    })
    await expect(
      loadLimitUpData({
        api: { getLimitUp: vi.fn().mockRejectedValue(new Error('network')) },
        dataLayer: { updateLimitUpData },
      }),
    ).resolves.toBeUndefined()

    expect(updateLimitUpData).not.toHaveBeenCalled()
    expect(warn).toHaveBeenCalledWith('[DataLoader] 加载涨停池数据失败:', expect.any(Error))
    warn.mockRestore()
  })
})
