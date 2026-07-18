import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import os from 'node:os'
import { join } from 'node:path'
import { gunzipSync } from 'node:zlib'

import { ProcessMemoryCache, LayeredProxyCache } from '../helpers/proxyCache.js'
import { createBigOrderArchiver } from '../services/bigOrderArchive.js'
import { createBigOrderCollector } from '../services/bigOrderCollector.js'
import { createLonghuBigOrderService } from '../services/longhuBigOrderCache.js'

// 2026-07-17（周五）10:00 上海 = 交易时段
const TRADING_NOW = Date.parse('2026-07-17T02:00:00Z')

const silentLogger = { log() {}, warn() {} }

function row(id, date = '2026-07-17 09:30:00') {
  return ['2', String(1_784_200_000 + id), '100', String(1000 + id), '10', date]
}

function tempDir() {
  return fs.mkdtempSync(join(os.tmpdir(), 'bigorder-archive-'))
}

function readArchive(file) {
  return JSON.parse(gunzipSync(fs.readFileSync(file)).toString('utf8'))
}

function makeCache(now) {
  return new LayeredProxyCache({
    memoryCache: new ProcessMemoryCache(now ? { now } : {}),
    redisCache: new ProcessMemoryCache(now ? { now } : {}),
  })
}

function pagedClient(rowsRef, calls = []) {
  return {
    post: async (url, body) => {
      const form = new URLSearchParams(body)
      calls.push(form)
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

test('archiver writes a gzip snapshot file under sessionDate directory', async () => {
  const dir = tempDir()
  const archiver = createBigOrderArchiver({ dir, logger: silentLogger })
  await archiver.save({
    sessionDate: '2026-07-17',
    stockCode: '600519',
    money: 0,
    value: {
      data: { List: [row(1)], Total: 1, errcode: '0' },
      sessionDate: '2026-07-17',
      fetchedAt: TRADING_NOW,
    },
  })

  const file = join(dir, '2026-07-17', '600519.money0.json.gz')
  assert.ok(fs.existsSync(file), 'archive file exists')
  const parsed = readArchive(file)
  assert.equal(parsed.sessionDate, '2026-07-17')
  assert.equal(parsed.stockCode, '600519')
  assert.equal(parsed.money, 0)
  assert.equal(parsed.fetchedAt, TRADING_NOW)
  assert.equal(parsed.data.Total, 1)
  assert.deepEqual(parsed.data.List, [row(1)])
})

test('archiver atomically overwrites the same stock-day file and leaves no temp files', async () => {
  const dir = tempDir()
  const archiver = createBigOrderArchiver({ dir, logger: silentLogger })
  const base = {
    sessionDate: '2026-07-17',
    stockCode: '600519',
    money: 0,
  }
  await archiver.save({
    ...base,
    value: { data: { List: [row(1)], Total: 1, errcode: '0' }, sessionDate: '2026-07-17', fetchedAt: 1 },
  })
  await archiver.save({
    ...base,
    value: {
      data: { List: [row(2), row(1)], Total: 2, errcode: '0' },
      sessionDate: '2026-07-17',
      fetchedAt: 2,
    },
  })

  const dayDir = join(dir, '2026-07-17')
  const files = fs.readdirSync(dayDir)
  assert.deepEqual(files, ['600519.money0.json.gz'], 'only the final file remains')
  const parsed = readArchive(join(dayDir, files[0]))
  assert.equal(parsed.data.Total, 2)
  assert.equal(parsed.fetchedAt, 2)
})

test('archiver failures are logged and do not reject', async () => {
  const warnings = []
  // 指向一个必然无法创建目录的路径（已有同名文件占位）
  const dir = tempDir()
  const blocker = join(dir, 'blocked')
  fs.writeFileSync(blocker, 'x')
  const archiver = createBigOrderArchiver({
    dir: blocker,
    logger: { log() {}, warn: (...args) => warnings.push(args.join(' ')) },
  })
  await archiver.save({
    sessionDate: '2026-07-17',
    stockCode: '600519',
    money: 0,
    value: { data: { List: [], Total: 0, errcode: '0' }, sessionDate: '2026-07-17', fetchedAt: 1 },
  })
  assert.equal(warnings.length, 1)
  assert.match(warnings[0], /归档失败/)
})

test('full rebuild archives the completed snapshot while empty results are skipped', async () => {
  const saved = []
  const archiver = { save: async (input) => void saved.push(input) }
  const rowsRef = { current: [row(2), row(1)] }
  const service = createLonghuBigOrderService({
    plainClient: pagedClient(rowsRef),
    layeredCache: makeCache(),
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
    archiver,
  })

  await service.loadAllDay({ stockCode: '600519', money: 0 })
  assert.equal(saved.length, 1)
  assert.equal(saved[0].sessionDate, '2026-07-17')
  assert.equal(saved[0].stockCode, '600519')
  assert.equal(saved[0].money, 0)
  assert.equal(saved[0].value.data.List.length, 2)

  // 合法空结果不归档
  rowsRef.current = []
  await service.loadAllDay({ stockCode: '000001', money: 0 })
  assert.equal(saved.length, 1)
})

test('incremental head merge archives the merged snapshot', async () => {
  let now = TRADING_NOW
  const saved = []
  const archiver = { save: async (input) => void saved.push(input) }
  const rowsRef = { current: [row(2), row(1)] }
  const service = createLonghuBigOrderService({
    plainClient: pagedClient(rowsRef),
    layeredCache: makeCache(() => now),
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'prepend-device-snapshot',
    archiver,
  })

  await service.loadAllDay({ stockCode: '600519', money: 0 })
  assert.equal(saved.length, 1)

  rowsRef.current = [row(3), row(2), row(1)]
  now += 11_000
  await service.loadAllDay({ stockCode: '600519', money: 0 })
  for (let attempt = 0; attempt < 100; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 10))
    if (saved.length === 2) break
  }
  assert.equal(saved.length, 2, 'incremental merge triggers one more archive')
  assert.equal(saved[1].value.data.List.length, 3)
  assert.deepEqual(saved[1].value.data.List[0], row(3))
})

test('archiver rejection does not break the rebuild response', async () => {
  const archiver = {
    save: async () => {
      throw new Error('disk full')
    },
  }
  const rowsRef = { current: [row(1)] }
  const warnings = []
  const service = createLonghuBigOrderService({
    plainClient: pagedClient(rowsRef),
    layeredCache: makeCache(),
    delayMs: 0,
    logger: { log() {}, warn: (...args) => warnings.push(args.join(' ')) },
    readConfig: () => 'off',
    archiver,
  })
  const result = await service.loadAllDay({ stockCode: '600519', money: 0 })
  assert.equal(result.data.List.length, 1)
  await new Promise((resolve) => setTimeout(resolve, 20))
  assert.ok(warnings.some((w) => /归档/.test(w)), 'archive failure is logged')
})

test('archiver.load returns the most recent archived snapshot for a stock', async () => {
  const dir = tempDir()
  const archiver = createBigOrderArchiver({ dir, logger: silentLogger })
  await archiver.save({
    sessionDate: '2026-07-16',
    stockCode: '600519',
    money: 0,
    value: { data: { List: [row(1, '2026-07-16 09:30:00')], Total: 1, errcode: '0' }, sessionDate: '2026-07-16', fetchedAt: 1 },
  })
  await archiver.save({
    sessionDate: '2026-07-17',
    stockCode: '600519',
    money: 0,
    value: { data: { List: [row(2), row(1)], Total: 2, errcode: '0' }, sessionDate: '2026-07-17', fetchedAt: 2 },
  })

  const restored = await archiver.load({ stockCode: '600519', money: 0 })
  assert.equal(restored.sessionDate, '2026-07-17')
  assert.equal(restored.data.Total, 2)

  assert.equal(await archiver.load({ stockCode: '000001', money: 0 }), null)
})

test('weekend cold miss restores from local archive with zero upstream requests', async () => {
  // 2026-07-18（周六）10:00 上海
  let now = Date.parse('2026-07-18T02:00:00Z')
  const dir = tempDir()
  const archiver = createBigOrderArchiver({ dir, logger: silentLogger })
  await archiver.save({
    sessionDate: '2026-07-17',
    stockCode: '600519',
    money: 0,
    value: { data: { List: [row(2), row(1)], Total: 2, errcode: '0' }, sessionDate: '2026-07-17', fetchedAt: TRADING_NOW },
  })

  const calls = []
  const service = createLonghuBigOrderService({
    plainClient: pagedClient({ current: [] }, calls),
    layeredCache: makeCache(() => now),
    now: () => now,
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
    archiver,
  })

  const result = await service.loadAllDay({ stockCode: '600519', money: 0 })
  await new Promise((resolve) => setTimeout(resolve, 20))
  assert.equal(result.sessionDate, '2026-07-17')
  assert.equal(result.data.List.length, 2)
  assert.equal(result.cache.stale, true, 'restored snapshot is served as stale')
  assert.equal(calls.length, 0, 'weekend restore must not touch upstream')

  // 第二次请求直接命中缓存，不再读归档
  const again = await service.loadAllDay({ stockCode: '600519', money: 0 })
  assert.equal(again.data.List.length, 2)
  assert.equal(calls.length, 0)
})

test('cold miss without archive still rebuilds from upstream', async () => {
  const dir = tempDir()
  const archiver = createBigOrderArchiver({ dir, logger: silentLogger })
  const calls = []
  const service = createLonghuBigOrderService({
    plainClient: pagedClient({ current: [row(1)] }, calls),
    layeredCache: makeCache(),
    delayMs: 0,
    logger: silentLogger,
    readConfig: () => 'off',
    archiver,
  })
  const result = await service.loadAllDay({ stockCode: '600519', money: 0 })
  assert.equal(result.data.List.length, 1)
  assert.ok(calls.length >= 1)
})

test('collector registers a deduplicated bounded daily list and persists it', async () => {
  const dir = tempDir()
  const collector = createBigOrderCollector({
    service: { loadAllDay: async () => ({}) },
    dir,
    now: () => TRADING_NOW,
    logger: silentLogger,
  })
  const first = await collector.register(['600519', '002297', '600519'])
  assert.deepEqual(first, ['600519', '002297'])
  const second = await collector.register(['000938'])
  assert.deepEqual(second, ['600519', '002297', '000938'])

  // 落盘后新实例仍能读回当日清单
  const reloaded = createBigOrderCollector({
    service: { loadAllDay: async () => ({}) },
    dir,
    now: () => TRADING_NOW,
    logger: silentLogger,
  })
  assert.deepEqual(await reloaded.list(), ['600519', '002297', '000938'])
})

test('collector runDaily loads every listed stock and one failure does not stop the rest', async () => {
  const dir = tempDir()
  const loaded = []
  const collector = createBigOrderCollector({
    service: {
      loadAllDay: async ({ stockCode }) => {
        loaded.push(stockCode)
        if (stockCode === '002297') throw new Error('blocked')
        return { data: { Total: 1 } }
      },
    },
    dir,
    now: () => TRADING_NOW,
    logger: silentLogger,
  })
  await collector.register(['600519', '002297', '000938'])
  const report = await collector.runDaily()
  assert.deepEqual(loaded, ['600519', '002297', '000938'])
  assert.equal(report.succeeded, 2)
  assert.equal(report.failed, 1)
})


test('corrupt archive for the latest date does not block fallback to the previous day', async () => {
  const dir = tempDir()
  const archiver = createBigOrderArchiver({ dir, logger: silentLogger })
  // 07-17 — 损坏（普通文本，非 gzip）
  const day17 = join(dir, '2026-07-17')
  fs.mkdirSync(day17, { recursive: true })
  fs.writeFileSync(join(day17, '600519.money0.json.gz'), 'not gzip')
  // 07-16 — 合法
  await archiver.save({
    sessionDate: '2026-07-16', stockCode: '600519', money: 0,
    value: { data: { List: [row(1, '2026-07-16 09:30:00')], Total: 1, errcode: '0' }, sessionDate: '2026-07-16', fetchedAt: 1 },
  })
  const restored = await archiver.load({ stockCode: '600519', money: 0 })
  assert.equal(restored.sessionDate, '2026-07-16', 'falls back to previous day')
  assert.equal(restored.data.Total, 1)
})
