import assert from 'node:assert/strict'
import test from 'node:test'

import { ProcessMemoryCache, LayeredProxyCache } from '../helpers/proxyCache.js'
import { createLonghuBigOrderService, longhuCacheSlot } from '../services/longhuBigOrderCache.js'
import { LonghuRequestScheduler } from '../services/longhuBigOrderCache.js'

// 2026-07-17（周五）10:00 上海 = 交易时段
const TRADING_NOW = Date.parse('2026-07-17T02:00:00Z')
// 2026-07-17（周五）20:00 上海 = 收盘后
const CLOSED_NOW = Date.parse('2026-07-17T12:00:00Z')

function row(id, date = '2026-07-17 09:30:00') {
  return ['2', String(1_784_200_000 + id), '100', String(1000 + id), '10', date]
}

// 按 Index/st 切片返回 rowsRef.current 的可分页假上游
function pagedClient(rowsRef, calls = []) {
  return {
    post: async (url, body, config) => {
      const form = new URLSearchParams(body)
      calls.push({ url, form, config })
      const index = Number(form.get('Index'))
      const st = Number(form.get('st'))
      return {
        data: {
          errcode: '0',
          Total: rowsRef.current.length,
          List: rowsRef.current.slice(index, index + st),
        },
      }
    },
  }
}

const silentLogger = { log() {}, warn() {} }

function makeCache(now) {
  return new LayeredProxyCache({
    memoryCache: new ProcessMemoryCache(now ? { now } : {}),
    redisCache: new ProcessMemoryCache(now ? { now } : {}),
  })
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
    logger: silentLogger,
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
    logger: silentLogger,
    readConfig: () => 'off',
  })

  await assert.rejects(service.loadAllDay({ stockCode: '002297', money: 0 }), /truncated/)
  assert.equal(await cache.get('big-order:longhu:latest:v1:002297', { allowStale: true }), null)
})

test('cold rebuild rejects cumulative rows beyond Total and does not cache them', async () => {
  const cache = makeCache()
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async (_url, body) => {
        const index = Number(new URLSearchParams(body).get('Index'))
        return {
          data: {
            errcode: '0',
            Total: 201,
            List:
              index === 0
                ? Array.from({ length: 200 }, (_, rowIndex) => row(rowIndex))
                : [row(200), row(201)],
          },
        }
      },
    },
    layeredCache: cache,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
  })

  await assert.rejects(
    service.loadAllDay({ stockCode: '002297', money: 0 }),
    /exceeds Total/,
  )
  assert.equal(await cache.get('big-order:longhu:latest:v1:002297', { allowStale: true }), null)
})

test('cold rebuild reports skipped all-day cache writes but still returns upstream data', async () => {
  const warnings = []
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async () => ({ data: { errcode: '0', Total: 1, List: [row(1)] } }),
    },
    layeredCache: new LayeredProxyCache({
      memoryCache: new ProcessMemoryCache({ maxValueBytes: 1 }),
      redisCache: new ProcessMemoryCache({ maxValueBytes: 1 }),
    }),
    delayMs: 0,
    logger: { log() {}, warn: (...args) => warnings.push(args.join(' ')) },
    readConfig: () => 'off',
  })

  const result = await service.loadAllDay({ stockCode: '002297', money: 0 })

  assert.equal(result.data.Total, 1)
  assert.equal(result.data.List.length, 1)
  assert.ok(warnings.some((message) => message.includes('全天快照缓存写入被跳过')))
})

test('incremental mode defaults to prepend-logical', async () => {
  const service = createLonghuBigOrderService({
    plainClient: { post: async () => ({ data: { errcode: '0', Total: 0, List: [] } }) },
    layeredCache: new LayeredProxyCache({
      memoryCache: new ProcessMemoryCache(),
      redisCache: new ProcessMemoryCache(),
    }),
    delayMs: 0,
    logger: silentLogger,
  })
  assert.equal(service.incrementalMode, 'prepend-logical')
})

