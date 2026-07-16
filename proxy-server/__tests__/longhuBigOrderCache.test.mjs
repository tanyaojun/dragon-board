import assert from 'node:assert/strict'
import test from 'node:test'

import { ProcessMemoryCache, LayeredProxyCache } from '../helpers/proxyCache.js'
import { createLonghuBigOrderService } from '../services/longhuBigOrderCache.js'
import { LonghuRequestScheduler } from '../services/longhuBigOrderCache.js'

function row(id, date = '2026-07-17 09:30:00') {
  return ['2', String(1_784_200_000 + id), '100', String(1000 + id), '10', date]
}

test('cold rebuild posts form pages of 200 and reuses DeviceID', async () => {
  const calls = []
  const plainClient = {
    post: async (url, body, config) => {
      const form = new URLSearchParams(body)
      calls.push({ url, form, config })
      const index = Number(form.get('Index'))
      return {
        data: {
          errcode: '0',
          Total: 201,
          List: index === 0 ? Array.from({ length: 200 }, (_, i) => row(i)) : [row(200)],
        },
      }
    },
  }
  const layeredCache = new LayeredProxyCache({
    memoryCache: new ProcessMemoryCache(),
    redisCache: new ProcessMemoryCache(),
  })
  const service = createLonghuBigOrderService({
    plainClient,
    layeredCache,
    delayMs: 0,
    readConfig: () => 'off',
  })

  const result = await service.loadAllDay({ stockCode: '002297', money: 0 })

  assert.equal(result.data.List.length, 201)
  assert.deepEqual(calls.map((call) => call.form.get('Index')), ['0', '200'])
  assert.ok(calls.every((call) => call.form.get('st') === '200'))
  assert.equal(new Set(calls.map((call) => call.form.get('DeviceID'))).size, 1)
  assert.ok(calls.every((call) => call.config.headers['Content-Type'] === 'application/x-www-form-urlencoded'))
})

test('cold rebuild rejects short incomplete pages and does not cache them', async () => {
  const cache = new LayeredProxyCache({
    memoryCache: new ProcessMemoryCache(),
    redisCache: new ProcessMemoryCache(),
  })
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async () => ({ data: { errcode: '0', Total: 201, List: [row(1)] } }),
    },
    layeredCache: cache,
    delayMs: 0,
    readConfig: () => 'off',
  })

  await assert.rejects(service.loadAllDay({ stockCode: '002297', money: 0 }), /truncated/)
  assert.equal(await cache.get('big-order:longhu:latest:v1:002297', { allowStale: true }), null)
})

test('incremental mode defaults to off', async () => {
  const service = createLonghuBigOrderService({
    plainClient: { post: async () => ({ data: { errcode: '0', Total: 0, List: [] } }) },
    layeredCache: new LayeredProxyCache({
      memoryCache: new ProcessMemoryCache(),
      redisCache: new ProcessMemoryCache(),
    }),
    delayMs: 0,
  })
  assert.equal(service.incrementalMode, 'off')
})

test('prepend-logical remains fail-closed until its contract is implemented', async () => {
  const service = createLonghuBigOrderService({
    plainClient: { post: async () => ({ data: { errcode: '0', Total: 0, List: [] } }) },
    layeredCache: new LayeredProxyCache({
      memoryCache: new ProcessMemoryCache(),
      redisCache: new ProcessMemoryCache(),
    }),
    readConfig: () => 'prepend-logical',
  })
  assert.equal(service.incrementalMode, 'off')
})

test('empty canonical result is cached briefly without replacing latest', async () => {
  let calls = 0
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async () => {
        calls += 1
        return { data: { errcode: '0', Total: 0, List: [] } }
      },
    },
    layeredCache: new LayeredProxyCache({
      memoryCache: new ProcessMemoryCache(),
      redisCache: new ProcessMemoryCache(),
    }),
    delayMs: 0,
  })
  await service.loadAllDay({ stockCode: '002297', money: 0 })
  const cached = await service.loadAllDay({ stockCode: '002297', money: 0 })
  assert.equal(cached.cache.hit, true)
  assert.equal(calls, 1)
})

test('mixed session dates are rejected before cache write', async () => {
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async () => ({
        data: {
          errcode: '0',
          Total: 2,
          List: [row(1, '2026-07-17 09:30:00'), row(2, '2026-07-16 14:00:00')],
        },
      }),
    },
    layeredCache: new LayeredProxyCache({
      memoryCache: new ProcessMemoryCache(),
      redisCache: new ProcessMemoryCache(),
    }),
    delayMs: 0,
  })
  await assert.rejects(
    service.loadAllDay({ stockCode: '002297', money: 0 }),
    /mixed session dates/,
  )
})

