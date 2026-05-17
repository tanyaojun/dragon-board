import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type RefreshManagerModule = typeof import('../RefreshManager')

const storage = (() => {
  const values = new Map<string, string>()
  return {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      values.set(key, value)
    }),
    removeItem: vi.fn((key: string) => {
      values.delete(key)
    }),
    clear: vi.fn(() => {
      values.clear()
    }),
  }
})()

async function loadRefreshManager(options: {
  manualRefresh?: () => Promise<boolean>
  isTradingTime?: () => boolean
} = {}): Promise<RefreshManagerModule & { coordinatorManualRefresh: ReturnType<typeof vi.fn> }> {
  vi.resetModules()

  const manualRefresh = vi.fn(options.manualRefresh || (() => Promise.resolve(true)))
  const isTradingTime = vi.fn(options.isTradingTime || (() => true))

  vi.doMock('../RefreshCoordinator', () => ({
    refreshCoordinator: {
      getStatus: vi.fn(() => ({ isRefreshing: false })),
      manualRefresh,
    },
  }))

  vi.doMock('../DataLayer', () => ({
    dataLayer: {
      getStocks: vi.fn(() => []),
    },
  }))

  vi.doMock('../../utils/time', () => ({
    isTradingTime,
  }))

  const module = await import('../RefreshManager')
  return { ...module, coordinatorManualRefresh: manualRefresh }
}

describe('RefreshManager Phase 0 behavior', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    storage.clear()
    vi.stubGlobal('localStorage', storage)
  })

  afterEach(async () => {
    const { RefreshManager } = await import('../RefreshManager')
    RefreshManager.destroy()
    vi.unstubAllGlobals()
    vi.useRealTimers()
    vi.resetModules()
    vi.clearAllMocks()
  })

  it('resets refreshing state after manual refresh succeeds', async () => {
    const { RefreshManager } = await loadRefreshManager({
      manualRefresh: () => Promise.resolve(true),
    })

    await RefreshManager.init()

    await expect(RefreshManager.manualRefresh('full')).resolves.toBe(true)

    expect(RefreshManager.getStatus().isRefreshing).toBe(false)
  })

  it('resets refreshing state after manual refresh fails', async () => {
    const { RefreshManager } = await loadRefreshManager({
      manualRefresh: () => Promise.resolve(false),
    })

    await RefreshManager.init()

    await expect(RefreshManager.manualRefresh('full')).resolves.toBe(false)

    expect(RefreshManager.getStatus().isRefreshing).toBe(false)
  })

  it('blocks concurrent manual refresh requests and releases the lock when the first finishes', async () => {
    let resolveFirst!: (value: boolean) => void
    const firstRefresh = new Promise<boolean>((resolve) => {
      resolveFirst = resolve
    })

    const { RefreshManager } = await loadRefreshManager({
      manualRefresh: () => firstRefresh,
    })

    await RefreshManager.init()

    const first = RefreshManager.manualRefresh('full')
    await expect(RefreshManager.manualRefresh('full')).resolves.toBe(false)

    resolveFirst(true)
    await expect(first).resolves.toBe(true)

    expect(RefreshManager.getStatus().isRefreshing).toBe(false)
  })

  it('does not call the coordinator when manual refresh is disabled', async () => {
    const { RefreshManager, coordinatorManualRefresh } = await loadRefreshManager()

    await RefreshManager.init()
    RefreshManager.toggleAllowManualRefresh(false)

    await expect(RefreshManager.manualRefresh('full')).resolves.toBe(false)

    expect(coordinatorManualRefresh).not.toHaveBeenCalled()
    expect(RefreshManager.getStatus().isRefreshing).toBe(false)
  })

  it('keeps the trading checker alive after pausing outside trading time', async () => {
    let trading = true
    const { RefreshManager } = await loadRefreshManager({
      isTradingTime: () => trading,
    })

    await RefreshManager.init()
    expect(RefreshManager.start()).toBe(true)
    expect(RefreshManager.getStatus().isRunning).toBe(true)

    trading = false
    await vi.advanceTimersByTimeAsync(60_000)
    expect(RefreshManager.getStatus().isRunning).toBe(false)

    trading = true
    await vi.advanceTimersByTimeAsync(60_000)
    expect(RefreshManager.getStatus().isRunning).toBe(true)
  })

  it('exposes the registered refresh task inventory for diagnostics', async () => {
    const { RefreshManager } = await loadRefreshManager()

    await RefreshManager.init()

    expect(RefreshManager.getStatus().tasks.map((task) => task.id)).toEqual([
      'dataLoader.full',
      'dataLoader.quote',
      'dataLoader.ranktrendSignal',
      'theme.runtime',
      'dragon.breath',
      'dragon.review',
      'alert.check',
      'snapshot.sweep',
      'snapshot.backupSync',
      'websocket.staleCheck',
    ])
  })

  it('does not reset shared task runtime state when resetting manager config', async () => {
    const { RefreshManager } = await loadRefreshManager()

    await RefreshManager.init()
    const { refreshTaskRegistry } = await import('../refresh/RefreshTaskRuntime')
    refreshTaskRegistry.markStarted('theme.runtime', 'scheduler')
    refreshTaskRegistry.markSuccess('theme.runtime', 'scheduler')

    RefreshManager.reset()

    expect(refreshTaskRegistry.getTask('theme.runtime')).toMatchObject({
      lastRunAt: expect.any(Number),
      lastSuccessAt: expect.any(Number),
      successCount: 1,
      source: 'scheduler',
    })
  })

  it('does not stop shared scheduler tasks when destroying the manager', async () => {
    const { RefreshManager } = await loadRefreshManager()

    await RefreshManager.init()
    const { refreshScheduler } = await import('../refresh/RefreshTaskRuntime')
    const run = vi.fn(async () => undefined)
    refreshScheduler.registerRunner('theme.runtime', run)
    refreshScheduler.startTask('theme.runtime', 1_000)

    RefreshManager.destroy()
    await vi.advanceTimersByTimeAsync(1_000)

    expect(run).toHaveBeenCalledTimes(1)
    refreshScheduler.stopTask('theme.runtime')
  })
})
