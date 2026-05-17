import type { RefreshTaskId, RefreshTaskRunner } from './types'
import { RefreshTaskRegistry } from './RefreshTaskRegistry'

interface RefreshSchedulerOptions {
  now?: () => number
  isTradingTime?: () => boolean
  isVisible?: () => boolean
}

export class RefreshScheduler {
  private timers = new Map<RefreshTaskId, ReturnType<typeof setInterval>>()
  private runners = new Map<RefreshTaskId, RefreshTaskRunner>()
  private readonly now: () => number
  private readonly isTradingTime: () => boolean
  private readonly isVisible: () => boolean

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

  startTask(id: RefreshTaskId): boolean {
    const task = this.registry.getTask(id)
    if (!task?.intervalMs || this.timers.has(id)) return false

    const timer = setInterval(() => {
      void this.runTask(id)
    }, task.intervalMs)

    this.timers.set(id, timer)
    return true
  }

  stopTask(id: RefreshTaskId): boolean {
    const timer = this.timers.get(id)
    if (!timer) return false
    clearInterval(timer)
    this.timers.delete(id)
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
  }

  async runTask(id: RefreshTaskId): Promise<boolean> {
    const task = this.registry.getTask(id)
    const runner = this.runners.get(id)
    if (!task || !runner || !this.canRun(task)) return false

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
    if (task.tradingTimeOnly && !this.isTradingTime()) return false
    if (!task.runWhenHidden && !this.isVisible()) return false
    return true
  }
}
