import { describe, expect, it } from 'vitest'
import { buildLegacyBlockThemeEvents } from '../ThemeLegacyAlertAdapter'

describe('ThemeLegacyAlertAdapter', () => {
  it('converts legacy block money, volume and batch signals to theme events', () => {
    const events = buildLegacyBlockThemeEvents({
      timestamp: 1713751200000,
      blocks: [
        {
          code: 'BKAI',
          name: '人工智能',
          strength: 4200,
          change: 4,
          mainNetInflow: 180000000,
          bigMoney300: 0,
          institutionBuy: 0,
          volumeRatio: 3.5,
          ztCount: 3,
        },
      ],
      stockMap: {
        '000001': { code: '000001', name: '样本一', blocks: ['人工智能'] } as any,
        '000002': { code: '000002', name: '样本二', blocks: ['人工智能'] } as any,
        '000003': { code: '000003', name: '样本三', blocks: ['人工智能'] } as any,
      },
    })

    expect(events.map((event) => event.type)).toEqual(
      expect.arrayContaining(['theme_fund_inflow', 'theme_crowding_high', 'theme_strength_surge']),
    )
    expect(events.every((event) => event.source === 'theme_legacy_adapter')).toBe(true)
    expect(events[0].stockCodes).toEqual(expect.arrayContaining(['000001']))
  })
})
