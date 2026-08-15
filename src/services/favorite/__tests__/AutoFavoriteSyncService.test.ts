import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, disposePinia, setActivePinia } from 'pinia'

import { dataLayer } from '@/services/DataLayer'
import { useFavoriteStore } from '@/stores/favorite'
import { AutoFavoriteSyncService } from '../AutoFavoriteSyncService'

function createStock(overrides: Record<string, unknown> = {}) {
  return {
    code: '000001',
    name: '平安银行',
    rankTrend: {
      technical: {
        macd: {
          cross: 'golden',
        },
      },
      resonance: {
        status: 'ok',
        direction: 'buy',
        score: 85,
      },
      observation: {
        lifecycle: {
          stage: 'expansion',
        },
      },
    },
    ...overrides,
  }
}

function createDeps(overrides: Record<string, unknown> = {}) {
  const isFavorite = vi.fn(() => false)
  const listAutoFavorites = vi.fn(() => [])
  const addAutoFavorite = vi.fn(() => true)
  const removeAutoFavorite = vi.fn(() => true)
  return {
    deps: {
      isFavorite,
      listAutoFavorites,
      addAutoFavorite,
      removeAutoFavorite,
      ...overrides,
    },
    isFavorite,
    listAutoFavorites,
    addAutoFavorite,
    removeAutoFavorite,
  }
}

