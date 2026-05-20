import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RotationAnalysis } from '@/types/core'
import { dataLayer } from '../DataLayer'
import { themeFacade } from '../theme/ThemeFacade'
import { themeRepository } from '../theme/ThemeRepository'
import { jxbkThemeFeed } from '../theme/JxbkThemeFeed'
import { rotationService } from '../rotationService'
import { sectorAnalyzer } from '../sectorAnalyzer'

vi.mock('../../utils/time', () => ({
  isTradingTime: vi.fn(() => true),
}))

const rotationSummary: RotationAnalysis = {
  timestamp: 1713751200000,
  mainLines: [
    {
      themeId: 'AI',
      themeName: '人工智能',
      rank: 1,
      rankChange: 0,
      netInflow: 100000000,
      avgChange: 4,
      ztCount: 2,
      strength: 'strong',
      strengthScore: 88,
      isMainLine: true,
      persistentDays: 3,
      direction: 'inflow',
      inflow: 100000000,
      outflow: 0,
      totalTurnover: 0,
      totalBoardHeight: 0,
      avgBoardHeight: 0,
      highDays: 0,
      topReasons: [],
      stockCount: 2,
      relatedThemes: [],
      volumeRatio: 2,
      bigMoney300: 0,
      institutionBuy: 0,
      inflowChange: 0,
    },
  ],
  inflowThemes: [],
  outflowThemes: [],
  strongThemes: [],
  quickRotation: [],
  rotationSpeed: 20,
  marketPhase: 'rising',
  summary: {
    mainLineCount: 1,
    inflowCount: 0,
    outflowCount: 0,
    strongCount: 0,
    topInflow: '无',
    topOutflow: '无',
    topStrength: '无',
    suggestion: '主线稳定',
  },
}

