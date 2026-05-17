import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RefreshRequestResult } from '../refresh/types'

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

const successResult = (overrides: Partial<RefreshRequestResult> = {}): RefreshRequestResult => ({
  kind: 'full',
  source: 'manual',
  success: true,
  skipped: false,
  busy: false,
  duration: 12,
  executedTasks: ['dataLoader'],
  errors: {},
  ...overrides,
})

async function loadRefreshManager(options: {
  executeRequest?: (request: any) => Promise<RefreshRequestResult>
  coordinatorRefreshing?: boolean
  isTradingTime?: () => boolean
} = {}): Promise<RefreshManagerModule & { coordinatorExecuteRequest: ReturnType<typeof vi.fn> }> {
  vi.resetModules()

  const executeRequest = vi.fn(
    options.executeRequest || ((request: any) => Promise.resolve(successResult({ source: request.source }))),
  )
  const isTradingTime = vi.fn(options.isTradingTime || (() => true))

  vi.doMock('../RefreshCoordinator', () => ({
    refreshCoordinator: {
      getStatus: vi.fn(() => ({ isRefreshing: Boolean(options.coordinatorRefreshing) })),
      executeRequest,
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
  return { ...module, coordinatorExecuteRequest: executeRequest }
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
      executeRequest: () => Promise.resolve(successResult()),
    })

    await RefreshManager.init()

    await expect(RefreshManager.manualRefresh('full')).resolves.toBe(true)

    expect(RefreshManager.getStatus().isRefreshing).toBe(false)
  })

  it('resets refreshing state after manual refresh fails', async () => {
    const { RefreshManager } = await loadRefreshManager({
      executeRequest: () => Promise.resolve(successResult({ success: false })),
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
      executeRequest: () => firstRefresh.then((success) => successResult({ success })),
    })

    await RefreshManager.init()

    const first = RefreshManager.manualRefresh('full')
    await expect(RefreshManager.manualRefresh('full')).resolves.toBe(false)

    resolveFirst(true)
    await expect(first).resolves.toBe(true)

    expect(RefreshManager.getStatus().isRefreshing).toBe(false)
  })

  it('does not call the coordinator when manual refresh is disabled', async () => {
    const { RefreshManager, coordinatorExecuteRequest } = await loadRefreshManager()

    await RefreshManager.init()
    RefreshManager.toggleAllowManualRefresh(false)

    await expect(RefreshManager.manualRefresh('full')).resolves.toBe(false)

    expect(coordinatorExecuteRequest).not.toHaveBeenCalled()
    expect(RefreshManager.getStatus().isRefreshing).toBe(false)
  })

  it('returns a structured request result from the unified refresh entry', async () => {
    const { RefreshManager, coordinatorExecuteRequest } = await loadRefreshManager()

    await RefreshManager.init()

    await expect(
      RefreshManager.requestRefresh({
        kind: 'full',
        source: 'app',
        trigger: 'manual',
        force: true,
      }),
    ).resolves.toMatchObject({
      kind: 'full',
      source: 'app',
      success: true,
      skipped: false,
      busy: false,
      executedTasks: ['dataLoader'],
      errors: {},
    })

    expect(coordinatorExecuteRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'full',
        source: 'app',
        trigger: 'manual',
        force: true,
      }),
    )
    expect(RefreshManager.getStatus().isRefreshing).toBe(false)
  })

  it('routes legacy manual refresh events through the unified manager entry', async () => {
    const { RefreshManager, coordinatorExecuteRequest } = await loadRefreshManager()
    const { EventManager } = await import('../../utils/eventManager')
    const { AppEvents } = await import('../../types')

    await RefreshManager.init()

    EventManager.emit(AppEvents.REFRESH.MANUAL_REQUESTED, {
      source: 'data-freshness',
      force: true,
    })
    await Promise.resolve()

    expect(coordinatorExecuteRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'full',
        source: 'data-freshness',
        trigger: 'manual',
        force: true,
      }),
    )
  })

  it('reports busy without invoking the coordinator when a refresh is already running', async () => {
    let resolveFirst!: (value: RefreshRequestResult) => void
    const firstRefresh = new Promise<RefreshRequestResult>((resolve) => {
      resolveFirst = resolve
    })

    const { RefreshManager, coordinatorExecuteRequest } = await loadRefreshManager({
      executeRequest: () => firstRefresh,
    })

    await RefreshManager.init()

    const first = RefreshManager.requestRefresh({ kind: 'full', source: 'app', trigger: 'manual' })
    await expect(
      RefreshManager.requestRefresh({ kind: 'full', source: 'data-freshness', trigger: 'manual' }),
    ).resolves.toMatchObject({
      success: false,
      skipped: false,
      busy: true,
      executedTasks: [],
    })

    resolveFirst(successResult({ source: 'app' }))
    await first

    expect(coordinatorExecuteRequest).toHaveBeenCalledTimes(1)
  })

  it('does not count coordinator-skipped requests as failed refreshes', async () => {
    const { RefreshManager } = await loadRefreshManager({
      executeRequest: (request: any) =>
        Promise.resolve(
          successResult({
            source: request.source,
            success: false,
            skipped: true,
            duration: 0,
            executedTasks: [],
            reason: 'request-throttled',
          }),
        ),
    })

    await RefreshManager.init()

    await expect(
      RefreshManager.requestRefresh({ kind: 'full', source: 'timer', trigger: 'timer', force: true }),
    ).resolves.toMatchObject({
      success: false,
      skipped: true,
      busy: false,
    })

    expect(RefreshManager.getStats().failedRefreshes).toBe(0)
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

  it('starts automatic full refresh immediately when trading-time restriction is disabled outside trading time', async () => {
    const { RefreshManager } = await loadRefreshManager({
      isTradingTime: () => false,
    })

    await RefreshManager.init()
    RefreshManager.toggleEnabled(true)

    expect(RefreshManager.getStatus().isRunning).toBe(false)

    RefreshManager.toggleTradingTimeOnly(false)

    expect(RefreshManager.getStatus().isRunning).toBe(true)
  })

  it('stops automatic full refresh immediately when trading-time restriction is enabled outside trading time', async () => {
    const { RefreshManager } = await loadRefreshManager({
      isTradingTime: () => false,
    })

    await RefreshManager.init()
    RefreshManager.toggleTradingTimeOnly(false)
    expect(RefreshManager.getStatus().isRunning).toBe(true)

    RefreshManager.toggleTradingTimeOnly(true)

    expect(RefreshManager.getStatus().isRunning).toBe(false)
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
      'hotStockEvent.monitor',
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

  it('does not expose legacy incremental refresh config or stats', async () => {
    const { RefreshManager } = await loadRefreshManager()

    await RefreshManager.init()

    expect(RefreshManager.getStatus()).not.toHaveProperty('incrementalRefreshInterval')
    expect(RefreshManager.getStats()).not.toHaveProperty('incrementalRefreshes')
    expect(RefreshManager.getStats()).not.toHaveProperty('lastIncrementalRefreshTime')
  })

  it('drops legacy incremental refresh config when saving stored settings', async () => {
    storage.setItem(
      'refresh-config',
      JSON.stringify({
        enabled: true,
        strategy: 'balanced',
        tradingTimeOnly: true,
        allowManualRefresh: true,
        fullRefreshInterval: 15 * 60 * 1000,
        incrementalRefreshInterval: 1234,
        hotStocksLimit: 100,
        retryOnFailure: true,
        maxRetries: 2,
      }),
    )
    const { RefreshManager } = await loadRefreshManager()

    await RefreshManager.init()
    RefreshManager.updateConfig({ fullRefreshInterval: 30 * 60 * 1000 })

    const saved = JSON.parse(String(storage.setItem.mock.calls.at(-1)?.[1] || '{}'))
    expect(saved.incrementalRefreshInterval).toBeUndefined()
  })
})
