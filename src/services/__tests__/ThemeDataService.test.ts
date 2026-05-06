import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { themeMapping } from '../ThemeDataService'
import { dataLayer } from '../DataLayer'

const sqlitePayload = {
  ok: true,
  source: 'sqlite',
  mapping: {
    version: 'theme-v8-test',
    lastUpdate: '2026-05-05T09:30:00.000Z',
    totalThemes: 1,
    themes: [
      {
        id: 'AI',
        name: '人工智能',
        zsCode: 'BK0800',
        stocks: ['000001', '600001'],
        stockTags: { '000001': [{ Name: '算力', Reason: '服务器订单' }] },
        stockReasons: { '000001': '算力龙头' },
      },
      {
        id: 'POWER',
        name: '电力',
        zsCode: 'BK0400',
        stocks: ['000001'],
        stockTags: { '000001': [{ Name: '电网' }] },
        stockReasons: { '000001': '电网建设' },
      },
    ],
  },
}

describe('ThemeDataService sqlite mapping facade', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    themeMapping.clearCache()
    dataLayer.reset()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads formal theme mapping from QuantBoard sqlite API without writing IndexedDB', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      expect(url).toBe('http://localhost:8000/api/themes/mapping')
      return new Response(JSON.stringify(sqlitePayload), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('indexedDB', {
      open: vi.fn(() => {
        throw new Error('IndexedDB must not be used for formal theme loading')
      }),
    })

    await expect(themeMapping.load()).resolves.toBe(true)

    expect(fetchMock.mock.calls.every(([url]) => String(url).includes('/api/themes/mapping'))).toBe(
      true,
    )
    expect(themeMapping.getCurrentVersion()).toBe('2026-05-05T09:30:00.000Z')
    expect(themeMapping.getAllThemes()).toEqual([
      { id: 'AI', name: '人工智能', zsCode: 'BK0800' },
      { id: 'POWER', name: '电力', zsCode: 'BK0400' },
    ])
    expect(themeMapping.getThemeStocks('AI')).toEqual(['000001', '600001'])
    expect(themeMapping.getStockThemes('000001')).toEqual(['AI', 'POWER'])
    expect(themeMapping.getStockTagsWithReason('000001')).toEqual([
      { Name: '算力', Reason: '服务器订单' },
      { Name: '电网' },
    ])
    expect(themeMapping.getStockReason('000001')).toBe('算力龙头；电网建设')
  })

  it('syncs stock tags and reasons to DataLayer limit-up extension on initial load', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify(sqlitePayload), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )

    await expect(themeMapping.load()).resolves.toBe(true)

    expect(dataLayer.getLimitUpData('000001')).toMatchObject({
      tags: [{ Name: '算力' }, { Name: '电网' }],
      reason: '算力龙头；电网建设',
    })
  })

  it('setData updates only in-memory facade state and does not persist browser IndexedDB', () => {
    vi.stubGlobal('indexedDB', {
      open: vi.fn(() => {
        throw new Error('IndexedDB must not be written by setData')
      }),
    })

    themeMapping.setData({
      version: 'manual',
      lastUpdate: '2026-05-05T10:00:00.000Z',
      totalThemes: 1,
      themes: [{ id: 'POWER', name: '电力', stocks: ['000002'] }],
    })

    expect(themeMapping.getThemeName('POWER')).toBe('电力')
    expect(themeMapping.getThemeStocks('POWER')).toEqual(['000002'])
  })

  it('keeps existing mapping when sqlite refresh returns malformed payload', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(sqlitePayload), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true, source: 'sqlite' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await expect(themeMapping.load()).resolves.toBe(true)
    await expect(themeMapping.forceRefresh()).resolves.toBe(false)

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(themeMapping.getThemeName('AI')).toBe('人工智能')
    expect(themeMapping.getStockReason('000001')).toBe('算力龙头；电网建设')
  })

  it('fails explicitly when sqlite loading fails and does not use local or batch fallbacks', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const text = String(url)
      if (text.includes('/data/theme_base_mapping.json') || text.includes('/api/themes/batch')) {
        throw new Error(`unexpected fallback request: ${text}`)
      }
      return new Response(JSON.stringify({ ok: false, detail: 'sqlite unavailable' }), {
        status: 503,
        headers: { 'content-type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('indexedDB', {
      open: vi.fn(() => {
        throw new Error('IndexedDB must not be used when sqlite loading fails')
      }),
    })

    await expect(themeMapping.load()).resolves.toBe(false)

    expect(fetchMock.mock.calls.every(([url]) => String(url).includes('/api/themes/mapping'))).toBe(
      true,
    )
    expect(themeMapping.getAllThemes()).toEqual([])
    expect(themeMapping.getLoadStatus()).toMatchObject({
      source: 'sqlite',
      loaded: false,
      themeCount: 0,
      mappingCount: 0,
    })
    expect(themeMapping.getLoadStatus().lastError).toContain('SQLite')
  })

  it('reports sqlite load status after successful loading', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify(sqlitePayload), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )

    await expect(themeMapping.load()).resolves.toBe(true)

    expect(themeMapping.getLoadStatus()).toEqual({
      source: 'sqlite',
      loaded: true,
      lastUpdate: '2026-05-05T09:30:00.000Z',
      lastError: null,
      themeCount: 2,
      mappingCount: 3,
    })
  })
})
