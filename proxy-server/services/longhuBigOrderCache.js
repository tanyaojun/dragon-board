import crypto from 'node:crypto'

const LONGHU_URL = 'https://apphwhq.longhuvip.com/w1/api/index.php'
const PAGE_SIZE = 200
const VALID_MODES = new Set(['off', 'prepend-device-snapshot', 'prepend-logical'])

export class LonghuRequestScheduler {
  constructor({ maxQueued = 4, waitTimeoutMs = 8000 } = {}) {
    this.maxQueued = maxQueued
    this.waitTimeoutMs = waitTimeoutMs
    this.running = false
    this.queue = []
    this.pending = new Map()
  }

  run(key, type, priority, loader) {
    const pendingKey = `${type}:${key}`
    if (this.pending.has(pendingKey)) return this.pending.get(pendingKey)
    if (this.running && this.queue.length >= this.maxQueued) {
      return Promise.reject(new Error('big_order_refresh_busy'))
    }
    let resolvePromise
    let rejectPromise
    const promise = new Promise((resolve, reject) => {
      resolvePromise = resolve
      rejectPromise = reject
    })
    const job = {
      pendingKey,
      priority,
      loader,
      resolve: resolvePromise,
      reject: rejectPromise,
      timer: null,
    }
    this.pending.set(pendingKey, promise)
    if (!this.running) this.start(job)
    else {
      job.timer = setTimeout(() => {
        const index = this.queue.indexOf(job)
        if (index >= 0) this.queue.splice(index, 1)
        this.pending.delete(pendingKey)
        rejectPromise(new Error('big_order_refresh_busy'))
      }, this.waitTimeoutMs)
      this.queue.push(job)
      this.queue.sort((left, right) => right.priority - left.priority)
    }
    return promise
  }

  start(job) {
    this.running = true
    if (job.timer) clearTimeout(job.timer)
    Promise.resolve()
      .then(job.loader)
      .then(job.resolve, job.reject)
      .finally(() => {
        this.pending.delete(job.pendingKey)
        const next = this.queue.shift()
        if (next) this.start(next)
        else this.running = false
      })
  }
}

function deviceId() {
  return crypto.randomBytes(16).toString('hex')
}

function formBody({ stockCode, money, index, device }) {
  return new URLSearchParams({
    Order: '0',
    st: String(PAGE_SIZE),
    a: 'GetMainMonitor_w30',
    c: 'StockYiDongKanPan',
    PhoneOSNew: '1',
    DeviceID: device,
    VerSion: '5.17.0.4',
    Index: String(index),
    Money: String(money),
    apiv: 'w36',
    StockID: stockCode,
    IsBS: '0',
  }).toString()
}

function sessionDateFromRows(rows) {
  let sessionDate = null
  for (const row of rows || []) {
    const value = Array.isArray(row) ? row[5] : null
    const match = String(value || '').match(/^(\d{4}-\d{2}-\d{2})\s/)
    if (!match) throw new Error('Longhu row missing session date')
    if (sessionDate && sessionDate !== match[1]) {
      throw new Error('Longhu snapshot contains mixed session dates')
    }
    sessionDate = match[1]
  }
  return sessionDate
}

function shanghaiDate(timestamp) {
  return new Date(timestamp).toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' })
}

function validatePage(payload) {
  if (!payload || String(payload.errcode) !== '0' || !Array.isArray(payload.List)) {
    throw new Error(payload?.msg || 'invalid Longhu payload')
  }
  const total = Number(payload.Total)
  if (!Number.isInteger(total) || total < 0) throw new Error('invalid Longhu Total')
  return { list: payload.List, total }
}

