import crypto from 'node:crypto'

import {
  LayeredProxyCache,
  ProcessMemoryCache,
  PROXY_CACHE_TTLS,
} from '../helpers/proxyCache.js'

const LONGHU_URL = 'https://apphwhq.longhuvip.com/w1/api/index.php'
const PAGE_SIZE = 200
const VALID_MODES = new Set(['off', 'prepend-device-snapshot', 'prepend-logical'])
// 增量头部刷新最多覆盖 10 页；超过说明积压太多，直接走受冷却保护的完整重建
const MAX_INCREMENTAL_ROWS = PAGE_SIZE * 10
const INCREMENTAL_BUDGET_MS = 20_000
const HISTORY_AUDIT_INTERVAL_MS = 300_000

class LonghuIntegrityError extends Error {}

function integrityError(message) {
  return new LonghuIntegrityError(message)
}

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

// 个别坏行只跳过日期提取；全部行都无法解析日期才整体失败（与 C# 解析器合同一致）
function sessionDateFromRows(rows) {
  let sessionDate = null
  let validRows = 0
  for (const row of rows || []) {
    const value = Array.isArray(row) ? row[5] : null
    const match = String(value || '').match(/^(\d{4}-\d{2}-\d{2})\s/)
    if (!match) continue
    validRows += 1
    if (sessionDate && sessionDate !== match[1]) {
      throw integrityError('Longhu snapshot contains mixed session dates')
    }
    sessionDate = match[1]
  }
  if ((rows || []).length > 0 && validRows === 0) {
    throw integrityError('Longhu rows missing session date')
  }
  return sessionDate
}

function shanghaiDate(timestamp) {
  return new Date(timestamp).toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' })
}

// 设计 §7 的时段 TTL 表：交易 10/300、盘前午间和收盘后半小时 60/900、其余(含周末) 1800/604800。
// off 模式的完整重建冷却同样分时段：闭市数据不再变化，不允许整夜重复全量分页。
export function longhuCacheSlot(timestamp) {
  const date = new Date(timestamp)
  const closed = { ttlSeconds: 1800, staleTtlSeconds: 604800, rebuildCooldownMs: 21_600_000 }
  const weekday = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    weekday: 'short',
  }).format(date)
  if (weekday === 'Sat' || weekday === 'Sun') return { ...closed, isWeekend: true }
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  const hour = Number(parts.find((part) => part.type === 'hour')?.value || 0)
  const minute = Number(parts.find((part) => part.type === 'minute')?.value || 0)
  const clock = hour * 60 + minute
  if ((clock >= 570 && clock <= 690) || (clock >= 780 && clock <= 900)) {
    return {
      ttlSeconds: PROXY_CACHE_TTLS.bigOrder.longhuAllDay,
      staleTtlSeconds: 300,
      rebuildCooldownMs: 300_000,
    }
  }
  if ((clock >= 540 && clock < 570) || (clock > 690 && clock < 780) || (clock > 900 && clock <= 930)) {
    return { ttlSeconds: 60, staleTtlSeconds: 900, rebuildCooldownMs: 300_000 }
  }
  return closed
}

function validatePage(payload) {
  if (!payload || String(payload.errcode) !== '0' || !Array.isArray(payload.List)) {
    throw integrityError(payload?.msg || 'invalid Longhu payload')
  }
  const total = Number(payload.Total)
  if (!Number.isInteger(total) || total < 0) throw integrityError('invalid Longhu Total')
  return { list: payload.List, total }
}

function requireCompletePage(page, index) {
  const expected = Math.min(PAGE_SIZE, Math.max(0, page.total - index))
  if (page.list.length < expected) throw integrityError('truncated Longhu response')
}

