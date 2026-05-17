import type { RefreshResourceKey } from './types'

interface RefreshResourceLockOptions {
  skipIfLocked?: boolean
}

interface RefreshResourceLockResult<T> {
  executed: boolean
  value?: T
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
    while (this.locks.has(key)) {
      const existing = this.locks.get(key)
      if (options.skipIfLocked) return { executed: false }
      await existing?.catch(() => undefined)
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
