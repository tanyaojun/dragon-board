import { afterEach, describe, expect, it, vi } from 'vitest'

import { refreshCoordinator } from '../RefreshCoordinator'

describe('RefreshCoordinator service registry', () => {
  afterEach(() => {
    ;(refreshCoordinator as any).destroy?.()
    ;(refreshCoordinator as any).reset?.()
    ;(refreshCoordinator as any).pendingRequests?.clear()
    ;(refreshCoordinator as any).services?.clear()
    ;(refreshCoordinator as any).setupListeners?.()
    vi.unstubAllGlobals()
  })

  it('does not run a second dataLoader merge after runUpdate', () => {
    const registry = (refreshCoordinator as any).SERVICE_REGISTRY as Array<{
      name: string
      fullMethod?: string
      syncMethod?: string
    }>

    expect(registry.find((service) => service.name === 'dataLoader')).toEqual(
      expect.objectContaining({
        fullMethod: 'runUpdate',
      }),
    )
    expect(registry.find((service) => service.name === 'dataLoader')).not.toHaveProperty(
      'syncMethod',
    )
    expect(registry.find((service) => service.name === 'algorithmManager')).toEqual(
      expect.objectContaining({
        fullMethod: 'runFullUpdate',
      }),
    )
  })

  it('executes a normalized request and returns structured task results', async () => {
    ;(refreshCoordinator as any).reset()
    ;(refreshCoordinator as any).pendingRequests.clear()
    ;(refreshCoordinator as any).services.clear()

    const runUpdate = vi.fn(async () => 'loaded')
    const runTheme = vi.fn(async () => undefined)
    const syncTheme = vi.fn(async () => undefined)

    refreshCoordinator.registerService('dataLoader', { runUpdate })
    refreshCoordinator.registerService('themeRuntime', { runUpdate: runTheme, syncData: syncTheme })

    await expect(
      refreshCoordinator.executeRequest({
        kind: 'full',
        source: 'test',
        trigger: 'manual',
        force: true,
      }),
    ).resolves.toMatchObject({
      kind: 'full',
      source: 'test',
      success: true,
      skipped: false,
      busy: false,
      errors: {},
      executedTasks: ['dataLoader', 'themeRuntime'],
    })
  })

  it('returns busy when a normalized request overlaps an active execution', async () => {
    ;(refreshCoordinator as any).reset()
    ;(refreshCoordinator as any).pendingRequests.clear()
    ;(refreshCoordinator as any).services.clear()

    let release!: () => void
    refreshCoordinator.registerService('dataLoader', {
      runUpdate: vi.fn(
        () =>
          new Promise<void>((resolve) => {
            release = resolve
          }),
      ),
    })

    const first = refreshCoordinator.executeRequest({
      kind: 'full',
      source: 'first',
      trigger: 'manual',
      force: true,
    })

    await expect(
      refreshCoordinator.executeRequest({
        kind: 'full',
        source: 'second',
        trigger: 'manual',
        force: true,
      }),
    ).resolves.toMatchObject({
      success: false,
      skipped: false,
      busy: true,
      executedTasks: [],
    })

    release()
    await first
  })

  it('throttles repeated forced requests from the same source', async () => {
    ;(refreshCoordinator as any).reset()
    ;(refreshCoordinator as any).pendingRequests.clear()
    ;(refreshCoordinator as any).services.clear()

    refreshCoordinator.registerService('dataLoader', {
      runUpdate: vi.fn(async () => undefined),
    })

    await refreshCoordinator.executeRequest({
      kind: 'full',
      source: 'same-button',
      trigger: 'manual',
      force: true,
    })

    await expect(
      refreshCoordinator.executeRequest({
        kind: 'full',
        source: 'same-button',
        trigger: 'manual',
        force: true,
      }),
    ).resolves.toMatchObject({
      success: false,
      skipped: true,
      busy: false,
      reason: 'request-throttled',
    })
  })

  it('forwards legacy refresh events to an uninitialized manager instead of executing directly', async () => {
    ;(refreshCoordinator as any).reset()
    ;(refreshCoordinator as any).pendingRequests.clear()
    ;(refreshCoordinator as any).services.clear()

    const requestRefresh = vi.fn(async () => undefined)
    const runUpdate = vi.fn(async () => undefined)
    refreshCoordinator.registerService('dataLoader', { runUpdate })
    vi.stubGlobal('window', {
      RefreshManager: {
        getStatus: () => ({ initialized: false }),
        requestRefresh,
      },
    })

    const { EventManager } = await import('../../utils/eventManager')
    const { AppEvents } = await import('../../types')

    EventManager.emit(AppEvents.REFRESH.MANUAL_REQUESTED, {
      source: 'legacy',
      force: true,
    })
    await Promise.resolve()

    expect(requestRefresh).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'full',
        source: 'legacy',
        trigger: 'manual',
        force: true,
      }),
    )
    expect(runUpdate).not.toHaveBeenCalled()
  })

  it('does not execute legacy refresh events directly when the manager is unavailable', async () => {
    ;(refreshCoordinator as any).reset()
    ;(refreshCoordinator as any).pendingRequests.clear()
    ;(refreshCoordinator as any).services.clear()

    const runUpdate = vi.fn(async () => undefined)
    refreshCoordinator.registerService('dataLoader', { runUpdate })

    const { EventManager } = await import('../../utils/eventManager')
    const { AppEvents } = await import('../../types')

    EventManager.emit(AppEvents.REFRESH.MANUAL_REQUESTED, {
      source: 'legacy-without-manager',
      force: true,
    })
    await Promise.resolve()

    expect(runUpdate).not.toHaveBeenCalled()
  })

  it('leaves legacy refresh events to RefreshManager when the manager is mounted', async () => {
    ;(refreshCoordinator as any).reset()
    ;(refreshCoordinator as any).pendingRequests.clear()
    ;(refreshCoordinator as any).services.clear()

    const runUpdate = vi.fn(async () => undefined)
    refreshCoordinator.registerService('dataLoader', { runUpdate })
    vi.stubGlobal('window', { RefreshManager: { requestRefresh: vi.fn() } })

    const { EventManager } = await import('../../utils/eventManager')
    const { AppEvents } = await import('../../types')

    EventManager.emit(AppEvents.REFRESH.MANUAL_REQUESTED, {
      source: 'legacy',
      force: true,
    })
    await Promise.resolve()

    expect(runUpdate).not.toHaveBeenCalled()
  })

  it('does not auto-register services from window after import', async () => {
    vi.useFakeTimers()
    try {
      vi.stubGlobal('window', {
        dataLoader: { runUpdate: vi.fn(async () => undefined) },
      })

      vi.resetModules()
      const { refreshCoordinator: importedCoordinator } = await import('../RefreshCoordinator')
      await vi.advanceTimersByTimeAsync(6_000)

      expect(importedCoordinator.getStatus().registeredServices).not.toContain('dataLoader')
      importedCoordinator.destroy?.()
    } finally {
      vi.useRealTimers()
      vi.resetModules()
    }
  })

  it('removes legacy refresh event listeners when destroyed', async () => {
    ;(refreshCoordinator as any).reset()
    ;(refreshCoordinator as any).pendingRequests.clear()
    ;(refreshCoordinator as any).services.clear()

    const requestRefresh = vi.fn(async () => undefined)
    vi.stubGlobal('window', {
      RefreshManager: {
        getStatus: () => ({ initialized: false }),
        requestRefresh,
      },
    })

    refreshCoordinator.destroy()

    const { EventManager } = await import('../../utils/eventManager')
    const { AppEvents } = await import('../../types')

    EventManager.emit(AppEvents.REFRESH.MANUAL_REQUESTED, {
      source: 'legacy-after-destroy',
      force: true,
    })
    await Promise.resolve()

    expect(requestRefresh).not.toHaveBeenCalled()
  })
})