export function createLonghuBigOrderService({
  plainClient,
  layeredCache,
  now = () => Date.now(),
  delayMs = 150,
  readConfig = (name, fallback) => process.env[name] || fallback,
  scheduler = new LonghuRequestScheduler(),
  logger = console,
  archiver = null,
  fullRebuildBudgetMs = 45_000,
  pageCache = new LayeredProxyCache({
    memoryCache: new ProcessMemoryCache({
      now,
      maxEntries: 128,
      maxBytes: 32 * 1024 * 1024,
      maxValueBytes: 1024 * 1024,
    }),
  }),
} = {}) {
  const configuredMode = readConfig('BIG_ORDER_LONGHU_INCREMENTAL_MODE', 'off')
  const incrementalMode = VALID_MODES.has(configuredMode) ? configuredMode : 'off'
  const pendingRefreshes = new Map()
  const lastFullRebuildAt = new Map()
  const auditState = new Map()
  const lastSessionProbeAt = new Map()
  const keyIntegrityFailures = new Map()
  const incrementalFailures = new Map()
  let sourceFailureCount = 0
  let sourceBreakerUntil = 0

  function sleep(ms) {
    return ms > 0 ? new Promise((resolve) => setTimeout(resolve, ms)) : Promise.resolve()
  }

  // 完整快照通过校验并写入缓存的同一时刻，异步归档为本地文件资产；失败只告警不影响响应
  function archiveSnapshot({ sessionDate, stockCode, money, value }) {
    if (!archiver || !sessionDate) return
    Promise.resolve(archiver.save({ sessionDate, stockCode, money, value })).catch((error) => {
      logger.warn(`[龙虎缓存] 快照归档失败 ${sessionDate}/${stockCode}:`, error?.message)
    })
  }

  function ensureKeyAvailable(id) {
    if (keyIntegrityFailures.get(id)?.cooldownUntil > now()) {
      throw new Error('big_order_key_cooldown')
    }
  }

  function recordKeyIntegrityFailure(id, error) {
    if (!(error instanceof LonghuIntegrityError) || error.keyFailureRecorded) return
    error.keyFailureRecorded = true
    const health = keyIntegrityFailures.get(id)
    const failureCount = (health?.failureCount || 0) + 1
    keyIntegrityFailures.set(id, {
      failureCount: failureCount >= 3 ? 0 : failureCount,
      cooldownUntil: failureCount >= 3 ? now() + 60_000 : 0,
    })
    if (failureCount >= 3) logger.warn(`[龙虎缓存] ${id} 连续 3 次完整性失败，冷却 60 秒`)
  }

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
          logger.warn('[龙虎缓存] 连续 3 次网络级失败，熔断 60 秒')
        }
      }
      throw error
    }
    return validatePage(response.data)
  }

  async function rebuildStableAttempt({ stockCode, money, signal }) {
    const device = deviceId()
    const list = []
    let expectedTotal = null
    let pagesFetched = 0
    for (let index = 0; ; index = list.length) {
      const page = await requestPage({ stockCode, money, index, device, signal })
      pagesFetched += 1
      if (expectedTotal === null) expectedTotal = page.total
      else if (page.total !== expectedTotal) {
        throw integrityError('Longhu Total changed during pagination')
      }
      requireCompletePage(page, index)
      list.push(...page.list)
      if (list.length > expectedTotal) throw integrityError('Longhu response exceeds Total')
      if (list.length === expectedTotal) return { list, expectedTotal, pagesFetched }
      await sleep(delayMs)
    }
  }

  async function rebuildLogicalAttempt({ stockCode, money, signal }) {
    const device = deviceId()
    const list = []
    let targetTotal = null
    let observedTotal = null
    let pagesFetched = 0
    while (targetTotal === null || list.length < targetTotal) {
      const logicalOffset = list.length
      let page = null
      for (let retry = 0; retry <= 2; retry++) {
        const requestIndex = logicalOffset + Math.max(0, (observedTotal ?? targetTotal ?? 0) - (targetTotal ?? 0))
        page = await requestPage({ stockCode, money, index: requestIndex, device, signal })
        pagesFetched += 1
        if (targetTotal === null) targetTotal = page.total
        if (page.total < targetTotal) throw integrityError('Longhu Total decreased during logical pagination')
        const adjustedIndex = logicalOffset + (page.total - targetTotal)
        if (adjustedIndex === requestIndex) {
          requireCompletePage(page, requestIndex)
          observedTotal = page.total
          break
        }
        observedTotal = page.total
        page = null
      }
      if (!page) throw integrityError('Longhu logical page changed more than 2 times')
      const remaining = targetTotal - list.length
      list.push(...page.list.slice(0, remaining))
      if (list.length > targetTotal) throw integrityError('Longhu response exceeds target Total')
      if (list.length < targetTotal) await sleep(delayMs)
    }
    return { list, expectedTotal: targetTotal, pagesFetched }
  }

  async function rebuildUnprotected({ stockCode, money }) {
    const startedAt = now()
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), fullRebuildBudgetMs)
    let rebuilt
    try {
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          rebuilt =
            incrementalMode === 'prepend-logical'
              ? await rebuildLogicalAttempt({ stockCode, money, signal: controller.signal })
              : await rebuildStableAttempt({ stockCode, money, signal: controller.signal })
          break
        } catch (error) {
          if (controller.signal.aborted) {
            throw integrityError('Longhu full rebuild budget exceeded')
          }
          if (!(error instanceof LonghuIntegrityError) || attempt === 2 || controller.signal.aborted) {
            throw error
          }
        }
      }
    } finally {
      clearTimeout(timer)
    }
    const { list, expectedTotal, pagesFetched } = rebuilt

    const sessionDate = sessionDateFromRows(list)
    const fetchedAt = now()
    const data = { List: list, Total: expectedTotal, errcode: '0' }
    if (!sessionDate) {
      await layeredCache.set(
        `big-order:longhu:empty:v1:${shanghaiDate(now())}:${stockCode}:0`,
        { data, sessionDate: null, fetchedAt },
        { ttlSeconds: PROXY_CACHE_TTLS.bigOrder.longhuEmpty, staleTtlSeconds: 30 },
      )
      return {
        data,
        sessionDate: null,
        fetchedAt,
        refresh: {
          mode: 'full-rebuild',
          inProgress: false,
          pagesFetched,
          newRows: 0,
          total: expectedTotal,
          elapsedMs: Math.max(0, now() - startedAt),
          incrementFailureCount: 0,
        },
      }
    }
    const slot = longhuCacheSlot(now())
    await layeredCache.set(
      `big-order:longhu:all-day:v2:${sessionDate}:${stockCode}:${money}`,
      { data, sessionDate, fetchedAt },
      {
        ttlSeconds: slot.ttlSeconds,
        staleTtlSeconds: 604800,
        maxValueBytes: 8 * 1024 * 1024,
      },
    )
    if (list.length > 0 && money === 0) {
      await layeredCache.set(
        `big-order:longhu:latest:v1:${stockCode}`,
        sessionDate,
        { ttlSeconds: 604800, staleTtlSeconds: 604800 },
      )
    }
    lastFullRebuildAt.set(`${stockCode}:${money}`, now())
    auditState.set(`${stockCode}:${money}`, { lastAuditAt: now(), offset: PAGE_SIZE })
    archiveSnapshot({ sessionDate, stockCode, money, value: { data, sessionDate, fetchedAt } })
    logger.log(
      `[龙虎缓存] 完整重建 ${stockCode} money=${money} rows=${list.length} session=${sessionDate}`,
    )
    return {
      data,
      sessionDate,
      fetchedAt,
      refresh: {
        mode: 'full-rebuild',
        inProgress: false,
        pagesFetched,
        newRows: list.length,
        total: expectedTotal,
        elapsedMs: Math.max(0, now() - startedAt),
        incrementFailureCount: 0,
      },
    }
  }

  async function rebuild({ stockCode, money }) {
    const id = `${stockCode}:${money}`
    ensureKeyAvailable(id)
    try {
      const result = await rebuildUnprotected({ stockCode, money })
      keyIntegrityFailures.delete(id)
      incrementalFailures.delete(id)
      return result
    } catch (error) {
      recordKeyIntegrityFailure(id, error)
      throw error
    }
  }

  async function loadAllDay({ stockCode, money = 0, _restored = false }) {
    if (money !== 0) throw new Error('canonical Longhu all-day only supports money=0')
    const latest = await layeredCache.get(`big-order:longhu:latest:v1:${stockCode}`, {
      allowStale: true,
    })
    if (latest?.value) {
      const key = `big-order:longhu:all-day:v2:${latest.value}:${stockCode}:0`
      const cached = await layeredCache.get(key, { allowStale: true })
      if (cached) {
        const slot = longhuCacheSlot(now())
        const oldSession = cached.value.sessionDate && cached.value.sessionDate !== shanghaiDate(now())
        if (oldSession) {
          const probe = slot.isWeekend
            ? null
            : scheduleSessionProbe({ stockCode, money, cached: cached.value })
          return {
            ...cached.value,
            cache: { hit: true, stale: true, store: cached.store, ttlSeconds: slot.ttlSeconds },
            refresh: {
              mode: 'cache-hit',
              inProgress: Boolean(probe),
              pagesFetched: 0,
              newRows: 0,
              total: Number(cached.value.data.Total),
              elapsedMs: 0,
              incrementFailureCount: incrementalFailures.get(`${stockCode}:${money}`) || 0,
            },
          }
        }
        if (!cached.stale && incrementalMode !== 'off') {
          scheduleAudit({ key, stockCode, money, value: cached.value })
        }
        if (cached.stale) {
          scheduleRefresh({ key, stockCode, money, cached: cached.value })
        }
        return {
          ...cached.value,
          cache: { hit: true, stale: cached.stale, store: cached.store, ttlSeconds: slot.ttlSeconds },
          refresh: {
            mode: 'cache-hit',
            inProgress: pendingRefreshes.has(key),
            pagesFetched: 0,
            newRows: 0,
            total: Number(cached.value.data.Total),
            elapsedMs: 0,
            incrementFailureCount: incrementalFailures.get(`${stockCode}:${money}`) || 0,
          },
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
        cache: {
          hit: true,
          stale: empty.stale,
          store: empty.store,
          ttlSeconds: PROXY_CACHE_TTLS.bigOrder.longhuEmpty,
        },
        refresh: {
          mode: 'cache-hit',
          inProgress: false,
          pagesFetched: 0,
          newRows: 0,
          total: Number(empty.value.data.Total),
          elapsedMs: 0,
          incrementFailureCount: 0,
        },
      }
    }
    // 冷 miss 先尝试本地归档回填（设计 §7.1）：命中则以 stale 身份立即可读，避免整套全量分页
    if (!_restored && archiver?.load && (await restoreFromArchive(stockCode))) {
      return loadAllDay({ stockCode, money, _restored: true })
    }
    const result = await scheduler.run(`${stockCode}:${money}`, 'cold', 3, () =>
      rebuild({ stockCode, money }),
    )
    return {
      ...result,
      cache: {
        hit: false,
        stale: false,
        store: 'upstream',
        ttlSeconds: longhuCacheSlot(now()).ttlSeconds,
      },
      refresh: { ...result.refresh, mode: 'cold-full' },
    }
  }

  // 从本地归档恢复最近一个交易日快照到缓存（stale 身份）并重建 latest 指针；失败静默返回 false
  async function restoreFromArchive(stockCode) {
    let snapshot
    try {
      snapshot = await archiver.load({ stockCode, money: 0 })
    } catch {
      return false
    }
    if (!snapshot?.sessionDate || !Array.isArray(snapshot?.data?.List) || !snapshot.data.List.length) {
      return false
    }
    const value = {
      data: snapshot.data,
      sessionDate: snapshot.sessionDate,
      fetchedAt: Number(snapshot.fetchedAt) || 0,
    }
    const slot = longhuCacheSlot(now())
    await layeredCache.set(
      `big-order:longhu:all-day:v2:${snapshot.sessionDate}:${stockCode}:0`,
      value,
      {
        ttlSeconds: slot.ttlSeconds,
        staleTtlSeconds: 604800,
        maxValueBytes: 8 * 1024 * 1024,
        stale: true,
      },
    )
    await layeredCache.set(`big-order:longhu:latest:v1:${stockCode}`, snapshot.sessionDate, {
      ttlSeconds: 604800,
      staleTtlSeconds: 604800,
    })
    logger.log(
      `[龙虎缓存] 归档回填 ${stockCode} session=${snapshot.sessionDate} rows=${value.data.List.length}`,
    )
    return true
  }

  function scheduleSessionProbe({ stockCode, money, cached }) {
    const id = `${stockCode}:${money}`
    const lastProbe = lastSessionProbeAt.get(id) || 0
    if (now() - lastProbe < 60_000) return null
    lastSessionProbeAt.set(id, now())
    return scheduler
      .run(id, 'probe', 2, async () => {
        const head = await requestPage({ stockCode, money, index: 0, device: deviceId() })
        requireCompletePage(head, 0)
        if (head.total === 0) return cached
        const sessionDate = sessionDateFromRows(head.list)
        if (!sessionDate || sessionDate === cached.sessionDate) return cached
        return rebuild({ stockCode, money })
      })
      .catch((error) => {
        logger.warn(`[龙虎缓存] 交易日头页探测失败 ${stockCode}:`, error?.message)
        return null
      })
  }

  function scheduleRefresh(input) {
    if (incrementalMode === 'off') {
      // 完整重建冷却分时段：交易 300 秒；闭市 6 小时，闭市数据不变不重复全量分页
      const slot = longhuCacheSlot(now())
      if (slot.isWeekend) return null
      const lastFull = lastFullRebuildAt.get(`${input.stockCode}:${input.money}`) || 0
      if (now() - lastFull < slot.rebuildCooldownMs) return null
    }
    if (pendingRefreshes.has(input.key)) return pendingRefreshes.get(input.key)
    const pending = scheduler
      .run(`${input.stockCode}:${input.money}`, 'head', 2, () => refreshCached(input))
      .catch((error) => {
        logger.warn(`[龙虎缓存] 后台刷新失败 ${input.stockCode}:`, error?.message)
        return null
      })
      .finally(() => pendingRefreshes.delete(input.key))
    pendingRefreshes.set(input.key, pending)
    return pending
  }

  async function refreshCachedCore({ key, stockCode, money, cached }) {
    if (incrementalMode === 'off') {
      return rebuild({ stockCode, money })
    }
    const startedAt = now()
    const device = deviceId()
    const oldRows = cached.data.List
    const oldTotal = Number(cached.data.Total)
    const head = await requestPage({ stockCode, money, index: 0, device })
    requireCompletePage(head, 0)
    const fullRebuild = (reason) => {
      const last = lastFullRebuildAt.get(`${stockCode}:${money}`) || 0
      if (now() - last < 60_000) {
        throw new Error(`Longhu full rebuild cooling down (${reason})`)
      }
      return rebuild({ stockCode, money })
    }
    if (head.total < oldTotal) return fullRebuild('total decreased')
    const delta = head.total - oldTotal
    const overlap = Math.min(20, oldRows.length)
    const needed = delta + overlap
    if (needed > MAX_INCREMENTAL_ROWS) return fullRebuild('delta too large')
    const rows = [...head.list]
    let observedTotal = head.total
    while (rows.length < needed) {
      if (now() - startedAt > INCREMENTAL_BUDGET_MS) {
        throw new Error('Longhu incremental refresh budget exceeded')
      }
      await sleep(delayMs)
      const logicalOffset = rows.length
      let page = null
      if (incrementalMode === 'prepend-logical') {
        for (let retry = 0; retry <= 2; retry++) {
          const requestIndex = logicalOffset + (observedTotal - head.total)
          const candidate = await requestPage({ stockCode, money, index: requestIndex, device })
          if (candidate.total < head.total) {
            throw integrityError('Longhu Total decreased during logical incremental refresh')
          }
          observedTotal = candidate.total
          if (logicalOffset + (candidate.total - head.total) === requestIndex) {
            requireCompletePage(candidate, requestIndex)
            page = candidate
            break
          }
        }
        if (!page) throw integrityError('Longhu logical incremental page changed more than 2 times')
      } else {
        page = await requestPage({ stockCode, money, index: logicalOffset, device })
        if (page.total !== head.total) {
          throw integrityError('Longhu Total changed during incremental refresh')
        }
        requireCompletePage(page, logicalOffset)
      }
      rows.push(...page.list)
    }
    const same = (left, right) => JSON.stringify(left) === JSON.stringify(right)
    for (let index = 0; index < overlap; index++) {
      if (!same(rows[delta + index], oldRows[index])) {
        return fullRebuild('overlap mismatch')
      }
    }
    const nextRows = delta === 0 ? oldRows : rows.slice(0, delta).concat(oldRows)
    const value = {
      data: { List: nextRows, Total: head.total, errcode: '0' },
      sessionDate: cached.sessionDate,
      fetchedAt: now(),
    }
    const slot = longhuCacheSlot(now())
    await layeredCache.set(key, value, {
      ttlSeconds: slot.ttlSeconds,
      staleTtlSeconds: 604800,
      maxValueBytes: 8 * 1024 * 1024,
    })
    archiveSnapshot({ sessionDate: value.sessionDate, stockCode, money, value })
    scheduleAudit({ key, stockCode, money, value })
    return value
  }

  async function refreshCached(input) {
    const id = `${input.stockCode}:${input.money}`
    ensureKeyAvailable(id)
    try {
      const result = await refreshCachedCore(input)
      keyIntegrityFailures.delete(id)
      incrementalFailures.delete(id)
      return result
    } catch (error) {
      recordKeyIntegrityFailure(id, error)
      if (incrementalMode === 'off') throw error
      const failureCount = (incrementalFailures.get(id) || 0) + 1
      incrementalFailures.set(id, failureCount)
      const slot = longhuCacheSlot(now())
      const tooOld = slot.ttlSeconds === PROXY_CACHE_TTLS.bigOrder.longhuAllDay &&
        now() - Number(input.cached.fetchedAt || 0) > 60_000
      if (failureCount >= 2 || tooOld) {
        const last = lastFullRebuildAt.get(id) || 0
        if (now() - last >= 60_000) return rebuild({ stockCode: input.stockCode, money: input.money })
      }
      throw error
    }
  }

  function scheduleAudit(input) {
    const id = `${input.stockCode}:${input.money}`
    const state = auditState.get(id) || { lastAuditAt: now(), offset: PAGE_SIZE }
    if (now() - state.lastAuditAt < HISTORY_AUDIT_INTERVAL_MS) return null
    if (input.value.data.List.length <= PAGE_SIZE) return null
    state.lastAuditAt = now()
    auditState.set(id, state)
    return scheduler
      .run(id, 'audit', 1, () => auditHistory(input))
      .catch((error) => {
        logger.warn(`[龙虎缓存] 历史审计跳过 ${input.stockCode}:`, error?.message)
        return null
      })
  }

  // 设计 §6.3：普通请求只负责把到期审计作为最低优先级独立任务入队，不等待审计结果。
  async function auditHistory({ key, stockCode, money, value }) {
    const id = `${stockCode}:${money}`
    const state = auditState.get(id) || { lastAuditAt: now(), offset: PAGE_SIZE }
    const rows = value.data.List
    if (rows.length <= PAGE_SIZE) return value
    let offset = state.offset
    if (offset >= rows.length) offset = PAGE_SIZE
    state.offset = offset + PAGE_SIZE
    const page = await requestPage({ stockCode, money, index: offset, device: deviceId() })
    // 审计期间快照又前移了：本轮跳过，等下一轮
    if (page.total !== Number(value.data.Total)) return value
    requireCompletePage(page, offset)
    const expected = rows.slice(offset, offset + page.list.length)
    if (JSON.stringify(page.list) === JSON.stringify(expected)) return value
    logger.warn(`[龙虎缓存] 历史页漂移 ${stockCode} offset=${offset}，触发完整重建`)
    const slot = longhuCacheSlot(now())
    await layeredCache.set(key, value, {
      ttlSeconds: slot.ttlSeconds,
      staleTtlSeconds: 604800,
      maxValueBytes: 8 * 1024 * 1024,
      stale: true,
    })
    const last = lastFullRebuildAt.get(id) || 0
    if (now() - last >= 60_000) return rebuild({ stockCode, money })
    return value
  }

  // 公共分页窗口：以 Total 为完整性标准聚合内部 200 条页，拒绝把短页当末页的静默截断
  async function fetchPageWindow({ stockCode, money, index, limit }) {
    const device = deviceId()
    const output = []
    let offset = index
    let expectedTotal = null
    for (;;) {
      const page = await requestPage({ stockCode, money, index: offset, device })
      if (expectedTotal === null) expectedTotal = page.total
      else if (page.total !== expectedTotal) {
        throw integrityError('Longhu Total changed during pagination')
      }
      const take = Math.min(page.list.length, limit - output.length)
      output.push(...page.list.slice(0, take))
      offset += page.list.length
      const target = Math.min(limit, Math.max(0, expectedTotal - index))
      if (output.length >= target) {
        return { List: output, Total: expectedTotal, errcode: '0' }
      }
      if (page.list.length < PAGE_SIZE) throw integrityError('truncated Longhu page response')
      await sleep(delayMs)
    }
  }

  async function loadPage({ stockCode, money = 0, index = 0, limit = 100 }) {
    const id = `${stockCode}:${money}`
    ensureKeyAvailable(id)
    const latest = await layeredCache.get(`big-order:longhu:latest:v1:${stockCode}`, {
      allowStale: true,
    })
    const sessionDate = latest?.value || shanghaiDate(now())
    const key = `big-order:longhu:page:v2:${sessionDate}:${stockCode}:${money}:${index}:${limit}`
    try {
      const result = await pageCache.remember(
        key,
        {
          ttlSeconds: PROXY_CACHE_TTLS.bigOrder.longhuPage,
          staleTtlSeconds: 120,
          maxValueBytes: 1024 * 1024,
        },
        () =>
          scheduler.run(`${stockCode}:${money}:${index}:${limit}`, 'page', 3, () =>
            fetchPageWindow({ stockCode, money, index, limit }),
          ),
      )
      keyIntegrityFailures.delete(id)
      return result.value
    } catch (error) {
      recordKeyIntegrityFailure(id, error)
      throw error
    }
  }

  return { incrementalMode, loadAllDay, loadPage }
}
