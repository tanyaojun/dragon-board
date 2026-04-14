// src/services/Algorithm/CalculationQueue.ts
// 通用计算队列 - 可被任何模块使用

import { EventManager } from '@/utils/eventManager'

type Priority = 'high' | 'medium' | 'low'

interface QueueTask<T = any> {
  id: string
  task: () => Promise<T>
  priority: Priority
  timestamp: number
  resolve: (value: T) => void
  reject: (reason?: any) => void
  retryCount?: number
  maxRetries?: number
  module?: string
}

interface QueueOptions {
  concurrency?: number
  retryDelay?: number
  timeout?: number
}

export class CalculationQueue {
  private queues: Map<Priority, QueueTask[]> = new Map()
  private processing: Map<Priority, boolean> = new Map()
  private inProgress: Set<string> = new Set()
  private moduleStats: Map<string, { total: number; completed: number; failed: number }> = new Map()

  private stats = {
    totalAdded: 0,
    totalCompleted: 0,
    totalFailed: 0,
    totalTimeout: 0,
  }

  private readonly DEFAULT_OPTIONS: Required<QueueOptions> = {
    concurrency: 3,
    retryDelay: 1000,
    timeout: 30000,
  }

  private options: Required<QueueOptions>

  private destroyed = false

  constructor(options: QueueOptions = {}) {
    this.options = { ...this.DEFAULT_OPTIONS, ...options }

    this.queues.set('high', [])
    this.queues.set('medium', [])
    this.queues.set('low', [])

    this.processing.set('high', false)
    this.processing.set('medium', false)
    this.processing.set('low', false)
  }

  // ========== 供协调者调用的方法 ==========

  /**
   * 后台维护 - 供协调者调用
   */
  async runMaintenance(): Promise<void> {
    if (this.destroyed) return
    console.log('[CalculationQueue] 执行后台维护')

    this.flushStats()
    this.monitorQueue()
  }

  /**
   * 初始化
   */
  init(): () => void {
    if (this.destroyed) {
      console.warn('[CalculationQueue] 实例已销毁，无法初始化')
      return () => {}
    }

    console.log('[CalculationQueue] 📊 初始化...')
    console.log('[CalculationQueue] ✅ 初始化完成')

    return () => this.destroy()
  }

  /**
   * 刷新统计信息
   */
  private flushStats(): void {
    if (this.destroyed) return

    EventManager.emit('queue:stats', {
      ...this.getStatus(),
      timestamp: Date.now(),
    })

    console.log('[CalculationQueue] 📊 队列统计:', this.getStatus())
  }

  /**
   * 监控队列健康状况
   */
  private monitorQueue(): void {
    if (this.destroyed) return

    const status = this.getStatus()
    let longWaitTasks = 0

    this.queues.forEach((queue) => {
      queue.forEach((task) => {
        const waitTime = Date.now() - task.timestamp
        if (waitTime > 60000) {
          longWaitTasks++
        }
      })
    })

    if (longWaitTasks > 0) {
      console.warn(`[CalculationQueue] ⚠️ 有 ${longWaitTasks} 个任务等待超过1分钟`)
    }

    if (this.stats.totalFailed > this.stats.totalCompleted * 0.1) {
      console.warn('[CalculationQueue] ⚠️ 任务失败率过高')
    }
  }

  /**
   * 获取状态
   */
  getStatus() {
    if (this.destroyed) return null

    return {
      queues: {
        high: this.queues.get('high')!.length,
        medium: this.queues.get('medium')!.length,
        low: this.queues.get('low')!.length,
      },
      inProgress: this.inProgress.size,
      stats: { ...this.stats },
      moduleStats: Object.fromEntries(this.moduleStats),
      processing: {
        high: this.processing.get('high'),
        medium: this.processing.get('medium'),
        low: this.processing.get('low'),
      },
      destroyed: this.destroyed,
    }
  }

  /**
   * 添加任务到队列
   */
  add<T>(
    id: string,
    task: () => Promise<T>,
    options?: {
      priority?: Priority
      maxRetries?: number
      timeout?: number
      module?: string
    },
  ): Promise<T> {
    if (this.destroyed) {
      return Promise.reject(new Error('Queue has been destroyed'))
    }

    if (this.inProgress.has(id)) {
      console.log(`[Queue] 任务 ${id} 已在进行中，跳过`)
      return Promise.reject(new Error('Task already in progress'))
    }

    const priority = options?.priority || 'medium'
    const maxRetries = options?.maxRetries || 3
    const timeout = options?.timeout || this.options.timeout
    const module = options?.module || 'default'

    return new Promise<T>((resolve, reject) => {
      const queueTask: QueueTask<T> = {
        id,
        task,
        priority,
        timestamp: Date.now(),
        resolve,
        reject,
        retryCount: 0,
        maxRetries,
        module,
      }

      this.queues.get(priority)!.push(queueTask)
      this.stats.totalAdded++

      this.updateModuleStats(module, 'add')

      console.log(`[Queue] 📥 [${module}] 任务已添加: ${id} (优先级: ${priority})`)

      this.processQueue(priority)
    })
  }

