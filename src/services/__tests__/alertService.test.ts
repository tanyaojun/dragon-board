import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../theme/ThemeFacade', () => ({
  themeFacade: {
    refresh: vi.fn(() => ({
      events: [
        {
          id: 'theme_fund_inflow:BKAI:1713751200000',
          type: 'theme_fund_inflow',
          level: 'warning',
          themeId: 'BKAI',
          themeName: '人工智能',
          timestamp: 1713751200000,
          source: 'theme',
          stockCodes: ['000001', '000002'],
          metrics: { netInflow: 200000000 },
          riskFlags: [],
          reasons: ['资金流入增强'],
        },
        {
          id: 'theme_mapping_quality_warning:MISS:1713751200000',
          type: 'theme_mapping_quality_warning',
          level: 'info',
          themeId: 'MISS',
          themeName: '映射缺失',
          timestamp: 1713751200000,
          source: 'theme',
          stockCodes: [],
          metrics: {},
          riskFlags: ['mapping_missing'],
          reasons: ['题材映射缺失'],
        },
      ],
    })),
    getJxbkBlocksCompat: vi.fn(() => [
      {
        code: 'BKAI',
        name: '人工智能',
        strength: 4200,
        change: 3,
        mainNetInflow: 200000000,
        bigMoney300: 0,
        institutionBuy: 0,
        volumeRatio: 3.2,
        ztCount: 2,
      },
    ]),
    getThemeStockMapCompat: vi.fn(() => ({
      '000001': { code: '000001', name: '样本一', blocks: ['人工智能'] },
      '000002': { code: '000002', name: '样本二', blocks: ['人工智能'] },
    })),
  },
}))

import { dataLayer } from '../DataLayer'
import { alertService } from '../alertService'

describe('alertService V3 compatibility', () => {
  beforeEach(() => {
    dataLayer.reset()
    alertService.destroy()
  })

  it('keeps legacy block alerts while ingesting theme events', async () => {
    dataLayer.updateJxbkBlocks([
      {
        code: 'BKAI',
        name: '人工智能',
        strength: 4200,
        change: 3,
        mainNetInflow: 200000000,
        bigMoney300: 0,
        institutionBuy: 0,
        volumeRatio: 3.2,
        ztCount: 2,
      },
    ])
    dataLayer.updateJxbkStocks([
      { code: '000001', name: '样本一', blocks: ['人工智能'] } as any,
      { code: '000002', name: '样本二', blocks: ['人工智能'] } as any,
    ])

    await alertService.checkAll()

    const alerts = alertService.getAlerts()
    expect(alerts.filter((alert) => alert.type === 'money_flow' && alert.themeName === '人工智能')).toHaveLength(1)
    expect(alerts.some((alert) => alert.type === 'volume_surge' && alert.themeName === '人工智能')).toBe(true)
    expect(alerts.some((alert) => alert.type === 'data_anomaly' && alert.themeName === '映射缺失')).toBe(true)
  })
})
