import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, disposePinia, setActivePinia } from 'pinia'

import { dataLayer } from '@/services/DataLayer'
import { AppEvents } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { useFavoriteStore } from '../favorite'

vi.mock('@/services/StockCodeManager', () => ({
  stockCodeManager: {
    getStockInfo: vi.fn(() => undefined),
  },
}))

class MemoryStorage {
  private store = new Map<string, string>()

  getItem(key: string): string | null {
    return this.store.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.store.set(key, value)
  }

  removeItem(key: string): void {
    this.store.delete(key)
  }

  clear(): void {
    this.store.clear()
  }
}

function seedStock(code = '600584') {
  dataLayer.setMergedStocks([
    {
      code,
      name: '长电科技',
      price: 58.05,
      change: 6.89,
      volume: 0,
      turnover: 0,
      turnoverRate: 0,
      pe: 0,
      pb: 0,
      totalMV: 0,
      cirMV: 0,
      zlje: 0,
      zljzb: 0,
      cddje: 0,
      cddjzb: 0,
    },
  ])
}

describe('FavoriteStore', () => {
  let storage: MemoryStorage
  let pinia: ReturnType<typeof createPinia> | null

  function disposeTestPinia(): void {
    if (!pinia) return
    disposePinia(pinia)
    pinia = null
  }

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    dataLayer.reset()
    EventManager.clearHistory()
    storage = new MemoryStorage()
    vi.stubGlobal('localStorage', storage)
  })

  afterEach(() => {
    disposeTestPinia()
    vi.unstubAllGlobals()
  })

  it('adds a visible DataLayer stock even when the stock code manager is not ready', () => {
    seedStock()
    const store = useFavoriteStore()
    store.init()

    expect(store.addToFavorites('600584')).toBe(true)

    expect(store.favoriteList).toEqual([
      expect.objectContaining({
        code: '600584',
        name: '长电科技',
        lastPrice: 58.05,
        lastChange: 6.89,
      }),
    ])
    expect(EventManager.getHistory(AppEvents.UI.TOAST).at(-1)?.data).toMatchObject({
      type: 'success',
    })
  })

  it('initializes from storage before adding so existing favorites are not overwritten', () => {
    storage.setItem(
      'favorite_data',
      JSON.stringify({
        favorites: [
          [
            '000001',
            {
              code: '000001',
              name: '平安银行',
              group: '默认',
              addTime: 1,
              lastPrice: 10,
              lastChange: 1,
              lastUpdate: 1,
            },
          ],
        ],
        groups: [['默认', { name: '默认', color: '#FF6B6B', count: 1, createTime: 1 }]],
        boards: [],
        stockBoards: [],
      }),
    )
    seedStock()
    const store = useFavoriteStore()

    expect(store.addToFavorites('600584')).toBe(true)

    expect(store.favoriteList.map((item) => item.code).sort()).toEqual(['000001', '600584'])
    const saved = JSON.parse(storage.getItem('favorite_data') || '{}')
    expect(saved.favorites.map(([code]: [string]) => code).sort()).toEqual(['000001', '600584'])
  })

  it('syncs favorite quotes from DataLayer instead of an uninitialized stock store', () => {
    seedStock()
    const store = useFavoriteStore()
    store.init()
    store.addToFavorites('600584')

    dataLayer.setMergedStocks([
      {
        code: '600584',
        name: '长电科技',
        price: 60.12,
        change: 8.21,
      },
    ])

    expect(store.syncWithMarketData()).toBe(1)
    expect(store.favorites.get('600584')).toMatchObject({
      lastPrice: 60.12,
      lastChange: 8.21,
    })
  })

  it('removes board links when a favorite is removed or all favorites are cleared', () => {
    seedStock('600584')
    const store = useFavoriteStore()
    store.init()
    store.addToFavorites('600584')
    const board = store.addBoard('芯片链')!
    store.addStockToBoard('600584', board.id)

    expect(store.stockBoards.has('600584')).toBe(true)

    store.removeFromFavorites('600584')

    expect(store.stockBoards.has('600584')).toBe(false)
    expect(store.boards.get(board.id)?.count).toBe(0)

    seedStock('600584')
    store.addToFavorites('600584')
    store.addStockToBoard('600584', board.id)
    store.clearAllFavorites()

    expect(store.stockBoards.size).toBe(0)
    expect(store.boards.get(board.id)?.count).toBe(0)
  })

  it('unsubscribes from DataLayer updates when the store scope is disposed', async () => {
    seedStock()
    const store = useFavoriteStore()
    store.init()
    store.addToFavorites('600584')

    disposeTestPinia()
    EventManager.clearHistory()

    dataLayer.setMergedStocks([
      {
        code: '600584',
        name: '长电科技',
        price: 61.23,
        change: 9.12,
      },
    ])
    await new Promise((resolve) => setTimeout(resolve, 80))

    expect(EventManager.getHistory('favorites-synced')).toHaveLength(0)
  })
})
