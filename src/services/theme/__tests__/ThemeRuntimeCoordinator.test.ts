import { describe, expect, it, vi, beforeEach } from 'vitest'
import { dataLayer } from '@/services/DataLayer'
import { refreshThemeFacadeState, themeFacade } from '../ThemeFacade'
import { jxbkThemeFeed } from '../JxbkThemeFeed'
import { refreshRuntime } from '../ThemeRuntimeCoordinator'
import { themeRuntimeStore } from '../ThemeRuntimeStore'
import { refreshResourceLocks } from '../../refresh/RefreshResourceLocks'
import type { ThemeSourceContext } from '../types'

function context(timestamp = 1713751200000): ThemeSourceContext {
  return {
    timestamp,
    themes: [{ id: 'AI', name: '人工智能' }],
    themeStocks: new Map([['AI', ['000001']]]),
    stockThemes: new Map([['000001', ['AI']]]),
    stocks: [{ code: '000001', name: '样本一', change: 10, volumeRatio: 3, leadStatus: '龙一' }],
    jxbkBlocks: [
      {
        code: 'BKAI',
        name: '人工智能',
        strength: 4200,
        change: 4,
        mainNetInflow: 180000000,
        bigMoney300: 0,
        institutionBuy: 0,
        volumeRatio: 2.4,
        ztCount: 1,
      },
    ],
    rotationAnalysis: null,
    correlations: new Map(),
  }
}

describe('ThemeRuntimeCoordinator', () => {
  beforeEach(() => {
    dataLayer.reset()
    themeRuntimeStore.clear()
  })

  it('builds runtime result with metadata, quality summary and changed fields', () => {
    const result = refreshRuntime({
      source: 'test',
      context: context(),
      emitAlerts: false,
    })

    expect(result.source).toBe('test')
    expect(result.inputSignature).toContain('AI')
    expect(result.changedFields).toEqual(expect.arrayContaining(['factors', 'exposures', 'rotation', 'events']))
    expect(result.qualitySummary.totalFlags).toBeGreaterThanOrEqual(0)
    expect(themeRuntimeStore.getSnapshot()).toMatchObject({
      refreshSource: 'test',
      factorVersion: 'theme-factor-v1',
      eventVersion: 'theme-event-v1',
    })
  })

  it('keeps outputs deterministic for the same input signature', () => {
    const first = refreshRuntime({ source: 'test', context: context(), emitAlerts: false })
    const second = refreshRuntime({ source: 'test', context: context(), emitAlerts: false })

    expect(second.inputSignature).toBe(first.inputSignature)
    expect(second.factors).toEqual(first.factors)
    expect(second.rotationSummary).toEqual(first.rotationSummary)
    expect(second.events).toEqual(first.events)
    expect(second.changedFields).toEqual([])
  })

  it('refreshes JXBK feed when forceJxbk is requested without explicit context', async () => {
    const spy = vi.spyOn(jxbkThemeFeed, 'refreshBlocks').mockResolvedValue([])

    await refreshRuntime({ source: 'manual', forceJxbk: true, emitAlerts: false })

    expect(spy).toHaveBeenCalledWith({ force: undefined })
    spy.mockRestore()
  })

  it('syncs projected stock themes back to DataLayer when requested', () => {
    dataLayer.setMergedStocks([{ code: '000001', name: '样本一', change: 10 } as any])

    const result = refreshRuntime({
      source: 'dataLoader',
      context: context(),
      syncStocks: true,
      emitAlerts: false,
    })
    const stock = dataLayer.getStock('000001') as any

    expect(result.syncedStockCount).toBe(1)
    expect(stock.mainTheme).toBe('人工智能')
    expect(stock.themeHeat).toBeGreaterThan(0)
    expect(stock.themes?.[0]?.themeContribution).toBeGreaterThanOrEqual(0)
  })

  it('keeps facade read models in sync when refreshing through refreshRuntime', () => {
    const result = themeFacade.refreshRuntime({
      source: 'test',
      context: context(),
      emitAlerts: false,
    })

    expect(themeFacade.getThemeFactors()).toEqual(result.factors)
    expect(themeFacade.getRotationSummary()).toEqual(result.rotationSummary)
    expect(themeFacade.getRuntimeSnapshot().inputSignature).toBe(result.inputSignature)
  })

  it('serializes async facade runtime refreshes through the theme resource', async () => {
    const releases: Array<() => void> = []
    const spy = vi.spyOn(jxbkThemeFeed, 'refreshBlocks').mockImplementation(
      () =>
        new Promise<any[]>((resolve) => {
          releases.push(() => resolve([]))
        }),
    )

    try {
      const first = themeFacade.refreshRuntime({
        source: 'manual',
        forceJxbk: true,
        emitAlerts: false,
      }) as Promise<any>

      await vi.waitFor(() => {
        expect(refreshResourceLocks.isLocked('theme-runtime')).toBe(true)
      })

      const second = themeFacade.refreshRuntime({
        source: 'manual',
        forceJxbk: true,
        emitAlerts: false,
      }) as Promise<any>
      await Promise.resolve()

      expect(spy).toHaveBeenCalledTimes(1)

      releases.shift()?.()
      await first
      await vi.waitFor(() => {
        expect(spy).toHaveBeenCalledTimes(2)
      })
      releases.shift()?.()
      await second

      expect(refreshResourceLocks.isLocked('theme-runtime')).toBe(false)
    } finally {
      spy.mockRestore()
    }
  })

  it('keeps legacy refresh facade as a wrapper around the same runtime chain', () => {
    const result = refreshThemeFacadeState({
      source: 'test',
      context: context(),
      emitAlerts: false,
    })

    expect(result.factors).toEqual(themeFacade.getRuntimeSnapshot().factors)
    expect(result.events).toEqual(themeFacade.getRuntimeSnapshot().events)
    expect(result.inputSignature).toBe(themeFacade.getRuntimeSnapshot().inputSignature)
  })
})
