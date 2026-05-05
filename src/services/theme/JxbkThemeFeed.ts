import { dataLayer } from '@/services/DataLayer'
import { apiService } from '@/services/apiService'
import type { JxbkBlockData, JxbkStockData } from '@/types'

const CACHE_TTL = 5 * 60 * 1000

const sectorStocksCache: Record<
  string,
  {
    stocks: JxbkStockData[]
    loaded: boolean
    loading: boolean
    loadTime: number
    promise?: Promise<JxbkStockData[]>
  }
> = {}

function finiteNumber(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

function normalizeBlock(block: Partial<JxbkBlockData>): JxbkBlockData {
  return {
    code: String(block.code || block.name || '').trim(),
    name: String(block.name || block.code || '').trim(),
    strength: finiteNumber(block.strength),
    change: finiteNumber(block.change),
    mainNetInflow: finiteNumber(block.mainNetInflow),
    bigMoney300: finiteNumber(block.bigMoney300),
    institutionBuy: finiteNumber(block.institutionBuy),
    volumeRatio: finiteNumber(block.volumeRatio),
    ztCount: finiteNumber(block.ztCount),
  } as JxbkBlockData
}

function parseNumber(value: unknown): number {
  return parseFloat(String(value ?? '')) || 0
}

function parseInteger(value: unknown): number {
  return parseInt(String(value ?? ''), 10) || 0
}

function normalizeStockRow(item: any): JxbkStockData {
  const rawDetails = item?.[100]
  const d = Array.isArray(rawDetails) ? rawDetails : []
  return {
    code: item?.[1],
    name: item?.[2],
    leadStatus: item?.[6] || '',
    blocks: d[0] ? String(d[0]).split('、').filter(Boolean) : [],
    price: parseNumber(d[1]),
    change: parseNumber(d[2]),
    speed: parseNumber(d[3]),
    volumeRatio: parseNumber(d[4]),
    mainNetInflow: parseNumber(d[6]),
    mainBuy: parseNumber(d[7]),
    mainSell: parseNumber(d[8]),
    institutionBuy: parseNumber(d[14]),
    lianban: d[18] || '',
    fengdan: parseNumber(d[21]),
    maxFengdan: parseNumber(d[22]),
    cirMV: parseNumber(d[29]),
    leadTimes: parseInteger(d[40]),
    bigMoney300: parseNumber(d[50]),
    popularity: parseInteger(d[58]),
    popularityChange: parseInteger(d[59]),
  } as JxbkStockData
}

export const jxbkThemeFeed = {
  async refreshBlocks(options: { force?: boolean; limit?: number } = {}): Promise<JxbkBlockData[]> {
    const data = await apiService.getHotBlockList(
      { st: options.limit || 20 },
      { force: options.force === true },
    )
    const blocks = Array.isArray(data?.list)
      ? data.list
          .map((item: any[]) =>
            normalizeBlock({
              code: item?.[0],
              name: item?.[1],
              strength: item?.[2],
              change: item?.[3],
              mainNetInflow: item?.[6],
              bigMoney300: item?.[12],
              institutionBuy: item?.[14],
              volumeRatio: item?.[9],
              ztCount: 0,
            }),
          )
          .filter(
            (block: JxbkBlockData) =>
              block.code &&
              block.name &&
              !block.name.startsWith('ST') &&
              !block.name.startsWith('*ST'),
          )
      : []
    this.updateBlocks(blocks)
    return blocks
  },

  getBlocks(limit?: number): JxbkBlockData[] {
    return dataLayer
      .getJxbkBlocksSorted?.(limit)
      .map(normalizeBlock)
      .filter((block) => block.code && block.name)
  },

  getBlockByCode(code: string): JxbkBlockData | undefined {
    const block = dataLayer.getJxbkBlock?.(code)
    return block ? normalizeBlock(block) : undefined
  },

  getStock(code: string): JxbkStockData | undefined {
    return dataLayer.getJxbkStock?.(code)
  },

  getStockMap(): Record<string, JxbkStockData> {
    return dataLayer.getJxbkStockMap?.() || {}
  },

  updateBlocks(blocks: Partial<JxbkBlockData>[]) {
    dataLayer.updateJxbkBlocks(blocks.map(normalizeBlock))
  },

  async loadSectorStocks(
    sectorCode: string,
    sectorName: string,
    forceRefresh: boolean = false,
  ): Promise<JxbkStockData[]> {
    const cacheKey = `${sectorCode}_${sectorName}`

    if (!forceRefresh && sectorStocksCache[cacheKey]?.loaded) {
      const cached = sectorStocksCache[cacheKey]
      if (Date.now() - cached.loadTime < CACHE_TTL) return cached.stocks
    }

    if (forceRefresh && sectorStocksCache[cacheKey]) {
      delete sectorStocksCache[cacheKey]
    }

    if (sectorStocksCache[cacheKey]?.loading && sectorStocksCache[cacheKey].promise) {
      return sectorStocksCache[cacheKey].promise
    }

    const promise = (async () => {
      try {
        const data = await apiService.getBlockStockList(sectorCode, { type: 6, st: 80 })
        const rows = Array.isArray(data?.response?.data) ? data.response.data : []
        const stocks = rows
          .map(normalizeStockRow)
          .filter((stock: JxbkStockData) => stock.code && stock.name)
        sectorStocksCache[cacheKey] = {
          stocks,
          loaded: true,
          loading: false,
          loadTime: Date.now(),
        }
        if (stocks.length > 0) {
          dataLayer.updateJxbkStocks(stocks)
        }
        const { themeFacade } = await import('./ThemeFacade')
        themeFacade.refreshRuntime({
          source: 'jxbkThemeFeed',
          context: themeFacade.buildCurrentThemeSourceContext(),
          emitAlerts: false,
        })
        return stocks
      } catch (error) {
        console.error(`[JxbkThemeFeed] 加载板块 ${sectorCode} 个股数据失败:`, error)
        sectorStocksCache[cacheKey] = {
          stocks: [],
          loaded: false,
          loading: false,
          loadTime: Date.now(),
        }
        return []
      }
    })()

    sectorStocksCache[cacheKey] = {
      stocks: [],
      loaded: false,
      loading: true,
      loadTime: Date.now(),
      promise,
    }

    return promise
  },

  getSectorStockCacheStats(): { cachedSectors: number } {
    return {
      cachedSectors: Object.values(sectorStocksCache).filter((entry) => entry.loaded).length,
    }
  },

  clearSectorStockCache(): void {
    Object.keys(sectorStocksCache).forEach((key) => {
      delete sectorStocksCache[key]
    })
  },
}