test('prepend-logical implements logical offsets while remaining opt-in', async () => {
  const calls = []
  const targetRows = Array.from({ length: 201 }, (_, index) => row(index))
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async (_url, body) => {
        const form = new URLSearchParams(body)
        const index = Number(form.get('Index'))
        calls.push(index)
        if (index === 0) {
          return { data: { errcode: '0', Total: 201, List: targetRows.slice(0, 200) } }
        }
        if (index === 200) {
          return { data: { errcode: '0', Total: 202, List: [row(199)] } }
        }
        return { data: { errcode: '0', Total: 202, List: [targetRows[200]] } }
      },
    },
    layeredCache: new LayeredProxyCache({
      memoryCache: new ProcessMemoryCache(),
      redisCache: new ProcessMemoryCache(),
    }),
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'prepend-logical',
  })

  const result = await service.loadAllDay({ stockCode: '002297', money: 0 })

  assert.equal(service.incrementalMode, 'prepend-logical')
  assert.equal(result.data.Total, 201)
  assert.equal(result.data.List.length, 201)
  assert.deepEqual(calls, [0, 200, 201])
})

test('prepend-logical rejects rows beyond the target Total', async () => {
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async (_url, body) => {
        const index = Number(new URLSearchParams(body).get('Index'))
        return {
          data: {
            errcode: '0',
            Total: 201,
            List:
              index === 0
                ? Array.from({ length: 200 }, (_, rowIndex) => row(rowIndex))
                : [row(200), row(201)],
          },
        }
      },
    },
    layeredCache: makeCache(),
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'prepend-logical',
  })

  await assert.rejects(
    service.loadAllDay({ stockCode: '002297', money: 0 }),
    /exceeds Total/,
  )
})

test('prepend-logical rejects a decreasing Total and an unstable logical page', async (context) => {
  await context.test('current Total below the target snapshot', async () => {
    const rows = Array.from({ length: 201 }, (_, index) => row(index))
    const service = createLonghuBigOrderService({
      plainClient: {
        post: async (_url, body) => {
          const index = Number(new URLSearchParams(body).get('Index'))
          return {
            data: {
              errcode: '0',
              Total: index === 0 ? 201 : 200,
              List: index === 0 ? rows.slice(0, 200) : [],
            },
          }
        },
      },
      layeredCache: makeCache(),
      delayMs: 0,
      logger: silentLogger,
      readConfig: () => 'prepend-logical',
    })
    await assert.rejects(
      service.loadAllDay({ stockCode: '002297', money: 0 }),
      /decreased/,
    )
  })

  await context.test('logical page changes more than two times', async () => {
    const rows = Array.from({ length: 201 }, (_, index) => row(index))
    let growth = 0
    const service = createLonghuBigOrderService({
      plainClient: {
        post: async (_url, body) => {
          const index = Number(new URLSearchParams(body).get('Index'))
          if (index === 0) growth = 0
          else growth += 1
          return {
            data: {
              errcode: '0',
              Total: 201 + growth,
              List: index === 0 ? rows.slice(0, 200) : [rows[200]],
            },
          }
        },
      },
      layeredCache: makeCache(),
      delayMs: 0,
      logger: silentLogger,
      readConfig: () => 'prepend-logical',
    })
    await assert.rejects(
      service.loadAllDay({ stockCode: '002298', money: 0 }),
      /changed more than 2 times/,
    )
  })
})

test('stable rebuild retries Total drift with a new DeviceID', async () => {
  const calls = []
  let attempt = 0
  const rows = Array.from({ length: 201 }, (_, index) => row(index))
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async (_url, body) => {
        const form = new URLSearchParams(body)
        const index = Number(form.get('Index'))
        const device = form.get('DeviceID')
        if (index === 0) attempt += 1
        calls.push({ attempt, index, device })
        return {
          data: {
            errcode: '0',
            Total: attempt === 1 && index > 0 ? 202 : 201,
            List: rows.slice(index, index + 200),
          },
        }
      },
    },
    layeredCache: makeCache(),
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
  })

  const result = await service.loadAllDay({ stockCode: '002297', money: 0 })

  assert.equal(result.data.List.length, 201)
  assert.equal(new Set(calls.filter((call) => call.attempt === 1).map((call) => call.device)).size, 1)
  assert.equal(new Set(calls.filter((call) => call.attempt === 2).map((call) => call.device)).size, 1)
  assert.notEqual(calls[0].device, calls.at(-1).device)
})