describe('theme legacy adapters', () => {
  beforeEach(async () => {
    dataLayer.reset()
    rotationService.stopAutoAnalysis()
    const { refreshTaskRegistry } = await import('../refresh/RefreshTaskRuntime')
    refreshTaskRegistry.resetRuntimeState()
    vi.restoreAllMocks()
  })

  it('rotationService uses runtime rotation summary without reading JXBK fallback data', () => {
    const refreshSpy = vi.spyOn(themeFacade, 'refreshRuntime').mockReturnValue({
      factors: [],
      exposures: { byCode: new Map(), byTheme: new Map() },
      rotationSummary,
      events: [],
      qualitySummary: { totalFlags: 0, fatalCount: 0, warningCount: 0, infoCount: 0, byCode: {} },
      changedFields: [],
      inputSignature: 'same',
      source: 'rotationService',
      timestamp: 1713751200000,
      syncedStockCount: 0,
    })
    vi.spyOn(themeFacade, 'buildCurrentThemeSourceContext').mockReturnValue({
      timestamp: 1713751200000,
      themes: [],
      themeStocks: new Map(),
      stockThemes: new Map(),
      stocks: [],
      jxbkBlocks: [],
      rotationAnalysis: null,
      correlations: new Map(),
    })
    const jxbkSpy = vi.spyOn(dataLayer, 'getJxbkBlocksSorted')

    expect(rotationService.analyzeAll()).toEqual(rotationSummary)
    expect(rotationService.forceAnalyze()).toEqual(rotationSummary)
    expect(refreshSpy).toHaveBeenCalledTimes(2)
    expect(jxbkSpy).not.toHaveBeenCalled()
  })

  it('records rotation analysis through the shared refresh scheduler', async () => {
    vi.useFakeTimers()
    const refreshSpy = vi.spyOn(themeFacade, 'refreshRuntime').mockReturnValue({
      factors: [],
      exposures: { byCode: new Map(), byTheme: new Map() },
      rotationSummary,
      events: [],
      qualitySummary: { totalFlags: 0, fatalCount: 0, warningCount: 0, infoCount: 0, byCode: {} },
      changedFields: [],
      inputSignature: 'same',
      source: 'rotationService',
      timestamp: 1713751200000,
      syncedStockCount: 0,
    })
    vi.spyOn(themeFacade, 'buildCurrentThemeSourceContext').mockReturnValue({
      timestamp: 1713751200000,
      themes: [],
      themeStocks: new Map(),
      stockThemes: new Map(),
      stocks: [],
      jxbkBlocks: [],
      rotationAnalysis: null,
      correlations: new Map(),
    })

    try {
      const { refreshTaskRegistry } = await import('../refresh/RefreshTaskRuntime')

      rotationService.startAutoAnalysis(1000)
      await vi.advanceTimersByTimeAsync(1000)

      expect(refreshSpy).toHaveBeenCalledTimes(1)
      expect(refreshTaskRegistry.getTask('theme.runtime')).toMatchObject({
        running: false,
        lastRunAt: expect.any(Number),
        lastSuccessAt: expect.any(Number),
        lastError: null,
        successCount: 1,
        source: 'scheduler',
      })
    } finally {
      rotationService.stopAutoAnalysis()
      vi.useRealTimers()
    }
  })

  it('sectorAnalyzer sync and refresh APIs delegate to theme runtime', async () => {
    const refreshSpy = vi.spyOn(themeFacade, 'refreshRuntime').mockReturnValue({
      factors: [],
      exposures: { byCode: new Map(), byTheme: new Map() },
      rotationSummary: null,
      events: [],
      qualitySummary: { totalFlags: 0, fatalCount: 0, warningCount: 0, infoCount: 0, byCode: {} },
      changedFields: [],
      inputSignature: 'same',
      source: 'sectorAnalyzer',
      timestamp: 1713751200000,
      syncedStockCount: 3,
    })

    expect(sectorAnalyzer.syncThemesToStocks()).toBe(3)
    await sectorAnalyzer.forceRefreshJxbk()
    await sectorAnalyzer.syncData()

    expect(refreshSpy).toHaveBeenCalledTimes(3)
    expect(refreshSpy.mock.calls.every(([options]) => options?.source === 'sectorAnalyzer')).toBe(true)
  })

  it('sectorAnalyzer forceRefreshJxbk does not refresh after destroy', async () => {
    const refreshSpy = vi.spyOn(themeFacade, 'refreshRuntime').mockReturnValue({
      factors: [],
      exposures: { byCode: new Map(), byTheme: new Map() },
      rotationSummary: null,
      events: [],
      qualitySummary: { totalFlags: 0, fatalCount: 0, warningCount: 0, infoCount: 0, byCode: {} },
      changedFields: [],
      inputSignature: 'same',
      source: 'sectorAnalyzer',
      timestamp: 1713751200000,
      syncedStockCount: 0,
    })

    sectorAnalyzer.destroy()
    await sectorAnalyzer.forceRefreshJxbk()

    expect(refreshSpy).not.toHaveBeenCalled()
  })

  it('sectorAnalyzer sector stock APIs delegate to JxbkThemeFeed', async () => {
    const loadSpy = vi.spyOn(jxbkThemeFeed, 'loadSectorStocks').mockResolvedValue([
      { code: '000001', name: '样本一', blocks: ['人工智能'] } as any,
    ])
    const clearSpy = vi.spyOn(jxbkThemeFeed, 'clearSectorStockCache').mockImplementation(() => {})
    vi.spyOn(jxbkThemeFeed, 'getSectorStockCacheStats').mockReturnValue({ cachedSectors: 2 })
    vi.spyOn(themeRepository, 'getThemeBaseStatus').mockReturnValue({
      source: 'mongodb',
      loaded: true,
      lastUpdate: '2026-05-05T09:30:00.000Z',
      lastError: null,
      themeCount: 237,
      mappingCount: 12215,
    })

    await expect(sectorAnalyzer.loadSectorStocks('BKAI', '人工智能', true)).resolves.toHaveLength(1)
    expect(loadSpy).toHaveBeenCalledWith('BKAI', '人工智能', true)
    expect(sectorAnalyzer.getStats().cachedSectors).toBe(2)
    expect(sectorAnalyzer.getStats()).toMatchObject({
      version: '11.0.0',
      themeBaseSource: 'mongodb',
      mappedStocks: 12215,
    })

    sectorAnalyzer.clearCache()
    expect(clearSpy).toHaveBeenCalled()
  })

  it('sectorAnalyzer syncs tag and reason data through themeRepository public getters', async () => {
    vi.spyOn(themeRepository, 'loadThemeBase').mockResolvedValue(true)
    vi.spyOn(themeRepository, 'getThemes').mockReturnValue([
      { id: 'AI', name: '人工智能', zsCode: 'BK0800' },
    ])
    vi.spyOn(themeRepository, 'getThemeStocks').mockReturnValue(['000001'])
    vi.spyOn(themeRepository, 'getThemeBaseStatus').mockReturnValue({
      source: 'mongodb',
      loaded: true,
      lastUpdate: '2026-05-05T09:30:00.000Z',
      lastError: null,
      themeCount: 1,
      mappingCount: 1,
    })
    vi.spyOn(themeRepository, 'getStockTags').mockReturnValue([{ Name: '算力' }])
    vi.spyOn(themeRepository, 'getStockReason').mockReturnValue('算力龙头')
    vi.spyOn(themeFacade, 'refreshRuntime').mockReturnValue({
      factors: [],
      exposures: { byCode: new Map(), byTheme: new Map() },
      rotationSummary: null,
      events: [],
      qualitySummary: { totalFlags: 0, fatalCount: 0, warningCount: 0, infoCount: 0, byCode: {} },
      changedFields: [],
      inputSignature: 'same',
      source: 'sectorAnalyzer',
      timestamp: 1713751200000,
      syncedStockCount: 0,
    })
    const stockTagsSpy = vi.spyOn(dataLayer, 'updateStockTags')
    const limitUpSpy = vi.spyOn(dataLayer, 'updateLimitUpData')

    await sectorAnalyzer.init()

    expect(stockTagsSpy).toHaveBeenCalledWith([{ code: '000001', tags: [{ Name: '算力' }] }])
    expect(limitUpSpy).toHaveBeenCalledWith([
      { code: '000001', reason: '算力龙头', tags: [{ Name: '算力' }] },
    ])
  })
})
