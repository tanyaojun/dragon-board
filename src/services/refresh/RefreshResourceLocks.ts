import type { RefreshResourceKey } from './types'

interface RefreshResourceLockOptions {
  skipIfLocked?: boolean
  /**
   * 等待锁的最长时间（毫秒）。超时不会抢占锁：锁仍由持有者持有，
   * 本调用返回 executed:false + reason:'timeout'，由调用方降级保留现有数据并等待下次重试。
   * 不设置则无限等待（保持原语义，供必须串行化的写入场景使用）。
   */
  waitTimeoutMs?: number
}

interface RefreshResourceLockResult<T> {
  executed: boolean
  value?: T
  reason?: 'skipped' | 'timeout'
}

export class RefreshResourceLockManager {
  private readonly locks = new Map<RefreshResourceKey, Promise<unknown>>()

  isLocked(key: RefreshResourceKey): boolean {
    return this.locks.has(key)
  }

  async runExclusive<T>(
    key: RefreshResourceKey,
    runner: () => Promise<T> | T,
    options: RefreshResourceLockOptions = {},
  ): Promise<RefreshResourceLockResult<T>> {
    const waitStart = Date.now()
    while (this.locks.has(key)) {
      const existing = this.locks.get(key)
      if (options.skipIfLocked) return { executed: false, reason: 'skipped' }
      if (options.waitTimeoutMs !== undefined) {
        const remaining = options.waitTimeoutMs - (Date.now() - waitStart)
        if (remaining <= 0) return { executed: false, reason: 'timeout' }
        let timer: ReturnType<typeof setTimeout> | null = null
        const timedOut = new Promise<never>((_, reject) => {
          timer = setTimeout(() => {
            reject(new Error('lock-wait-timeout'))
          }, remaining)
        })
        try {
          // 锁 promise 与超时定时器竞速：持有者释放即继续，超时则放弃等待（不抢占锁）
          await Promise.race([existing?.catch(() => undefined), timedOut])
        } catch {
          return { executed: false, reason: 'timeout' }
        } finally {
          if (timer) clearTimeout(timer)
        }
      } else {
        await existing?.catch(() => undefined)
      }
    }

    let release!: () => void
    const lock = new Promise<void>((resolve) => {
      release = resolve
    })
    this.locks.set(key, lock)

    try {
      return {
        executed: true,
        value: await runner(),
      }
    } finally {
      if (this.locks.get(key) === lock) {
        this.locks.delete(key)
      }
      release()
    }
  }

}

export const refreshResourceLocks = new RefreshResourceLockManager()
