// src/utils/eventManager.ts
// 优化版：支持事件溯源、性能监控、安全初始化

type EventCallback = (data: any) => void
type EventHistory = {
  event: string
  data: any
  timestamp: number
  source?: string
  duration?: number
}

class EventManagerClass {
  private listeners = new Map<string, Set<EventCallback>>()
  private onceListeners = new Map<string, Set<EventCallback>>()
  private history: EventHistory[] = []
  private maxHistory = 1000
  private enabled = true
  private stats = new Map<string, { count: number; lastTime: number }>()
  private initialized = false

  constructor() {
    // 延迟初始化，避免在导入时就被使用
    if (typeof window !== 'undefined') {
      // 使用微任务确保其他导入完成
      queueMicrotask(() => {
        this.initialized = true
        console.log('[EventManager] ✅ 已初始化')
      })
    }
  }

  /**
   * 检查是否就绪
   */
  private ensureReady(): boolean {
    if (!this.initialized) {
      //console.warn('[EventManager] ⚠️ 尚未完全初始化，事件可能会延迟处理')
    }
    return true
  }

  /**
   * 订阅事件
   */
  on(event: string, callback: EventCallback): () => void {
    this.ensureReady()

    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set())
    }
    this.listeners.get(event)!.add(callback)

    // 返回取消订阅函数
    return () => this.off(event, callback)
  }

  /**
   * 一次性订阅
   */
  once(event: string, callback: EventCallback): () => void {
    this.ensureReady()

    if (!this.onceListeners.has(event)) {
      this.onceListeners.set(event, new Set())
    }
    this.onceListeners.get(event)!.add(callback)

    return () => {
      this.onceListeners.get(event)?.delete(callback)
    }
  }

  /**
   * 取消订阅
   */
  off(event: string, callback: EventCallback): void {
    this.listeners.get(event)?.delete(callback)
    this.onceListeners.get(event)?.delete(callback)
  }

  /**
   * 触发事件
   */
  emit(event: string, data?: any, source?: string): void {
    if (!this.enabled) return

    const startTime = performance.now()

    // 更新统计
    const stat = this.stats.get(event) || { count: 0, lastTime: 0 }
    stat.count++
    stat.lastTime = Date.now()
    this.stats.set(event, stat)

    // 记录历史
    this.history.push({
      event,
      data,
      timestamp: Date.now(),
      source,
    })

    // 限制历史长度
    if (this.history.length > this.maxHistory) {
      this.history.shift()
    }

    // 触发普通监听器
    const listeners = this.listeners.get(event)
    if (listeners) {
      listeners.forEach((callback) => {
        try {
          callback(data)
        } catch (error) {
          console.error(`[EventManager] 事件回调错误 (${event}):`, error)
        }
      })
    }

    // 触发一次性监听器
    const onceListeners = this.onceListeners.get(event)
    if (onceListeners) {
      onceListeners.forEach((callback) => {
        try {
          callback(data)
        } catch (error) {
          console.error(`[EventManager] 一次性事件回调错误 (${event}):`, error)
        }
      })
      this.onceListeners.delete(event)
    }

    const duration = performance.now() - startTime
    if (duration > 20) {
      //console.warn(`[EventManager] 事件处理耗时较长: ${event} ${duration.toFixed(2)}ms`)
    }
  }

  /**
   * 安全触发事件（捕获所有错误）
   */
  emitSafe(event: string, data?: any, source?: string): void {
    try {
      this.emit(event, data, source)
    } catch (error) {
      console.error(`[EventManager] 触发事件失败: ${event}`, error)
    }
  }

  /**
   * 异步触发事件
   */
  async emitAsync(event: string, data?: any, source?: string): Promise<void> {
    return new Promise((resolve) => {
      setTimeout(() => {
        this.emitSafe(event, data, source)
        resolve()
      }, 0)
    })
  }

  /**
   * 批量触发事件
   */
  emitBatch(events: Array<{ event: string; data?: any; source?: string }>): void {
    events.forEach(({ event, data, source }) => {
      this.emitSafe(event, data, source)
    })
  }

  /**
   * 等待事件
   */
  waitFor(event: string, timeout = 5000): Promise<any> {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        unsubscribe()
        reject(new Error(`等待事件超时: ${event}`))
      }, timeout)

      const unsubscribe = this.once(event, (data) => {
        clearTimeout(timer)
        resolve(data)
      })
    })
  }

  /**
   * 获取事件历史
   */
  getHistory(event?: string, limit = 50): EventHistory[] {
    let filtered = this.history
    if (event) {
      filtered = filtered.filter((h) => h.event === event)
    }
    return filtered.slice(-limit)
  }

  /**
   * 获取统计信息
   */
  getStats(): Record<string, { count: number; lastTime: string }> {
    const result: Record<string, any> = {}
    this.stats.forEach((stat, event) => {
      result[event] = {
        count: stat.count,
        lastTime: new Date(stat.lastTime).toLocaleTimeString(),
      }
    })
    return result
  }

  /**
   * 清除历史
   */
  clearHistory(): void {
    this.history = []
  }

  /**
   * 暂停事件处理
   */
  pause(): void {
    this.enabled = false
  }

  /**
   * 恢复事件处理
   */
  resume(): void {
    this.enabled = true
  }

  /**
   * 获取监听器数量
   */
  getListenerCount(): number {
    let count = 0
    this.listeners.forEach((listeners) => (count += listeners.size))
    this.onceListeners.forEach((listeners) => (count += listeners.size))
    return count
  }

  /**
   * 检查是否就绪
   */
  isReady(): boolean {
    return this.initialized
  }
}

// 创建单例
export const EventManager = new EventManagerClass()

// 挂载到 window
if (typeof window !== 'undefined') {
  ;(window as any).EventManager = EventManager
}

// 导出类型
export type { EventCallback, EventHistory }
