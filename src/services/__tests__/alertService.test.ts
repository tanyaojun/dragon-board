import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../theme/ThemeFacade', () => ({
  themeFacade: {
    refresh: vi.fn(() => ({ events: [] })),
    refreshRuntime: vi.fn(() => ({
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
        {
          id: 'theme_crowding_high:BKAI:1713751200000',
          type: 'theme_crowding_high',
          level: 'warning',
          themeId: 'BKAI',
          themeName: '人工智能',
          timestamp: 1713751200000,
          source: 'theme_legacy_adapter',
          alertType: 'volume_surge',
          stockCodes: ['000001', '000002'],
          metrics: { volumeRatio: 3.2 },
          riskFlags: ['volume_surge'],
          reasons: ['板块量比放大'],
        },
      ],
    })),
    getJxbkBlocks: vi.fn(() => [
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
    getThemeStockMap: vi.fn(() => ({
      '000001': { code: '000001', name: '样本一', blocks: ['人工智能'] },
      '000002': { code: '000002', name: '样本二', blocks: ['人工智能'] },
    })),
  },
}))

vi.mock('../../utils/time', () => ({
  isTradingTime: vi.fn(() => true),
}))

import { dataLayer } from '../DataLayer'
import { alertService } from '../alertService'
import { themeFacade } from '../theme/ThemeFacade'

describe('alertService V3 compatibility', () => {
  beforeEach(async () => {
    dataLayer.reset()
    alertService.destroy()
    const { refreshTaskRegistry } = await import('../refresh/RefreshTaskRuntime')
    refreshTaskRegistry.resetRuntimeState()
    vi.clearAllMocks()
  })

  afterEach(() => {
    alertService.destroy()
  })

  it('ingests unified runtime theme events without rebuilding legacy block events', async () => {
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
    expect(themeFacade.refreshRuntime).toHaveBeenCalledTimes(1)
    expect(themeFacade.refresh).not.toHaveBeenCalled()
    expect(alerts.filter((alert) => alert.type === 'money_flow' && alert.themeName === '人工智能')).toHaveLength(1)
    expect(alerts.filter((alert) => alert.type === 'volume_surge' && alert.themeName === '人工智能')).toHaveLength(1)
    expect(alerts.some((alert) => alert.type === 'volume_surge' && alert.themeName === '人工智能')).toBe(true)
    expect(alerts.some((alert) => alert.type === 'data_anomaly' && alert.themeName === '映射缺失')).toBe(true)
  })

  it('records automatic alert checks through the shared refresh scheduler', async () => {
    vi.useFakeTimers()
    try {
      const { refreshTaskRegistry } = await import('../refresh/RefreshTaskRuntime')

      alertService.startAutoCheck(1000)
      await vi.advanceTimersByTimeAsync(1000)

      expect(themeFacade.refreshRuntime).toHaveBeenCalledTimes(1)
      expect(refreshTaskRegistry.getTask('alert.check')).toMatchObject({
        running: false,
        lastRunAt: expect.any(Number),
        lastSuccessAt: expect.any(Number),
        lastError: null,
        successCount: 1,
        source: 'scheduler',
      })
    } finally {
      alertService.stopAutoCheck()
      vi.useRealTimers()
    }
  })

  it('does not use suspicious capped volume ratio for stock speed alerts', async () => {
    vi.mocked(themeFacade.getThemeStockMap).mockReturnValue({
      '000001': {
        code: '000001',
        name: '样本一',
        speed: 4,
        change: 5,
        volumeRatio: 99.99,
        volumeRatioMeta: {
          status: 'suspicious',
          source: 'intraday_snapshot',
          calculatedAt: Date.now(),
          currentVolume: 100000,
          capped: true,
          reason: 'ratio_capped',
        },
        blocks: ['人工智能'],
      },
    })

    await alertService.checkAll()

    expect(alertService.getAlerts().some((alert) => alert.type === 'rocket_launch')).toBe(false)
  })
})
