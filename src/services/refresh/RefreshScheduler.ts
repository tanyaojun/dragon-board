import type { RefreshSchedulerPolicy, RefreshTaskId, RefreshTaskRunner } from './types'
import { RefreshTaskRegistry } from './RefreshTaskRegistry'

interface RefreshSchedulerOptions {
  now?: () => number
  isTradingTime?: () => boolean
  isVisible?: () => boolean
}

export class RefreshScheduler {
  private timers = new Map<RefreshTaskId, ReturnType<typeof setInterval>>()
  private runners = new Map<RefreshTaskId, RefreshTaskRunner>()
  private lastRunByTask = new Map<RefreshTaskId, number>()
  private readonly now: () => number
  private readonly isTradingTime: () => boolean
  private readonly isVisible: () => boolean
  private policy: RefreshSchedulerPolicy = {
    tradingTimeOnly: true,
    defaultVisibilityPolicy: 'pause',
  }

  constructor(
    private readonly registry: RefreshTaskRegistry,
    options: RefreshSchedulerOptions = {},
  ) {
    this.now = options.now ?? (() => Date.now())
    this.isTradingTime = options.isTradingTime ?? (() => true)
    this.isVisible =
      options.isVisible ??
      (() => typeof document === 'undefined' || document.visibilityState !== 'hidden')
  }

  registerRunner(id: RefreshTaskId, runner: RefreshTaskRunner): void {
    this.runners.set(id, runner)
  }

  setPolicy(policy: Partial<RefreshSchedulerPolicy>): void {
    this.policy = {
      ...this.policy,
      ...policy,
    }
  }

  getPolicy(): RefreshSchedulerPolicy {
    return { ...this.policy }
  }

  startTask(id: RefreshTaskId, intervalMs?: number): boolean {
    const task = this.registry.getTask(id)
    const effectiveInterval = intervalMs ?? task?.intervalMs
    if (!task || !effectiveInterval || this.timers.has(id)) return false

    const timer = setInterval(() => {
      void this.runTask(id)
    }, effectiveInterval)

    this.timers.set(id, timer)
    return true
  }

  stopTask(id: RefreshTaskId): boolean {
    const timer = this.timers.get(id)
    if (!timer) return false
    clearInterval(timer)
    this.timers.delete(id)
    this.lastRunByTask.delete(id)
    return true
  }

  startAll(): void {
    this.registry.listTasks().forEach((task) => {
      this.startTask(task.id)
    })
  }

  stopAll(): void {
    Array.from(this.timers.keys()).forEach((id) => this.stopTask(id))
  }

  destroy(): void {
    this.stopAll()
    this.runners.clear()
    this.lastRunByTask.clear()
  }

  async runTask(id: RefreshTaskId): Promise<boolean> {
    const task = this.registry.getTask(id)
    const runner = this.runners.get(id)
    if (!task || !runner || !this.canRun(task)) return false

    this.lastRunByTask.set(id, this.now())
    this.registry.markStarted(id, 'scheduler')

    try {
      await runner()
      this.registry.markSuccess(id, 'scheduler')
      return true
    } catch (error) {
      this.registry.markFailure(id, error, 'scheduler')
      return false
    }
  }

  private canRun(task: NonNullable<ReturnType<RefreshTaskRegistry['getTask']>>): boolean {
    if (!task.enabled || task.running) return false
    if (this.policy.tradingTimeOnly && task.tradingTimeOnly && !this.isTradingTime()) return false
    const visible = this.isVisible()
    const visibilityPolicy =
      task.visibilityPolicy ?? (task.runWhenHidden ? 'run' : this.policy.defaultVisibilityPolicy)
    if (!visible && visibilityPolicy === 'pause') return false
    if (!visible && visibilityPolicy === 'slow') {
      const hiddenIntervalMs = task.hiddenIntervalMs || task.intervalMs || 0
      const lastRunAt = this.lastRunByTask.get(task.id) ?? task.lastSuccessAt ?? 0
      if (lastRunAt && hiddenIntervalMs > 0 && this.now() - lastRunAt < hiddenIntervalMs) {
        return false
      }
    }
    return true
  }
}
