import assert from 'node:assert/strict'
import test from 'node:test'

import { LayeredProxyCache, ProcessMemoryCache } from '../helpers/proxyCache.js'

test('layered cache prefers fresh L2 over stale L1 and backfills L1', async () => {
  let now = 1_750_000_000_000
  const l1 = new ProcessMemoryCache({ now: () => now })
  const l2 = new ProcessMemoryCache({ now: () => now })
  await l1.set('key', { source: 'old' }, { ttlSeconds: 1, staleTtlSeconds: 30 })
  now += 2_000
  await l2.set('key', { source: 'redis' }, { ttlSeconds: 30, staleTtlSeconds: 60 })

  const cache = new LayeredProxyCache({ memoryCache: l1, redisCache: l2 })
  const result = await cache.get('key', { allowStale: true })

  assert.equal(result.value.source, 'redis')
  assert.equal(result.store, 'redis')
  assert.equal((await l1.get('key')).value.source, 'redis')
})

test('layered cache coalesces loaders and writes both layers', async () => {
  const l1 = new ProcessMemoryCache()
  const l2 = new ProcessMemoryCache()
  const cache = new LayeredProxyCache({ memoryCache: l1, redisCache: l2 })
  let calls = 0
  let release
  const gate = new Promise((resolve) => {
    release = resolve
  })
  const loader = async () => {
    calls += 1
    await gate
    return { value: 1 }
  }

  const first = cache.remember('same', { ttlSeconds: 30 }, loader)
  const second = cache.remember('same', { ttlSeconds: 30 }, loader)
  release()
  await Promise.all([first, second])

  assert.equal(calls, 1)
  assert.equal((await l1.get('same')).value.value, 1)
  assert.equal((await l2.get('same')).value.value, 1)
})

test('process memory cache enforces byte limits without breaking reads', async () => {
  const cache = new ProcessMemoryCache({
    maxEntries: 10,
    maxBytes: 20,
    maxValueBytes: 10,
  })
  assert.equal(await cache.set('too-large', '12345678901', { ttlSeconds: 30 }), false)
  assert.equal(await cache.get('too-large'), null)
  assert.equal(await cache.set('small', '12345', { ttlSeconds: 30 }), true)
  assert.equal((await cache.get('small')).value, '12345')
})