test('three network failures open the source breaker for sixty seconds', async () => {
  let calls = 0
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async () => {
        calls += 1
        throw new Error('network down')
      },
    },
    layeredCache: new LayeredProxyCache({
      memoryCache: new ProcessMemoryCache(),
      redisCache: new ProcessMemoryCache(),
    }),
    delayMs: 0,
  })
  for (let attempt = 0; attempt < 3; attempt++) {
    await assert.rejects(service.loadAllDay({ stockCode: `00229${attempt}`, money: 0 }))
  }
  await assert.rejects(
    service.loadAllDay({ stockCode: '002299', money: 0 }),
    /circuit_open/,
  )
  assert.equal(calls, 3)
})

test('stale snapshot returns immediately and refreshes by verified head delta', async () => {
  let now = 1_750_000_000_000
  let upstreamRows = [row(2), row(1)]
  let calls = 0
  const cache = new LayeredProxyCache({
    memoryCache: new ProcessMemoryCache({ now: () => now }),
    redisCache: new ProcessMemoryCache({ now: () => now }),
  })
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async () => {
        calls += 1
        return { data: { errcode: '0', Total: upstreamRows.length, List: upstreamRows } }
      },
    },
    layeredCache: cache,
    now: () => now,
    delayMs: 0,
    readConfig: () => 'prepend-device-snapshot',
  })

  await service.loadAllDay({ stockCode: '002297', money: 0 })
  upstreamRows = [row(3), row(2), row(1)]
  now += 11_000
  const stale = await service.loadAllDay({ stockCode: '002297', money: 0 })
  assert.equal(stale.cache.stale, true)
  assert.equal(stale.data.List.length, 2)

  for (let attempt = 0; attempt < 20; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 5))
    const refreshed = await service.loadAllDay({ stockCode: '002297', money: 0 })
    if (!refreshed.cache.stale && refreshed.data.List.length === 3) {
      assert.equal(calls, 2)
      assert.equal(refreshed.refresh.mode, 'cache-hit')
      return
    }
  }
  assert.fail('incremental background refresh did not complete')
})

test('off mode keeps stale snapshot without full rebuild inside 300 second cooldown', async () => {
  let now = 1_750_000_000_000
  let calls = 0
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async () => {
        calls += 1
        return { data: { errcode: '0', Total: 1, List: [row(1)] } }
      },
    },
    layeredCache: new LayeredProxyCache({
      memoryCache: new ProcessMemoryCache({ now: () => now }),
      redisCache: new ProcessMemoryCache({ now: () => now }),
    }),
    now: () => now,
    delayMs: 0,
    readConfig: () => 'off',
  })
  await service.loadAllDay({ stockCode: '002297', money: 0 })
  now += 11_000
  const stale = await service.loadAllDay({ stockCode: '002297', money: 0 })
  await new Promise((resolve) => setTimeout(resolve, 20))
  assert.equal(stale.cache.stale, true)
  assert.equal(calls, 1)
})

test('overlap mismatch keeps stale data while full rebuild is cooling down', async () => {
  let now = 1_750_000_000_000
  let rows = [row(2), row(1)]
  let calls = 0
  const cache = new LayeredProxyCache({
    memoryCache: new ProcessMemoryCache({ now: () => now }),
    redisCache: new ProcessMemoryCache({ now: () => now }),
  })
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async () => {
        calls += 1
        return { data: { errcode: '0', Total: rows.length, List: rows } }
      },
    },
    layeredCache: cache,
    now: () => now,
    delayMs: 0,
    readConfig: () => 'prepend-device-snapshot',
  })
  await service.loadAllDay({ stockCode: '002297', money: 0 })
  rows = [row(3), row(99), row(1)]
  now += 11_000
  await service.loadAllDay({ stockCode: '002297', money: 0 })
  await new Promise((resolve) => setTimeout(resolve, 20))
  const stale = await cache.get(
    'big-order:longhu:all-day:v2:2026-07-17:002297:0',
    { allowStale: true },
  )
  assert.equal(stale.stale, true)
  assert.equal(stale.value.data.List.length, 2)
  assert.equal(calls, 2)
})

test('scheduler serializes jobs and rejects cold misses when its queue is full', async () => {
  const scheduler = new LonghuRequestScheduler({ maxQueued: 1, waitTimeoutMs: 1000 })
  let release
  const gate = new Promise((resolve) => {
    release = resolve
  })
  let running = 0
  let peak = 0
  const first = scheduler.run('first', 'cold', 3, async () => {
    running += 1
    peak = Math.max(peak, running)
    await gate
    running -= 1
  })
  const second = scheduler.run('second', 'head', 2, async () => {
    running += 1
    peak = Math.max(peak, running)
    running -= 1
  })
  await assert.rejects(
    scheduler.run('third', 'cold', 3, async () => {}),
    /big_order_refresh_busy/,
  )
  release()
  await Promise.all([first, second])
  assert.equal(peak, 1)
})
