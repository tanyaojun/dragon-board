import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RefreshScheduler } from '../RefreshScheduler'
import { RefreshTaskRegistry } from '../RefreshTaskRegistry'

describe('RefreshScheduler', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('runs enabled scheduled tasks and records success', async () => {
    const now = vi.fn().mockReturnValue(1_000)
    const registry = new RefreshTaskRegistry(now)
    const run = vi.fn(async () => undefined)

    registry.register({
      id: 'example.task',
      label: '示例任务',
      category: 'business',
      owner: 'test',
      intervalMs: 1_000,
    })

    const scheduler = new RefreshScheduler(registry, { now })
    scheduler.registerRunner('example.task', run)
    scheduler.startTask('example.task')

    await vi.advanceTimersByTimeAsync(1_000)

    expect(run).toHaveBeenCalledTimes(1)
    expect(registry.getTask('example.task')).toMatchObject({
      running: false,
      lastRunAt: 1_000,
      lastSuccessAt: 1_000,
      lastError: null,
      source: 'scheduler',
    })

    scheduler.destroy()
  })

  it('skips disabled tasks without calling the runner', async () => {
    const registry = new RefreshTaskRegistry()
    const run = vi.fn(async () => undefined)

    registry.register({
      id: 'example.task',
      label: '示例任务',
      category: 'business',
      owner: 'test',
      intervalMs: 1_000,
      enabled: false,
    })

    const scheduler = new RefreshScheduler(registry)
    scheduler.registerRunner('example.task', run)
    scheduler.startTask('example.task')

    await vi.advanceTimersByTimeAsync(1_000)

    expect(run).not.toHaveBeenCalled()
    expect(registry.getTask('example.task')?.running).toBe(false)

    scheduler.destroy()
  })

  it('records runner failures and releases the running flag', async () => {
    const registry = new RefreshTaskRegistry(() => 2_000)
    const run = vi.fn(async () => {
      throw new Error('failed')
    })

    registry.register({
      id: 'example.task',
      label: '示例任务',
      category: 'business',
      owner: 'test',
      intervalMs: 1_000,
    })

    const scheduler = new RefreshScheduler(registry)
    scheduler.registerRunner('example.task', run)
    scheduler.startTask('example.task')

    await vi.advanceTimersByTimeAsync(1_000)

    expect(registry.getTask('example.task')).toMatchObject({
      running: false,
      lastRunAt: 2_000,
      lastSuccessAt: null,
      lastError: 'failed',
      failureCount: 1,
    })

    scheduler.destroy()
  })

  it('honors trading time and visibility policies before running a task', async () => {
    const registry = new RefreshTaskRegistry()
    const run = vi.fn(async () => undefined)
    let tradingTime = false
    let visible = false

    registry.register({
      id: 'example.task',
      label: '示例任务',
      category: 'business',
      owner: 'test',
      intervalMs: 1_000,
      runWhenHidden: false,
      tradingTimeOnly: true,
    })

    const scheduler = new RefreshScheduler(registry, {
      isTradingTime: () => tradingTime,
      isVisible: () => visible,
    })
    scheduler.registerRunner('example.task', run)
    scheduler.startTask('example.task')

    await vi.advanceTimersByTimeAsync(1_000)
    expect(run).not.toHaveBeenCalled()

    tradingTime = true
    await vi.advanceTimersByTimeAsync(1_000)
    expect(run).not.toHaveBeenCalled()

    visible = true
    await vi.advanceTimersByTimeAsync(1_000)
    expect(run).toHaveBeenCalledTimes(1)

    scheduler.destroy()
  })

  it('allows global policy to relax trading-time gating for scheduled tasks', async () => {
    const registry = new RefreshTaskRegistry()
    const run = vi.fn(async () => undefined)

    registry.register({
      id: 'example.task',
      label: '示例任务',
      category: 'market',
      owner: 'test',
      intervalMs: 1_000,
      tradingTimeOnly: true,
    })

    const scheduler = new RefreshScheduler(registry, {
      isTradingTime: () => false,
    })
    scheduler.registerRunner('example.task', run)
    scheduler.startTask('example.task')

    await vi.advanceTimersByTimeAsync(1_000)
    expect(run).not.toHaveBeenCalled()

    scheduler.setPolicy({ tradingTimeOnly: false })
    await vi.advanceTimersByTimeAsync(1_000)
    expect(run).toHaveBeenCalledTimes(1)

    scheduler.destroy()
  })

  it('resets shared scheduler policy with the refresh task runtime', async () => {
    const runtime = await import('../RefreshTaskRuntime')

    runtime.refreshScheduler.setPolicy({ tradingTimeOnly: false })
    runtime.resetRefreshTaskRuntime()

    expect(runtime.refreshScheduler.getPolicy()).toMatchObject({
      tradingTimeOnly: true,
      defaultVisibilityPolicy: 'pause',
    })
  })

  it('pauses hidden-page tasks with visibility policy pause', async () => {
    const registry = new RefreshTaskRegistry()
    const run = vi.fn(async () => undefined)
    let visible = false

    registry.register({
      id: 'example.task',
      label: '示例任务',
      category: 'business',
      owner: 'test',
      intervalMs: 1_000,
      visibilityPolicy: 'pause',
      tradingTimeOnly: false,
    })

    const scheduler = new RefreshScheduler(registry, {
      isVisible: () => visible,
    })
    scheduler.registerRunner('example.task', run)
    scheduler.startTask('example.task')

    await vi.advanceTimersByTimeAsync(1_000)
    expect(run).not.toHaveBeenCalled()

    visible = true
    await vi.advanceTimersByTimeAsync(1_000)
    expect(run).toHaveBeenCalledTimes(1)

    scheduler.destroy()
  })

  it('slows hidden-page tasks according to visibility slow interval', async () => {
    const registry = new RefreshTaskRegistry()
    const run = vi.fn(async () => undefined)
    let visible = false

    registry.register({
      id: 'example.task',
      label: '示例任务',
      category: 'market',
      owner: 'test',
      intervalMs: 1_000,
      visibilityPolicy: 'slow',
      hiddenIntervalMs: 5_000,
      tradingTimeOnly: false,
    })

    const scheduler = new RefreshScheduler(registry, {
      now: () => Date.now(),
      isVisible: () => visible,
    })
    scheduler.registerRunner('example.task', run)
    scheduler.startTask('example.task')

    await vi.advanceTimersByTimeAsync(1_000)
    expect(run).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(1_000)
    expect(run).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(4_000)
    expect(run).toHaveBeenCalledTimes(2)

    visible = true
    await vi.advanceTimersByTimeAsync(1_000)
    expect(run).toHaveBeenCalledTimes(3)

    scheduler.destroy()
  })

  it('keeps slow hidden-page cadence after runner failures', async () => {
    const registry = new RefreshTaskRegistry()
    const run = vi.fn(async () => {
      throw new Error('temporary')
    })

    registry.register({
      id: 'example.task',
      label: '示例任务',
      category: 'market',
      owner: 'test',
      intervalMs: 1_000,
      visibilityPolicy: 'slow',
      hiddenIntervalMs: 5_000,
      tradingTimeOnly: false,
    })

    const scheduler = new RefreshScheduler(registry, {
      now: () => Date.now(),
      isVisible: () => false,
    })
    scheduler.registerRunner('example.task', run)
    scheduler.startTask('example.task')

    await vi.advanceTimersByTimeAsync(1_000)
    expect(run).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(1_000)
    expect(run).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(4_000)
    expect(run).toHaveBeenCalledTimes(2)

    scheduler.destroy()
  })

  it('allows callers to override the registered interval when starting a task', async () => {
    const registry = new RefreshTaskRegistry()
    const run = vi.fn(async () => undefined)

    registry.register({
      id: 'example.task',
      label: '示例任务',
      category: 'business',
      owner: 'test',
      intervalMs: 60_000,
    })

    const scheduler = new RefreshScheduler(registry)
    scheduler.registerRunner('example.task', run)
    scheduler.startTask('example.task', 1_000)

    await vi.advanceTimersByTimeAsync(1_000)

    expect(run).toHaveBeenCalledTimes(1)

    scheduler.destroy()
  })

  it('keeps registered runners when only stopping all timers', async () => {
    const registry = new RefreshTaskRegistry()
    const run = vi.fn(async () => undefined)

    registry.register({
      id: 'example.task',
      label: '示例任务',
      category: 'business',
      owner: 'test',
      intervalMs: 1_000,
    })

    const scheduler = new RefreshScheduler(registry)
    scheduler.registerRunner('example.task', run)
    scheduler.startTask('example.task')
    scheduler.stopAll()
    scheduler.startTask('example.task')

    await vi.advanceTimersByTimeAsync(1_000)

    expect(run).toHaveBeenCalledTimes(1)

    scheduler.destroy()
  })
})