test('three integrity failures cool only the affected stock key for sixty seconds', async () => {
  let now = TRADING_NOW
  const calls = new Map()
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async (_url, body) => {
        const stockCode = new URLSearchParams(body).get('StockID')
        calls.set(stockCode, (calls.get(stockCode) || 0) + 1)
        if (stockCode === '002297') {
          return { data: { errcode: '0', Total: 201, List: [row(1)] } }
        }
        return { data: { errcode: '0', Total: 1, List: [row(2)] } }
      },
    },
    layeredCache: makeCache(() => now),
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
  })

  for (let attempt = 0; attempt < 3; attempt++) {
    await assert.rejects(service.loadAllDay({ stockCode: '002297', money: 0 }), /truncated/)
    if (attempt < 2) now += 300_001
  }
  const failedCalls = calls.get('002297')
  await assert.rejects(
    service.loadAllDay({ stockCode: '002297', money: 0 }),
    /key_cooldown/,
  )
  assert.equal(calls.get('002297'), failedCalls)

  const other = await service.loadAllDay({ stockCode: '600519', money: 0 })
  assert.equal(other.data.Total, 1)
})

test('the shared rebuild deadline is a key failure and does not open the source breaker', async () => {
  let now = TRADING_NOW
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async (_url, body, config) => {
        const stockCode = new URLSearchParams(body).get('StockID')
        if (stockCode === '600519') {
          return { data: { errcode: '0', Total: 1, List: [row(1)] } }
        }
        return new Promise((_resolve, reject) => {
          config.signal.addEventListener('abort', () => {
            const error = new Error('aborted')
            error.name = 'AbortError'
            reject(error)
          })
        })
      },
    },
    layeredCache: makeCache(() => now),
    now: () => now,
    fullRebuildBudgetMs: 5,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
  })

  for (let attempt = 0; attempt < 3; attempt++) {
    await assert.rejects(
      service.loadAllDay({ stockCode: '002297', money: 0 }),
      /budget exceeded/,
    )
    if (attempt < 2) now += 300_001
  }
  await assert.rejects(
    service.loadAllDay({ stockCode: '002297', money: 0 }),
    /key_cooldown/,
  )
  const other = await service.loadAllDay({ stockCode: '600519', money: 0 })
  assert.equal(other.data.Total, 1)
})

test('two consecutive incremental integrity failures force a cooled full rebuild', async () => {
  let now = TRADING_NOW
  const baseline = Array.from({ length: 300 }, (_, index) => row(300 - index))
  const updated = [row(99_999), ...baseline]
  let phase = 'baseline'
  let shortHeads = 0
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async (_url, body) => {
        const index = Number(new URLSearchParams(body).get('Index'))
        if (phase === 'baseline') {
          return { data: { errcode: '0', Total: baseline.length, List: baseline.slice(index, index + 200) } }
        }
        if (index === 0 && shortHeads < 2) {
          shortHeads += 1
          return { data: { errcode: '0', Total: updated.length, List: updated.slice(0, 30) } }
        }
        return { data: { errcode: '0', Total: updated.length, List: updated.slice(index, index + 200) } }
      },
    },
    layeredCache: makeCache(() => now),
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'prepend-device-snapshot',
  })
  await service.loadAllDay({ stockCode: '002297', money: 0 })

  phase = 'refresh'
  now += 61_000
  await service.loadAllDay({ stockCode: '002297', money: 0 })
  await new Promise((resolve) => setTimeout(resolve, 20))
  now += 11_000
  await service.loadAllDay({ stockCode: '002297', money: 0 })

  for (let attempt = 0; attempt < 100; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 10))
    const refreshed = await service.loadAllDay({ stockCode: '002297', money: 0 })
    if (!refreshed.cache.stale && refreshed.data.Total === updated.length) {
      assert.equal(shortHeads, 2)
      return
    }
  }
  assert.fail('two incremental failures did not force a full rebuild')
})

