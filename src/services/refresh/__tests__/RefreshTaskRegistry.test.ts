import { describe, expect, it, vi } from 'vitest'

import {
  REFRESH_TASK_DEFINITIONS,
  RefreshTaskRegistry,
  createRefreshTaskRegistry,
} from '../RefreshTaskRegistry'

describe('RefreshTaskRegistry', () => {
  it('registers the Phase 2 task inventory with observable default state', () => {
    const registry = createRefreshTaskRegistry()

    expect(registry.listTasks().map((task) => task.id)).toEqual([
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

    expect(registry.getTask('dataLoader.quote')).toMatchObject({
      id: 'dataLoader.quote',
      label: 'HTTP 行情兜底',
      enabled: true,
      running: false,
      intervalMs: 30_000,
      source: 'registered',
      lastRunAt: null,
      lastSuccessAt: null,
      lastError: null,
    })

    expect(registry.getTask('snapshot.backupSync')?.intervalMs).toBe(300_000)
  })

  it('defines Phase 5 visibility policies for migrated and residual timers', () => {
    const registry = createRefreshTaskRegistry()

    expect(registry.getTask('dataLoader.quote')).toMatchObject({
      tradingTimeOnly: true,
      visibilityPolicy: 'slow',
      hiddenIntervalMs: 120_000,
    })
    expect(registry.getTask('dataLoader.ranktrendSignal')).toMatchObject({
      tradingTimeOnly: false,
      visibilityPolicy: 'run',
    })
    expect(registry.getTask('theme.runtime')).toMatchObject({
      tradingTimeOnly: false,
      visibilityPolicy: 'pause',
    })
    expect(registry.getTask('dragon.breath')).toMatchObject({
      tradingTimeOnly: true,
      visibilityPolicy: 'pause',
    })
    expect(registry.getTask('alert.check')).toMatchObject({
      tradingTimeOnly: false,
      visibilityPolicy: 'pause',
    })
    expect(registry.getTask('snapshot.sweep')).toMatchObject({
      tradingTimeOnly: true,
      visibilityPolicy: 'run',
    })
    expect(registry.getTask('snapshot.backupSync')).toMatchObject({
      tradingTimeOnly: true,
      visibilityPolicy: 'run',
    })
    expect(registry.getTask('websocket.staleCheck')).toMatchObject({
      tradingTimeOnly: false,
      visibilityPolicy: 'slow',
      hiddenIntervalMs: 5_000,
    })
    expect(registry.getTask('hotStockEvent.monitor')).toMatchObject({
      tradingTimeOnly: false,
      visibilityPolicy: 'pause',
    })
  })

  it('updates task state for start, success, failure and enable toggles', () => {
    const now = vi.fn()
      .mockReturnValueOnce(1_000)
      .mockReturnValueOnce(1_500)
      .mockReturnValueOnce(2_000)
      .mockReturnValueOnce(2_500)

    const registry = new RefreshTaskRegistry(now)
    registry.register({
      id: 'example.task',
      label: '示例任务',
      category: 'business',
      owner: 'test',
      intervalMs: 5_000,
    })

    registry.markStarted('example.task', 'manual')
    expect(registry.getTask('example.task')).toMatchObject({
      enabled: true,
      running: true,
      lastRunAt: 1_000,
      lastSuccessAt: null,
      lastError: null,
      source: 'manual',
    })

    registry.markSuccess('example.task', 'manual')
    expect(registry.getTask('example.task')).toMatchObject({
      running: false,
      lastRunAt: 1_000,
      lastSuccessAt: 1_500,
      lastError: null,
      successCount: 1,
    })

    registry.markStarted('example.task', 'scheduler')
    registry.markFailure('example.task', new Error('boom'), 'scheduler')
    expect(registry.getTask('example.task')).toMatchObject({
      running: false,
      lastRunAt: 2_000,
      lastSuccessAt: 1_500,
      lastError: 'boom',
      failureCount: 1,
      source: 'scheduler',
    })

    registry.setEnabled('example.task', false)
    expect(registry.getTask('example.task')).toMatchObject({
      enabled: false,
      running: false,
    })
  })

  it('preserves runtime state when an existing task is registered again', () => {
    const registry = createRefreshTaskRegistry()

    registry.markStarted('theme.runtime', 'scheduler')
    registry.register({
      ...REFRESH_TASK_DEFINITIONS.find((task) => task.id === 'theme.runtime')!,
      label: '题材运行态刷新',
      intervalMs: 10_000,
    })

    expect(registry.getTask('theme.runtime')).toMatchObject({
      label: '题材运行态刷新',
      intervalMs: 10_000,
      running: true,
      source: 'scheduler',
    })
  })
})