  /**
   * 批量添加任务
   */
  addBatch<T>(
    tasks: Array<{
      id: string
      task: () => Promise<T>
      priority?: Priority
      module?: string
    }>,
  ): Promise<T>[] {
    if (this.destroyed) {
      return tasks.map(() => Promise.reject(new Error('Queue has been destroyed')))
    }

    return tasks.map((t) =>
      this.add(t.id, t.task, {
        priority: t.priority,
        module: t.module,
      }),
    )
  }

  private updateModuleStats(module: string, action: 'add' | 'complete' | 'fail'): void {
    const stats = this.moduleStats.get(module) || { total: 0, completed: 0, failed: 0 }
    if (action === 'add') stats.total++
    else if (action === 'complete') stats.completed++
    else if (action === 'fail') stats.failed++

    this.moduleStats.set(module, stats)
  }

  private async processQueue(priority: Priority): Promise<void> {
    if (this.destroyed) return
    if (this.processing.get(priority)) return

    this.processing.set(priority, true)

    try {
      while (this.queues.get(priority)!.length > 0 && !this.destroyed) {
        if (this.inProgress.size >= this.options.concurrency) {
          await this.delay(100)
          continue
        }

        const task = this.queues.get(priority)!.shift()
        if (!task) continue

        this.inProgress.add(task.id)

        this.executeTask(task).finally(() => {
          this.inProgress.delete(task.id)
        })
      }
    } finally {
      this.processing.set(priority, false)
      this.checkHigherPriority(priority)
    }
  }

  private async executeTask(task: QueueTask): Promise<void> {
    const startTime = Date.now()

    try {
      const timeoutPromise = new Promise((_, reject) => {
        setTimeout(() => reject(new Error('Task timeout')), this.options.timeout)
      })

      const result = await Promise.race([task.task(), timeoutPromise])

      task.resolve(result)
      this.stats.totalCompleted++
      this.updateModuleStats(task.module!, 'complete')

      console.log(`[Queue] ✅ [${task.module}] 任务完成: ${task.id} (${Date.now() - startTime}ms)`)
    } catch (error) {
      if (error.message === 'Task timeout') {
        this.stats.totalTimeout++
        console.warn(`[Queue] ⏰ [${task.module}] 任务超时: ${task.id}`)
      }

      if (task.retryCount! < task.maxRetries!) {
        task.retryCount!++
        console.log(
          `[Queue] 🔄 [${task.module}] 任务重试: ${task.id} (${task.retryCount}/${task.maxRetries})`,
        )

        setTimeout(() => {
          if (!this.destroyed) {
            this.queues.get(task.priority)!.unshift(task)
            this.processQueue(task.priority)
          }
        }, this.options.retryDelay * task.retryCount!)
      } else {
        task.reject(error)
        this.stats.totalFailed++
        this.updateModuleStats(task.module!, 'fail')
        console.error(`[Queue] ❌ [${task.module}] 任务失败: ${task.id}`, error)
      }
    }
  }

  private checkHigherPriority(currentPriority: Priority): void {
    if (this.destroyed) return

    const priorityOrder: Priority[] = ['high', 'medium', 'low']
    const currentIndex = priorityOrder.indexOf(currentPriority)

    for (let i = 0; i < currentIndex; i++) {
      const higherPriority = priorityOrder[i]
      if (this.queues.get(higherPriority)!.length > 0) {
        this.processQueue(higherPriority)
        break
      }
    }
  }

  /**
   * 获取指定模块的任务详情
   */
  getModuleTasks(module: string) {
    if (this.destroyed) return []

    const tasks: any[] = []

    this.queues.forEach((queue, priority) => {
      queue.forEach((task) => {
        if (task.module === module) {
          tasks.push({
            id: task.id,
            priority,
            waitTime: Date.now() - task.timestamp,
            retryCount: task.retryCount,
          })
        }
      })
    })

    return tasks
  }

  /**
   * 清空队列
   */
  clear(): void {
    if (this.destroyed) return

    this.queues.forEach((queue) => {
      queue.forEach((task) => {
        task.reject(new Error('Queue cleared'))
      })
      queue.length = 0
    })

    this.inProgress.clear()
    this.moduleStats.clear()
    this.stats = {
      totalAdded: 0,
      totalCompleted: 0,
      totalFailed: 0,
      totalTimeout: 0,
    }
    console.log('[Queue] 🧹 队列已清空')
  }

  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }

  /**
   * 销毁方法
   */
  destroy(): void {
    if (this.destroyed) return

    console.log('[CalculationQueue] 💥 开始销毁...')
    this.destroyed = true

    this.clear()

    console.log('[CalculationQueue] ✅ 已销毁')
  }
}

// 导出单例
export const calculationQueue = new CalculationQueue({
  concurrency: 5,
  retryDelay: 1000,
  timeout: 30000,
})