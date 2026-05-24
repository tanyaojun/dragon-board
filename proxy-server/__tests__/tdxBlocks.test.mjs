import assert from 'node:assert/strict'
import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import test from 'node:test'

import { createProxyApp } from '../app.js'
import { parseTdxBlockLines } from '../services/tdxBlocks.js'

function listen(app) {
  return new Promise((resolve) => {
    const server = app.listen(0, '127.0.0.1', () => {
      const address = server.address()
      resolve({ server, baseUrl: `http://127.0.0.1:${address.port}` })
    })
  })
}

test('parseTdxBlockLines normalizes TDX seven digit codes and filters invalid rows', () => {
  const result = parseTdxBlockLines('sample.blk', [
    '0300834',
    '1603072',
    '0002082',
    '1880001',
    '0300834',
    'not-a-code',
  ])

  assert.deepEqual(result.codes.map((item) => item.code), ['300834', '603072', '002082'])
  assert.equal(result.issues.filter((issue) => issue.reason === 'duplicate').length, 1)
  assert.equal(result.issues.filter((issue) => issue.reason === 'invalid_code').length, 2)
})

test('GET /api/tdx-blocks/codes loads local block files through configured TDX_BLOCK_DIR', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'dragon-board-tdx-blocks-'))
  await writeFile(join(directory, '自选股.blk'), '0300834\n1603072\n', 'utf8')
  await writeFile(join(directory, '观察.blk'), '0002082\n0300834\n', 'utf8')

  const { server, baseUrl } = await listen(createProxyApp({
    logRequests: false,
    localEnv: { TDX_BLOCK_DIR: directory },
  }))

  try {
    const response = await fetch(`${baseUrl}/api/tdx-blocks/codes`)
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.deepEqual(body.data.codes, ['002082', '300834', '603072'])
    assert.equal(body.data.files.length, 2)
    assert.equal(body.data.duplicateCount, 1)
  } finally {
    server.close()
  }
})

test('GET /api/tdx-blocks/codes does not fall back to all files when requested files are invalid', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'dragon-board-tdx-blocks-'))
  await writeFile(join(directory, '自选股.blk'), '0300834\n', 'utf8')

  const { server, baseUrl } = await listen(createProxyApp({
    logRequests: false,
    localEnv: { TDX_BLOCK_DIR: directory },
  }))

  try {
    const response = await fetch(`${baseUrl}/api/tdx-blocks/codes?files=../outside.blk`)
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.deepEqual(body.data.codes, [])
    assert.equal(body.data.files.length, 0)
  } finally {
    server.close()
  }
})

test('GET /api/tdx-blocks reads YiDongJingLing desktop settings for directory and selected files', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'dragon-board-tdx-blocks-'))
  const settingsPath = join(directory, 'settings.json')
  const selectedPath = join(directory, 'ZB.blk')
  await writeFile(join(directory, '观察.blk'), '0300834\n', 'utf8')
  await writeFile(selectedPath, '1603072\n', 'utf8')
  await writeFile(settingsPath, JSON.stringify({
    BlockDirectory: directory,
    SelectedBlockFiles: [selectedPath],
  }), 'utf8')

  const { server, baseUrl } = await listen(createProxyApp({
    logRequests: false,
    localEnv: { TDX_BLOCK_SETTINGS_PATH: settingsPath },
  }))

  try {
    const response = await fetch(`${baseUrl}/api/tdx-blocks`)
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.equal(body.data.directory, resolve(directory))
    assert.deepEqual(body.data.selectedFiles, [resolve(selectedPath)])
    const selectedByName = Object.fromEntries(body.data.files.map((file) => [file.name, file.selected]))
    assert.deepEqual(selectedByName, {
      'ZB.blk': true,
      '观察.blk': false,
    })
  } finally {
    server.close()
  }
})

test('POST /api/tdx-blocks/selection writes selected block files back to YiDongJingLing desktop settings', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'dragon-board-tdx-blocks-'))
  const settingsPath = join(directory, 'settings.json')
  const zbPath = join(directory, 'ZB.blk')
  const watchPath = join(directory, '观察.blk')
  await writeFile(zbPath, '1603072\n', 'utf8')
  await writeFile(watchPath, '0300834\n', 'utf8')
  await writeFile(settingsPath, JSON.stringify({
    BlockDirectory: directory,
    SelectedBlockFiles: [zbPath],
    BridgeUrl: 'ws://127.0.0.1:8765/ws/quotes',
  }), 'utf8')

  const { server, baseUrl } = await listen(createProxyApp({
    logRequests: false,
    localEnv: { TDX_BLOCK_SETTINGS_PATH: settingsPath },
  }))

  try {
    const response = await fetch(`${baseUrl}/api/tdx-blocks/selection`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files: ['观察.blk', '../outside.blk'] }),
    })
    const body = await response.json()
    const saved = JSON.parse(await readFile(settingsPath, 'utf8'))

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.deepEqual(body.data.selectedFiles, [resolve(watchPath)])
    assert.deepEqual(saved.SelectedBlockFiles, [resolve(watchPath)])
    assert.equal(saved.BridgeUrl, 'ws://127.0.0.1:8765/ws/quotes')
  } finally {
    server.close()
  }
})
