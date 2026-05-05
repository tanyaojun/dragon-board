import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../theme/ThemeFacade', () => ({
  themeFacade: {
    refresh: vi.fn(() => ({ events: [] })),
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
    expect(alerts.some((alert) => alert.type === 'money_flow' && alert.themeName === '人工智能')).toBe(true)
    expect(alerts.some((alert) => alert.type === 'volume_surge' && alert.themeName === '人工智能')).toBe(true)
  })
})