describe('AutoFavoriteSyncService', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('adds a stock whose rank trend is MACD golden cross and resonance direction is buy', () => {
    const { deps, addAutoFavorite, isFavorite } = createDeps()
    const service = new AutoFavoriteSyncService(deps)

    const result = service.sync([createStock()])

    expect(isFavorite).toHaveBeenCalledWith('000001')
    expect(addAutoFavorite).toHaveBeenCalledWith('000001')
    expect(result.added).toEqual(['000001'])
    expect(result.removed).toEqual([])
  })

  it('does not add when resonance direction is not buy even with golden cross', () => {
    const { deps, addAutoFavorite } = createDeps()
    const service = new AutoFavoriteSyncService(deps)

    const result = service.sync([createStock({ rankTrend: { technical: { macd: { cross: 'golden' } }, resonance: { status: 'ok', direction: 'sell' } } })])

    expect(addAutoFavorite).not.toHaveBeenCalled()
    expect(result.added).toEqual([])
  })

  it('does not add when macd cross is not golden even with resonance buy', () => {
    const { deps, addAutoFavorite } = createDeps()
    const service = new AutoFavoriteSyncService(deps)

    const result = service.sync([createStock({ rankTrend: { technical: { macd: { cross: 'death' } }, resonance: { status: 'ok', direction: 'buy' } } })])

    expect(addAutoFavorite).not.toHaveBeenCalled()
    expect(result.added).toEqual([])
  })

  it('does not add when resonance status is not ok (insufficient sample)', () => {
    const { deps, addAutoFavorite } = createDeps()
    const service = new AutoFavoriteSyncService(deps)

    const result = service.sync([createStock({ rankTrend: { technical: { macd: { cross: 'golden' } }, resonance: { status: 'insufficient', direction: 'buy' } } })])

    expect(addAutoFavorite).not.toHaveBeenCalled()
    expect(result.added).toEqual([])
  })

  it('does not add when resonance score is below 80 even with golden cross and buy direction', () => {
    const { deps, addAutoFavorite } = createDeps()
    const service = new AutoFavoriteSyncService(deps)

    const result = service.sync([createStock({ rankTrend: { technical: { macd: { cross: 'golden' } }, resonance: { status: 'ok', direction: 'buy', score: 79.9 } } })])

    expect(addAutoFavorite).not.toHaveBeenCalled()
    expect(result.added).toEqual([])
  })

  it('adds when resonance score is exactly 80', () => {
    const { deps, addAutoFavorite } = createDeps()
    const service = new AutoFavoriteSyncService(deps)

    const result = service.sync([createStock({ rankTrend: { ...createStock().rankTrend, resonance: { status: 'ok', direction: 'buy', score: 80 } } })])

    expect(addAutoFavorite).toHaveBeenCalledWith('000001')
    expect(result.added).toEqual(['000001'])
  })

  it('does not add when resonance score is missing', () => {
    const { deps, addAutoFavorite } = createDeps()
    const service = new AutoFavoriteSyncService(deps)

    const result = service.sync([createStock({ rankTrend: { technical: { macd: { cross: 'golden' } }, resonance: { status: 'ok', direction: 'buy' } } })])

    expect(addAutoFavorite).not.toHaveBeenCalled()
    expect(result.added).toEqual([])
  })

  it('adds when lifecycle stage is ignition', () => {
    const { deps, addAutoFavorite } = createDeps()
    const service = new AutoFavoriteSyncService(deps)

    const result = service.sync([createStock({ rankTrend: { ...createStock().rankTrend, observation: { lifecycle: { stage: 'ignition' } } } })])

    expect(addAutoFavorite).toHaveBeenCalledWith('000001')
    expect(result.added).toEqual(['000001'])
  })

  it('does not add when lifecycle stage is crowded/high_reversal/cooling even with golden and strong resonance', () => {
    const { deps, addAutoFavorite } = createDeps()
    const service = new AutoFavoriteSyncService(deps)
    const base = createStock().rankTrend

    for (const stage of ['crowded', 'high_reversal', 'cooling']) {
      service.sync([createStock({ rankTrend: { ...base, observation: { lifecycle: { stage } } } })])
    }

    expect(addAutoFavorite).not.toHaveBeenCalled()
  })

  it('does not add when lifecycle stage is missing', () => {
    const { deps, addAutoFavorite } = createDeps()
    const service = new AutoFavoriteSyncService(deps)
    const base = createStock().rankTrend

    service.sync([createStock({ rankTrend: { ...base, observation: { lifecycle: undefined } } })])

    expect(addAutoFavorite).not.toHaveBeenCalled()
  })

  it('removes auto favorites whose lifecycle turns to cooling or high_reversal even while golden in pool', () => {
    const { deps, removeAutoFavorite, listAutoFavorites } = createDeps()
    listAutoFavorites.mockReturnValue([{ code: '000001' }, { code: '000002' }])
    const service = new AutoFavoriteSyncService(deps)
    const base = createStock().rankTrend

    service.sync([
      createStock({ rankTrend: { ...base, observation: { lifecycle: { stage: 'cooling' } } } }),
      createStock({ code: '000002', rankTrend: { ...base, observation: { lifecycle: { stage: 'high_reversal' } } } }),
    ])

    expect(removeAutoFavorite).toHaveBeenCalledWith('000001')
    expect(removeAutoFavorite).toHaveBeenCalledWith('000002')
  })

  it('keeps auto favorites whose lifecycle stays in ignition/expansion while golden in pool', () => {
    const { deps, removeAutoFavorite, listAutoFavorites } = createDeps()
    listAutoFavorites.mockReturnValue([{ code: '000001' }])
    const service = new AutoFavoriteSyncService(deps)

    service.sync([createStock({ rankTrend: { ...createStock().rankTrend, observation: { lifecycle: { stage: 'ignition' } } } })])

    expect(removeAutoFavorite).not.toHaveBeenCalled()
  })

  it('does not remove an auto favorite for a missing lifecycle stage when macd is not death', () => {
    const { deps, removeAutoFavorite, listAutoFavorites } = createDeps()
    listAutoFavorites.mockReturnValue([{ code: '000001' }])
    const service = new AutoFavoriteSyncService(deps)
    const base = createStock().rankTrend

    service.sync([createStock({ rankTrend: { ...base, observation: { lifecycle: undefined } } })])

    expect(removeAutoFavorite).not.toHaveBeenCalled()
  })

  it('skips stocks already in favorites', () => {
    const { deps, addAutoFavorite, isFavorite } = createDeps()
    isFavorite.mockReturnValue(true)
    const service = new AutoFavoriteSyncService(deps)

    const result = service.sync([createStock()])

    expect(addAutoFavorite).not.toHaveBeenCalled()
    expect(result.added).toEqual([])
  })

  it('removes auto favorites whose macd turns to death cross', () => {
    const { deps, removeAutoFavorite, listAutoFavorites } = createDeps()
    listAutoFavorites.mockReturnValue([{ code: '000001' }, { code: '000002' }])
    const service = new AutoFavoriteSyncService(deps)

    const result = service.sync([
      createStock(), // 000001: golden，保留
      createStock({ code: '000002', rankTrend: { technical: { macd: { cross: 'death' } }, resonance: { status: 'ok', direction: 'buy' } } }),
    ])

    expect(removeAutoFavorite).toHaveBeenCalledWith('000002')
    expect(removeAutoFavorite).not.toHaveBeenCalledWith('000001')
    expect(result.removed).toEqual(['000002'])
  })

  it('removes auto favorites that left the hotlist pool', () => {
    const { deps, removeAutoFavorite, listAutoFavorites } = createDeps()
    listAutoFavorites.mockReturnValue([{ code: '000003' }])
    const service = new AutoFavoriteSyncService(deps)

    const result = service.sync([createStock()])

    expect(removeAutoFavorite).toHaveBeenCalledWith('000003')
    expect(result.removed).toEqual(['000003'])
  })

  it('keeps auto favorites that are still golden and still in the pool', () => {
    const { deps, removeAutoFavorite, listAutoFavorites } = createDeps()
    listAutoFavorites.mockReturnValue([{ code: '000001' }])
    const service = new AutoFavoriteSyncService(deps)

    const result = service.sync([createStock()])

    expect(removeAutoFavorite).not.toHaveBeenCalled()
    expect(result.removed).toEqual([])
  })

  it('never removes favorites when the auto-source list is empty (manual stays untouched)', () => {
    const { deps, removeAutoFavorite, listAutoFavorites } = createDeps()
    listAutoFavorites.mockReturnValue([]) // manual 自选不会被 auto 列表枚举
    const service = new AutoFavoriteSyncService(deps)

    const result = service.sync([createStock()])

    expect(removeAutoFavorite).not.toHaveBeenCalled()
    expect(result.removed).toEqual([])
  })

  it('keeps manual favorites untouched through the real store auto-source filter', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    try {
      dataLayer.reset()
      dataLayer.setMergedStocks([
        { code: '600584', name: '长电科技', price: 58.05, change: 6.89 },
      ])
      const store = useFavoriteStore()
      store.init()
      store.addToFavorites('600584') // manual 来源

      const service = new AutoFavoriteSyncService({})
      // 600584 不在本轮热榜且无 rankTrend：manual 来源绝不能被自动删除
      service.sync([createStock({ code: '000001' })])

      expect(store.favorites.has('600584')).toBe(true)
    } finally {
      disposePinia(pinia)
    }
  })

  it('does nothing when the stock list is empty', () => {
    const { deps, addAutoFavorite, removeAutoFavorite, isFavorite, listAutoFavorites } = createDeps()
    const service = new AutoFavoriteSyncService(deps)

    const result = service.sync([])

    expect(isFavorite).not.toHaveBeenCalled()
    expect(listAutoFavorites).not.toHaveBeenCalled()
    expect(addAutoFavorite).not.toHaveBeenCalled()
    expect(removeAutoFavorite).not.toHaveBeenCalled()
    expect(result).toEqual({ added: [], removed: [] })
  })

  it('skips with a warning when the favorite store is unavailable and no ops are injected', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const service = new AutoFavoriteSyncService({})

    const result = service.sync([createStock()])

    expect(warnSpy).toHaveBeenCalled()
    expect(result).toEqual({ added: [], removed: [] })
    warnSpy.mockRestore()
  })
})