test('a failed incremental full rebuild is not attempted again within sixty seconds', async () => {
  let now = TRADING_NOW
  let phase = 'baseline'
  const refreshCalls = []
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async (_url, body) => {
        if (phase === 'baseline') {
          return { data: { errcode: '0', Total: 1, List: [row(1)] } }
        }
        const index = Number(new URLSearchParams(body).get('Index'))
        refreshCalls.push(index)
        if (refreshCalls.length === 1 || refreshCalls.length === 5) {
          return { data: { errcode: '0', Total: 0, List: [] } }
        }
        return { data: { errcode: '0', Total: 2, List: [row(2)] } }
      },
    },
    layeredCache: makeCache(() => now),
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'prepend-device-snapshot',
  })
  await service.loadAllDay({ stockCode: '002297', money: 0 })

  phase = 'refresh'
  now += 61_000
  await service.loadAllDay({ stockCode: '002297', money: 0 })
  await new Promise((resolve) => setTimeout(resolve, 30))
  assert.equal(refreshCalls.length, 4, 'head plus three stable rebuild attempts')

  now += 11_000
  const stale = await service.loadAllDay({ stockCode: '002297', money: 0 })
  await new Promise((resolve) => setTimeout(resolve, 30))
  assert.equal(stale.data.Total, 1)
  assert.equal(refreshCalls.length, 5, 'second probe is allowed while full rebuild remains cooled down')
})

test('prepend-logical applies logical offsets during a multi-page head refresh', async () => {
  let now = TRADING_NOW
  const baseline = Array.from({ length: 300 }, (_, index) => row(10_000 - index))
  const additions = Array.from({ length: 190 }, (_, index) => row(30_000 - index))
  const target = [...additions, ...baseline]
  const later = [row(40_000), ...target]
  let phase = 'baseline'
  let shifted = false
  const calls = []
  const cache = makeCache(() => now)
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async (_url, body) => {
        const index = Number(new URLSearchParams(body).get('Index'))
        calls.push(index)
        if (phase === 'baseline') {
          return { data: { errcode: '0', Total: baseline.length, List: baseline.slice(index, index + 200) } }
        }
        if (index === 0) {
          shifted = true
          return { data: { errcode: '0', Total: target.length, List: target.slice(0, 200) } }
        }
        const rows = shifted ? later : target
        return { data: { errcode: '0', Total: rows.length, List: rows.slice(index, index + 200) } }
      },
    },
    layeredCache: cache,
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'prepend-logical',
  })
  await service.loadAllDay({ stockCode: '002297', money: 0 })

  phase = 'refresh'
  now += 11_000
  await service.loadAllDay({ stockCode: '002297', money: 0 })
  await new Promise((resolve) => setTimeout(resolve, 30))

  const cached = await cache.get('big-order:longhu:all-day:v2:2026-07-17:002297:0', {
    allowStale: true,
  })
  assert.equal(cached.value.data.Total, target.length)
  assert.equal(cached.value.data.List.length, target.length)
  assert.deepEqual(calls.slice(-3), [0, 200, 201])
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
    logger: silentLogger,
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
    logger: silentLogger,
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
    logger: silentLogger,
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

test('stale snapshot waits for verified head delta and returns fresh data', async () => {
  let now = TRADING_NOW
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
    logger: silentLogger,
    readConfig: () => 'prepend-logical',
  })

  await service.loadAllDay({ stockCode: '002297', money: 0 })
  upstreamRows = [row(3), row(2), row(1)]
  now += 11_000
  const refreshed = await service.loadAllDay({ stockCode: '002297', money: 0 })
  assert.equal(refreshed.cache.stale, false)
  assert.equal(refreshed.data.List.length, 3)
  assert.equal(calls, 2)
  assert.equal(refreshed.refresh.mode, 'cache-hit')
})

