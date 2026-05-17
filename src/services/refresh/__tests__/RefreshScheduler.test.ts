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
