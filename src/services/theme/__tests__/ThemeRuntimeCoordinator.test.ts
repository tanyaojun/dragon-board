import { describe, expect, it, vi, beforeEach } from 'vitest'
import { dataLayer } from '@/services/DataLayer'
import { jxbkThemeFeed } from '../JxbkThemeFeed'
import { refreshRuntime } from '../ThemeRuntimeCoordinator'
import { themeRuntimeStore } from '../ThemeRuntimeStore'
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
})