test('incremental merge preserves legitimate duplicate transactions', async () => {
  let now = TRADING_NOW
  const duplicate = row(1)
  const rowsRef = { current: [duplicate, duplicate, row(2)] }
  const service = createLonghuBigOrderService({
    plainClient: pagedClient(rowsRef),
    layeredCache: makeCache(() => now),
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'prepend-device-snapshot',
  })

  await service.loadAllDay({ stockCode: '002297', money: 0 })
  rowsRef.current = [duplicate, duplicate, duplicate, row(2)]
  now += 11_000
  await service.loadAllDay({ stockCode: '002297', money: 0 })

  for (let attempt = 0; attempt < 100; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 10))
    const refreshed = await service.loadAllDay({ stockCode: '002297', money: 0 })
    if (!refreshed.cache.stale && refreshed.data.Total === 4) {
      const fingerprint = JSON.stringify(duplicate)
      assert.equal(
        refreshed.data.List.filter((item) => JSON.stringify(item) === fingerprint).length,
        3,
      )
      return
    }
  }
  assert.fail('duplicate-preserving incremental refresh did not complete')
})

test('off mode keeps stale snapshot without full rebuild inside 300 second cooldown', async () => {
  let now = TRADING_NOW
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
    logger: silentLogger,
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
  let now = TRADING_NOW
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
    logger: silentLogger,
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

test('cache slot maps trading, lunch and closed windows to design TTLs', () => {
  const trading = longhuCacheSlot(TRADING_NOW)
  assert.equal(trading.ttlSeconds, 3)
  assert.equal(trading.staleTtlSeconds, 300)
  assert.equal(trading.rebuildCooldownMs, 300_000)

  // 周五 12:00 上海 = 午间休市
  const lunch = longhuCacheSlot(Date.parse('2026-07-17T04:00:00Z'))
  assert.equal(lunch.ttlSeconds, 60)
  assert.equal(lunch.staleTtlSeconds, 900)

  // 周五 09:15 上海 = 盘前
  const preOpen = longhuCacheSlot(Date.parse('2026-07-17T01:15:00Z'))
  assert.equal(preOpen.ttlSeconds, 60)
  assert.equal(preOpen.staleTtlSeconds, 900)

  const closed = longhuCacheSlot(CLOSED_NOW)
  assert.equal(closed.ttlSeconds, 1800)
  assert.equal(closed.staleTtlSeconds, 604800)
  assert.equal(closed.rebuildCooldownMs, 21_600_000)

  // 周六任何时间都按收盘处理
  const weekend = longhuCacheSlot(Date.parse('2026-07-18T02:00:00Z'))
  assert.equal(weekend.ttlSeconds, 1800)
  assert.equal(weekend.staleTtlSeconds, 604800)
})

test('after close the snapshot stays fresh long and stale hits do not rebuild', async () => {
  let now = CLOSED_NOW
  const rowsRef = { current: [row(1)] }
  const calls = []
  const service = createLonghuBigOrderService({
    plainClient: pagedClient(rowsRef, calls),
    layeredCache: makeCache(() => now),
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
  })
  await service.loadAllDay({ stockCode: '002297', money: 0 })
  assert.equal(calls.length, 1)

  now += 400_000 // 收盘后 TTL 1800s：400 秒后仍是 fresh
  const fresh = await service.loadAllDay({ stockCode: '002297', money: 0 })
  assert.equal(fresh.cache.stale, false)
  assert.equal(calls.length, 1)

  now += 1_700_000 // 共 2100s：进入 stale，但收盘冷却 6h 内不得触发完整重建
  const stale = await service.loadAllDay({ stockCode: '002297', money: 0 })
  await new Promise((resolve) => setTimeout(resolve, 20))
  assert.equal(stale.cache.stale, true)
  assert.equal(calls.length, 1)
})

test('the first post-close request reconciles a trading-time snapshot once', async () => {
  let now = Date.parse('2026-07-17T06:59:00Z') // 周五 14:59 上海
  const rowsRef = { current: [row(1, '2026-07-17 14:59:00')] }
  const calls = []
  const service = createLonghuBigOrderService({
    plainClient: pagedClient(rowsRef, calls),
    layeredCache: makeCache(() => now),
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
  })
  await service.loadAllDay({ stockCode: '002297', money: 0 })
  rowsRef.current = [row(2, '2026-07-17 15:00:00'), row(1, '2026-07-17 14:59:00')]

  now = Date.parse('2026-07-17T07:01:00Z') // 周五 15:01 上海
  const stale = await service.loadAllDay({ stockCode: '002297', money: 0 })
  assert.equal(stale.data.Total, 1, 'post-close reconcile remains stale-while-revalidate')
  for (let attempt = 0; attempt < 100; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 10))
    const reconciled = await service.loadAllDay({ stockCode: '002297', money: 0 })
    if (reconciled.data.Total === 2 && !reconciled.cache.stale) {
      assert.equal(calls.length, 2, 'only one post-close full reconcile')
      return
    }
  }
  assert.fail('first post-close request did not reconcile the final snapshot')
})

