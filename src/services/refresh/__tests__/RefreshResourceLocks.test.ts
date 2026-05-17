import { describe, expect, it } from 'vitest'

import { RefreshResourceLockManager } from '../RefreshResourceLocks'

describe('RefreshResourceLockManager', () => {
  it('skips a runner when the resource is already locked and skipIfLocked is enabled', async () => {
    const locks = new RefreshResourceLockManager()
    let release!: () => void
    const first = locks.runExclusive(
      'quote-http',
      () =>
        new Promise<void>((resolve) => {
          release = resolve
        }),
    )

    const second = await locks.runExclusive('quote-http', () => 'second', { skipIfLocked: true })

    expect(second).toEqual({ executed: false })
    release()
    await first
  })

  it('serializes runners for the same resource key', async () => {
    const locks = new RefreshResourceLockManager()
    const events: string[] = []
    let releaseFirst!: () => void

    const first = locks.runExclusive(
      'quote-http',
      async () => {
        events.push('first:start')
        await new Promise<void>((resolve) => {
          releaseFirst = resolve
        })
        events.push('first:end')
      },
    )
    const second = locks.runExclusive('quote-http', () => {
      events.push('second')
      return 'second'
    })

    await Promise.resolve()
    expect(events).toEqual(['first:start'])

    releaseFirst()
    await first

    expect(await second).toEqual({ executed: true, value: 'second' })
    expect(events).toEqual(['first:start', 'first:end', 'second'])
  })
})