export function createLonghuBigOrderService({
  plainClient,
  layeredCache,
  now = () => Date.now(),
  delayMs = 150,
  readConfig = (name, fallback) => process.env[name] || fallback,
  scheduler = new LonghuRequestScheduler(),
} = {}) {
  const configuredMode = readConfig('BIG_ORDER_LONGHU_INCREMENTAL_MODE', 'off')
  const incrementalMode =
    VALID_MODES.has(configuredMode) && configuredMode !== 'prepend-logical'
      ? configuredMode
      : 'off'
  const pendingRefreshes = new Map()
  const lastFullRebuildAt = new Map()
  let sourceFailureCount = 0
  let sourceBreakerUntil = 0

  async function requestPage({ stockCode, money, index, device, signal }) {
    if (sourceBreakerUntil > now()) throw new Error('big_order_source_circuit_open')
    let response
    try {
      response = await plainClient.post(
        LONGHU_URL,
        formBody({ stockCode, money, index, device }),
        {
          timeout: 15000,
          signal,
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 9; MI 8 MIUI/V11.0.5.0.PEACNXM)',
          },
        },
      )
      sourceFailureCount = 0
    } catch (error) {
      const status = Number(error?.response?.status)
      const deadlineAbort = error?.name === 'AbortError' || error?.code === 'ERR_CANCELED'
      if (!deadlineAbort && (!status || status === 403 || status === 429 || status >= 500)) {
        sourceFailureCount += 1
        if (sourceFailureCount >= 3) {
          sourceBreakerUntil = now() + 60_000
          sourceFailureCount = 0
        }
      }
      throw error
    }
    return validatePage(response.data)
  }

  async function rebuild({ stockCode, money }) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 45_000)
    const device = deviceId()
    const list = []
    let expectedTotal = null
    try {
      for (let index = 0; ; index = list.length) {
        const page = await requestPage({
          stockCode,
          money,
          index,
          device,
          signal: controller.signal,
        })
        if (expectedTotal === null) expectedTotal = page.total
        else if (page.total !== expectedTotal) throw new Error('Longhu Total changed during pagination')
        list.push(...page.list)
        if (list.length > expectedTotal) throw new Error('Longhu response exceeds Total')
        if (list.length === expectedTotal) break
        if (page.list.length < PAGE_SIZE) throw new Error('truncated Longhu response')
        if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs))
      }
    } finally {
      clearTimeout(timer)
    }

    const sessionDate = sessionDateFromRows(list)
    const fetchedAt = now()
    const data = { List: list, Total: expectedTotal, errcode: '0' }
    if (!sessionDate) {
      await layeredCache.set(
        `big-order:longhu:empty:v1:${shanghaiDate(now())}:${stockCode}:0`,
        { data, sessionDate: null, fetchedAt },
        { ttlSeconds: 5, staleTtlSeconds: 30 },
      )
      return { data, sessionDate: null, fetchedAt }
    }
    await layeredCache.set(
      `big-order:longhu:all-day:v2:${sessionDate}:${stockCode}:${money}`,
      { data, sessionDate, fetchedAt },
      { ttlSeconds: 10, staleTtlSeconds: 300 },
    )
    if (list.length > 0 && money === 0) {
      await layeredCache.set(
        `big-order:longhu:latest:v1:${stockCode}`,
        sessionDate,
        { ttlSeconds: 604800, staleTtlSeconds: 604800 },
      )
    }
    lastFullRebuildAt.set(`${stockCode}:${money}`, now())
    return { data, sessionDate, fetchedAt }
  }

  async function loadAllDay({ stockCode, money = 0 }) {
    if (money !== 0) throw new Error('canonical Longhu all-day only supports money=0')
    const latest = await layeredCache.get(`big-order:longhu:latest:v1:${stockCode}`, {
      allowStale: true,
    })
    if (latest?.value) {
      const key = `big-order:longhu:all-day:v2:${latest.value}:${stockCode}:0`
      const cached = await layeredCache.get(key, { allowStale: true })
      if (cached) {
        if (cached.stale) {
          scheduleRefresh({ key, stockCode, money, cached: cached.value })
        }
        return {
          ...cached.value,
          cache: { hit: true, stale: cached.stale, store: cached.store },
          refresh: { mode: 'cache-hit', inProgress: false, pagesFetched: 0, newRows: 0 },
        }
      }
    }
    const empty = await layeredCache.get(
      `big-order:longhu:empty:v1:${shanghaiDate(now())}:${stockCode}:0`,
      { allowStale: true },
    )
    if (empty) {
      return {
        ...empty.value,
        cache: { hit: true, stale: empty.stale, store: empty.store },
        refresh: { mode: 'cache-hit', inProgress: false, pagesFetched: 0, newRows: 0 },
      }
    }
    const result = await scheduler.run(`${stockCode}:${money}`, 'cold', 3, () =>
      rebuild({ stockCode, money }),
    )
    return {
      ...result,
      cache: { hit: false, stale: false, store: 'upstream' },
      refresh: { mode: 'cold-full', inProgress: false, pagesFetched: 0, newRows: 0 },
    }
  }

  function scheduleRefresh(input) {
    const cooldownMs = incrementalMode === 'off' ? 300_000 : 60_000
    const lastFull = lastFullRebuildAt.get(`${input.stockCode}:${input.money}`) || 0
    if (incrementalMode === 'off' && now() - lastFull < cooldownMs) return null
    if (pendingRefreshes.has(input.key)) return pendingRefreshes.get(input.key)
    const pending = scheduler
      .run(`${input.stockCode}:${input.money}`, 'head', 2, () => refreshCached(input))
      .catch(() => null)
      .finally(() => pendingRefreshes.delete(input.key))
    pendingRefreshes.set(input.key, pending)
    return pending
  }

  async function refreshCached({ key, stockCode, money, cached }) {
    if (incrementalMode === 'off') {
      return rebuild({ stockCode, money })
    }
    const device = deviceId()
    const oldRows = cached.data.List
    const oldTotal = Number(cached.data.Total)
    const head = await requestPage({ stockCode, money, index: 0, device })
    const canFullRebuild = () => {
      const last = lastFullRebuildAt.get(`${stockCode}:${money}`) || 0
      return now() - last >= 60_000
    }
    if (head.total < oldTotal) {
      if (!canFullRebuild()) throw new Error('Longhu full rebuild cooling down')
      return rebuild({ stockCode, money })
    }
    const delta = head.total - oldTotal
    const overlap = Math.min(20, oldRows.length)
    const needed = delta + overlap
    const rows = [...head.list]
    while (rows.length < needed) {
      const page = await requestPage({
        stockCode,
        money,
        index: rows.length,
        device,
      })
      if (page.total !== head.total) throw new Error('Longhu Total changed during incremental refresh')
      if (page.list.length === 0) throw new Error('truncated Longhu incremental response')
      rows.push(...page.list)
    }
    const same = (left, right) => JSON.stringify(left) === JSON.stringify(right)
    for (let index = 0; index < overlap; index++) {
      if (!same(rows[delta + index], oldRows[index])) {
        if (!canFullRebuild()) throw new Error('Longhu full rebuild cooling down')
        return rebuild({ stockCode, money })
      }
    }
    const nextRows = delta === 0 ? oldRows : rows.slice(0, delta).concat(oldRows)
    const value = {
      data: { List: nextRows, Total: head.total, errcode: '0' },
      sessionDate: cached.sessionDate,
      fetchedAt: now(),
    }
    await layeredCache.set(key, value, { ttlSeconds: 10, staleTtlSeconds: 300 })
    return value
  }

  async function loadPage({ stockCode, money = 0, index = 0, limit = 100 }) {
    return scheduler.run(`${stockCode}:${money}:${index}:${limit}`, 'page', 3, async () => {
      const device = deviceId()
      const output = []
      let offset = index
      while (output.length < limit) {
        const page = await requestPage({ stockCode, money, index: offset, device })
        const take = Math.min(page.list.length, limit - output.length)
        output.push(...page.list.slice(0, take))
        if (take < PAGE_SIZE || output.length >= limit) {
          return { List: output, Total: page.total, errcode: '0' }
        }
        offset += page.list.length
        if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs))
      }
      return { List: output, Total: output.length, errcode: '0' }
    })
  }

  return { incrementalMode, loadAllDay, loadPage }
}