test('a trading-time snapshot remains available from stale storage over the weekend', async () => {
  let now = Date.parse('2026-07-17T06:00:00Z') // 周五 14:00 上海
  const rowsRef = { current: [row(1, '2026-07-17 14:00:00')] }
  const calls = []
  const service = createLonghuBigOrderService({
    plainClient: pagedClient(rowsRef, calls),
    layeredCache: makeCache(() => now),
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
  })
  await service.loadAllDay({ stockCode: '002297', money: 0 })

  now = Date.parse('2026-07-18T02:00:00Z') // 周六 10:00 上海
  const weekend = await service.loadAllDay({ stockCode: '002297', money: 0 })

  assert.equal(weekend.cache.hit, true)
  assert.equal(weekend.cache.stale, true)
  assert.equal(calls.length, 1)
})

test('an old-session weekday snapshot probes an empty holiday head at most once per minute', async () => {
  let now = Date.parse('2026-07-17T06:00:00Z')
  let holiday = false
  const calls = []
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async (_url, body) => {
        calls.push(new URLSearchParams(body))
        if (holiday) return { data: { errcode: '0', Total: 0, List: [] } }
        return { data: { errcode: '0', Total: 1, List: [row(1, '2026-07-17 14:00:00')] } }
      },
    },
    layeredCache: makeCache(() => now),
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'prepend-device-snapshot',
  })
  await service.loadAllDay({ stockCode: '002297', money: 0 })

  holiday = true
  now = Date.parse('2026-07-20T02:00:00Z') // 周一 10:00，模拟法定休市
  const first = await service.loadAllDay({ stockCode: '002297', money: 0 })
  await new Promise((resolve) => setTimeout(resolve, 10))
  now += 30_000
  const second = await service.loadAllDay({ stockCode: '002297', money: 0 })
  await new Promise((resolve) => setTimeout(resolve, 10))

  assert.equal(first.cache.stale, true)
  assert.equal(second.cache.stale, true)
  assert.equal(calls.length, 2) // 冷启动 1 + 头探测 1

  now += 31_000
  await service.loadAllDay({ stockCode: '002297', money: 0 })
  await new Promise((resolve) => setTimeout(resolve, 10))
  assert.equal(calls.length, 3)
})

test('incremental refresh rejects a short head page even when overlap rows are present', async () => {
  let now = TRADING_NOW
  const baseline = Array.from({ length: 300 }, (_, index) => row(300 - index))
  const updated = [row(99_999), ...baseline]
  let phase = 'baseline'
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async (_url, body) => {
        const index = Number(new URLSearchParams(body).get('Index'))
        if (phase === 'baseline') {
          return {
            data: { errcode: '0', Total: baseline.length, List: baseline.slice(index, index + 200) },
          }
        }
        return {
          data: {
            errcode: '0',
            Total: updated.length,
            List: index === 0 ? updated.slice(0, 30) : [],
          },
        }
      },
    },
    layeredCache: makeCache(() => now),
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'prepend-device-snapshot',
  })
  await service.loadAllDay({ stockCode: '002297', money: 0 })

  phase = 'short-head'
  now += 11_000
  const stale = await service.loadAllDay({ stockCode: '002297', money: 0 })
  await new Promise((resolve) => setTimeout(resolve, 30))
  const stillStale = await service.loadAllDay({ stockCode: '002297', money: 0 })

  assert.equal(stale.data.Total, 300)
  assert.equal(stillStale.data.Total, 300)
  assert.equal(stillStale.cache.stale, true)
})

