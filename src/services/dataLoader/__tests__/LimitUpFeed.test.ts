import { describe, expect, it, vi } from 'vitest'

import {
  loadLimitUpData,
  loadThsLimitUpPoolData,
  mapLimitUpItems,
  mapThsLimitUpPools,
} from '../LimitUpFeed'

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

  it('normalizes real 10jqka timestamp and high-days text fields', () => {
    expect(
      mapLimitUpItems([
        {
          code: '600386',
          reason_type: '广告传媒+汽车服务+北京国资',
          is_new: 0,
          first_limit_up_time: '1778810904',
          last_limit_up_time: '1778828133',
          continue_day: null as any,
          high_days: '首板' as any,
        },
        {
          code: '002971',
          reason_type: '电子特气+硅基新材料',
          is_new: 0,
          first_limit_up_time: '1778827443',
          last_limit_up_time: '1778827515',
          continue_day: null as any,
          high_days: '5天3板' as any,
        },
      ]),
    ).toEqual([
      {
        code: '600386',
        reason: '广告传媒+汽车服务+北京国资',
        isNew: false,
        firstZtTime: '10:08:24',
        lastZtTime: '14:55:33',
        boardHeight: 1,
        highDays: 1,
        lianbanStr: '首板',
      },
      {
        code: '002971',
        reason: '电子特气+硅基新材料',
        isNew: false,
        firstZtTime: '14:44:03',
        lastZtTime: '14:45:15',
        boardHeight: 3,
        highDays: 3,
        lianbanStr: '5天3板',
      },
    ])
  })

  it('maps order_amount to fengdan and keeps missing fields absent', () => {
    const rows = mapLimitUpItems([
      {
        code: '002059',
        reason_type: '景区运营+文旅科技+人形机器人',
        is_new: 0,
        first_limit_up_time: '1778810904',
        last_limit_up_time: '1778828133',
        continue_day: null as any,
        high_days: '首板' as any,
        order_amount: 4.2107625e7,
        open_num: 1,
      },
      {
        code: '605118',
        reason_type: '光学镜头+机器视觉',
        is_new: 0,
        first_limit_up_time: '1778826944',
        last_limit_up_time: '1778830610',
        continue_day: null as any,
        high_days: '3天2板' as any,
        order_amount: null as any,
        open_num: null as any,
      },
    ])

    expect(rows[0]).toEqual(
      expect.objectContaining({
        code: '002059',
        fengdan: 42107625,
        lianbanStr: '首板',
        openNum: 1,
      }),
    )
    // 缺失字段不产出伪造键：无封单金额不造 fengdan: 0，无开板次数不造 openNum: 0
    expect('fengdan' in rows[1]).toBe(false)
    expect('openNum' in rows[1]).toBe(false)
    expect(rows[1]).toEqual(
      expect.objectContaining({ code: '605118', lianbanStr: '3天2板' }),
    )
  })

  it('decodes high-days encoded value when text is missing', () => {
    expect(
      mapLimitUpItems([
        {
          code: '002971',
          reason_type: '电子特气+硅基新材料',
          is_new: 0,
          first_limit_up_time: '1778827443',
          last_limit_up_time: '1778827515',
          continue_day: null,
          high_days: null,
          high_days_value: 196613,
        },
      ]),
    ).toEqual([
      expect.objectContaining({
        code: '002971',
        boardHeight: 3,
        highDays: 3,
      }),
    ])
  })

  it('normalizes ths segmented limit-up pool rows', () => {
    const rows = mapThsLimitUpPools({
      one: {
        ok: true,
        cate: 'limit_up_one',
        items: [
          {
            stock_code: 'SZ002971',
            stock_name: '和远气体',
            change: 10.01,
            volume_money: '24500000',
            limit_up_time: '1778827443',
            limit_up_reason: '电子特气+硅基新材料',
            continue_day: '3',
            high_days: '5天3板',
          },
        ],
      },
      failed: {
        ok: true,
        cate: 'limit_up_fail',
        items: [
          {
            code: '600386',
            name: '北巴传媒',
            change_rate: 8.6,
            rise_rate: 1.2,
            turnover: '320000000',
          },
        ],
      },
      drawdown: {
        ok: true,
        cate: 'limit_up_bigboard',
        items: [
          {
            stock_code: '600001',
            stock_name: '样本股',
            change: 4.2,
            max_drawdown: '-12.5',
          },
        ],
      },
    } as any)

    expect(rows).toEqual([
      expect.objectContaining({
        poolType: 'one',
        code: '002971',
        name: '和远气体',
        reason: '电子特气+硅基新材料',
        firstZtTime: '14:44:03',
        limitUpTime: '14:44:03',
        boardHeight: 3,
        highDays: 3,
        lianbanStr: '5天3板',
        fengdan: 24500000,
        raw: expect.any(Object),
      }),
      expect.objectContaining({
        poolType: 'failed',
        code: '600386',
        name: '北巴传媒',
        change: 8.6,
        speed: 1.2,
        turnover: 320000000,
      }),
      expect.objectContaining({
        poolType: 'drawdown',
        code: '600001',
        name: '样本股',
        maxDrawdown: -12.5,
      }),
    ])
    expect(rows[1].turnoverRate).toBeUndefined()
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

  it('writes ths segmented pool rows to DataLayer as limit-up enrichment', async () => {
    const updateLimitUpData = vi.fn()
    await loadThsLimitUpPoolData({
      api: {
        getThsLimitUpPools: vi.fn().mockResolvedValue({
          pools: {
            one: {
              ok: true,
              items: [
                {
                  stock_code: '600001',
                  stock_name: '样本股',
                  limit_up_reason: '机器人',
                  limit_up_time: '09:35',
                  continue_day: 1,
                  high_days: '2连板',
                  volume_money: 12000000,
                },
              ],
            },
          },
        }),
      },
      dataLayer: { updateLimitUpData },
    })

    expect(updateLimitUpData).toHaveBeenCalledWith([
      expect.objectContaining({
        code: '600001',
        reason: '机器人',
        firstZtTime: '09:35:00',
        // 细分池无 last_limit_up_time 字段：不产出 lastZtTime，保留主池真实回封时间
        boardHeight: 1,
        highDays: 1,
        lianbanStr: '2连板',
        fengdan: 12000000,
      }),
    ])
    const updates = updateLimitUpData.mock.calls[0][0] as Array<Record<string, unknown>>
    expect('lastZtTime' in updates[0]).toBe(false)
  })

  it('does not fabricate lastZtTime from first limit-up time in ths pools', () => {
    // 2026-09-02 接口实测：细分池（ths/pools）只有 limit_up_time（首次），没有 last_limit_up_time。
    // 缺省时不得用首次时间伪造最后涨停时间 —— 细分池后加载会覆盖主池真实的回封时间
    const rows = mapThsLimitUpPools({
      one: {
        ok: true,
        items: [
          {
            stock_code: '600001',
            stock_name: '样本股',
            limit_up_time: '09:35',
          },
        ],
      },
    })

    expect(rows[0].firstZtTime).toBe('09:35:00')
    expect('lastZtTime' in rows[0]).toBe(false)
  })

  it('keeps real last_limit_up_time when the ths pool provides it', () => {
    const rows = mapThsLimitUpPools({
      one: {
        ok: true,
        items: [
          {
            stock_code: '600001',
            stock_name: '样本股',
            limit_up_time: '09:35',
            last_limit_up_time: '14:55',
          },
        ],
      },
    })

    expect(rows[0].firstZtTime).toBe('09:35:00')
    expect(rows[0].lastZtTime).toBe('14:55:00')
  })

  it('does not overwrite existing limit-up facts with empty ths pool fields', async () => {
    const updateLimitUpData = vi.fn()
    await loadThsLimitUpPoolData({
      api: {
        getThsLimitUpPools: vi.fn().mockResolvedValue({
          pools: {
            failed: {
              ok: true,
              items: [
                {
                  code: '600386',
                  name: '北巴传媒',
                  change_rate: 8.6,
                  rise_rate: 1.2,
                },
              ],
            },
          },
        }),
      },
      dataLayer: { updateLimitUpData },
    })

    expect(updateLimitUpData).toHaveBeenCalledWith([
      expect.not.objectContaining({
        reason: '',
        firstZtTime: '',
        lastZtTime: '',
        boardHeight: 0,
        highDays: 0,
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