test('a single bad row is skipped for session date while all-bad rows reject', async () => {
  const badRow = ['2', '1784200000', '100', '1000', '10', '']
  const good = createLonghuBigOrderService({
    plainClient: {
      post: async () => ({
        data: { errcode: '0', Total: 3, List: [row(1), badRow, row(2)] },
      }),
    },
    layeredCache: makeCache(),
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
  })
  const result = await good.loadAllDay({ stockCode: '002297', money: 0 })
  assert.equal(result.sessionDate, '2026-07-17')
  assert.equal(result.data.List.length, 3)

  const allBad = createLonghuBigOrderService({
    plainClient: {
      post: async () => ({ data: { errcode: '0', Total: 1, List: [badRow] } }),
    },
    layeredCache: makeCache(),
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
  })
  await assert.rejects(
    allBad.loadAllDay({ stockCode: '002298', money: 0 }),
    /session date/,
  )
})

test('loadPage aggregates against Total and rejects silent truncation', async () => {
  // 完整聚合：Total=250，两页取齐
  const rowsRef = { current: Array.from({ length: 250 }, (_, i) => row(i)) }
  const calls = []
  const service = createLonghuBigOrderService({
    plainClient: pagedClient(rowsRef, calls),
    layeredCache: makeCache(),
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
  })
  const full = await service.loadPage({ stockCode: '002297', money: 30, index: 0, limit: 40_000 })
  assert.equal(full.List.length, 250)
  assert.equal(full.Total, 250)
  assert.equal(calls.length, 2)

  // 短页截断：Total=250 但上游只肯给 30 行
  const truncated = createLonghuBigOrderService({
    plainClient: {
      post: async () => ({
        data: { errcode: '0', Total: 250, List: Array.from({ length: 30 }, (_, i) => row(i)) },
      }),
    },
    layeredCache: makeCache(),
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
  })
  await assert.rejects(
    truncated.loadPage({ stockCode: '002298', money: 30, index: 0, limit: 40_000 }),
    /truncated/,
  )

  // 分页中 Total 变化
  let page = 0
  const shifting = createLonghuBigOrderService({
    plainClient: {
      post: async () => {
        page += 1
        return {
          data: {
            errcode: '0',
            Total: page === 1 ? 400 : 500,
            List: Array.from({ length: 200 }, (_, i) => row(i)),
          },
        }
      },
    },
    layeredCache: makeCache(),
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
  })
  await assert.rejects(
    shifting.loadPage({ stockCode: '002299', money: 0, index: 0, limit: 40_000 }),
    /Total changed/,
  )
})

test('loadPage caches identical requests briefly', async () => {
  const rowsRef = { current: Array.from({ length: 10 }, (_, i) => row(i)) }
  const calls = []
  const service = createLonghuBigOrderService({
    plainClient: pagedClient(rowsRef, calls),
    layeredCache: makeCache(),
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
  })
  const first = await service.loadPage({ stockCode: '002297', money: 0, index: 0, limit: 100 })
  const second = await service.loadPage({ stockCode: '002297', money: 0, index: 0, limit: 100 })
  assert.equal(first.List.length, 10)
  assert.deepEqual(second.List, first.List)
  assert.equal(calls.length, 1)
})

test('legacy page integrity failures participate in the same per-key cooldown', async () => {
  let calls = 0
  const service = createLonghuBigOrderService({
    plainClient: {
      post: async (_url, body) => {
        calls += 1
        const stockCode = new URLSearchParams(body).get('StockID')
        if (stockCode === '600519') {
          return { data: { errcode: '0', Total: 1, List: [row(1)] } }
        }
        return { data: { errcode: '0', Total: 250, List: Array.from({ length: 30 }, (_, i) => row(i)) } }
      },
    },
    layeredCache: makeCache(),
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
  })

  for (let attempt = 0; attempt < 3; attempt++) {
    await assert.rejects(
      service.loadPage({ stockCode: '002297', money: 30, index: 0, limit: 500 }),
      /truncated/,
    )
  }
  const failedCalls = calls
  await assert.rejects(
    service.loadPage({ stockCode: '002297', money: 30, index: 0, limit: 500 }),
    /key_cooldown/,
  )
  assert.equal(calls, failedCalls)
  const other = await service.loadPage({ stockCode: '600519', money: 30, index: 0, limit: 500 })
  assert.equal(other.Total, 1)
})

test('oversized head delta falls back to one full rebuild instead of head merge', async () => {
  let now = TRADING_NOW
  const rowsRef = { current: [row(0)] }
  const calls = []
  const service = createLonghuBigOrderService({
    plainClient: pagedClient(rowsRef, calls),
    layeredCache: makeCache(() => now),
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'prepend-device-snapshot',
  })
  await service.loadAllDay({ stockCode: '002297', money: 0 })
  assert.equal(calls.length, 1)

  // 新增 2001 行（prepend），delta+overlap 超过 10 页阈值
  rowsRef.current = [
    ...Array.from({ length: 2001 }, (_, i) => row(10_000 + i)),
    row(0),
  ]
  now += 61_000
  await service.loadAllDay({ stockCode: '002297', money: 0 })

  for (let attempt = 0; attempt < 100; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 10))
    const refreshed = await service.loadAllDay({ stockCode: '002297', money: 0 })
    if (!refreshed.cache.stale && refreshed.data.List.length === 2002) {
      // 冷启动 1 页 + 头页 1 次 + 完整重建 11 页
      assert.equal(calls.length, 13)
      return
    }
  }
  assert.fail('large-delta full rebuild did not complete')
})

test('rotating history audit detects drift and forces a full rebuild', async () => {
  let now = TRADING_NOW
  const oldRows = Array.from({ length: 400 }, (_, i) => row(400 - i))
  const rowsRef = { current: oldRows }
  const calls = []
  const service = createLonghuBigOrderService({
    plainClient: pagedClient(rowsRef, calls),
    layeredCache: makeCache(() => now),
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'prepend-device-snapshot',
  })
  await service.loadAllDay({ stockCode: '002297', money: 0 })
  assert.equal(calls.length, 2)

  // 历史区（第 2 页）出现深层修订，头部保持不变
  const drifted = oldRows.slice()
  drifted[250] = row(99_999)
  rowsRef.current = drifted
  now += 301_000
  await service.loadAllDay({ stockCode: '002297', money: 0 })

  for (let attempt = 0; attempt < 100; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 10))
    const refreshed = await service.loadAllDay({ stockCode: '002297', money: 0 })
    const merged = refreshed.data.List
    if (!refreshed.cache.stale && JSON.stringify(merged[250]) === JSON.stringify(row(99_999))) {
      // 冷启动 2 页 + 头页 1 + 审计页 1 + 完整重建 2 页
      assert.equal(calls.length, 6)
      return
    }
  }
  assert.fail('history audit did not trigger a rebuild')
})

test('history audit is queued separately at the lowest scheduler priority', async () => {
  let now = TRADING_NOW
  const rowsRef = { current: Array.from({ length: 400 }, (_, index) => row(400 - index)) }
  const jobs = []
  const scheduler = {
    run: async (key, type, priority, loader) => {
      jobs.push({ key, type, priority })
      return loader()
    },
  }
  const service = createLonghuBigOrderService({
    plainClient: pagedClient(rowsRef),
    layeredCache: makeCache(() => now),
    scheduler,
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'prepend-device-snapshot',
  })

  await service.loadAllDay({ stockCode: '002297', money: 0 })
  assert.deepEqual(jobs.map((job) => job.type), ['cold'])

  now += 301_000
  await service.loadAllDay({ stockCode: '002297', money: 0 })
  await new Promise((resolve) => setTimeout(resolve, 10))

  assert.deepEqual(jobs.map((job) => [job.type, job.priority]), [
    ['cold', 3],
    ['head', 2],
    ['audit', 1],
  ])
})
