import assert from 'node:assert/strict'
import test from 'node:test'

import { createProxyApp } from '../app.js'

function listen(app) {
  return new Promise((resolve) => {
    const server = app.listen(0, '127.0.0.1', () => {
      const address = server.address()
      resolve({ server, baseUrl: `http://127.0.0.1:${address.port}` })
    })
  })
}

test('quant board ranktrend route is proxied through the stock proxy', async () => {
  let upstreamUrl = ''
  const app = createProxyApp({
    logRequests: false,
    fetchImpl: async (url) => {
      upstreamUrl = String(url)
      return new Response(JSON.stringify({ ok: true, frames: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(
      `${baseUrl}/api/ranktrend/rank-series?snapshot_type=half_hour&codes=000001`,
    )
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.equal(
      upstreamUrl,
      'http://127.0.0.1:8000/api/ranktrend/rank-series?snapshot_type=half_hour&codes=000001',
    )
  } finally {
    server.close()
  }
})

test('quant board proxy gzip-compresses passthrough responses for gzip clients', async () => {
  const upstreamBody = JSON.stringify({
    ok: true,
    frames: Array.from({ length: 120 }, (_, index) => ({
      code: '000001',
      frameKey: `2026-08-02 14:${String(index % 60).padStart(2, '0')}`,
      stocks: [{ code: '000001', analysis: { meta: { currentPercentile: index } } }],
    })),
  })
  const app = createProxyApp({
    logRequests: false,
    fetchImpl: async () =>
      new Response(upstreamBody, {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
  })
  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/ranktrend/analyze`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'accept-encoding': 'gzip',
      },
      body: JSON.stringify({ snapshotType: 'half_hour', codes: [] }),
    })
    assert.equal(response.status, 200)
    assert.equal(response.headers.get('content-encoding'), 'gzip')
    const body = await response.json()
    assert.equal(body.ok, true)
  } finally {
    server.close()
  }
})

test('cached quant board rank-series is gzip-compressed for gzip clients', async () => {
  let upstreamCalls = 0
  const app = createProxyApp({
    logRequests: false,
    fetchImpl: async () => {
      upstreamCalls += 1
      return new Response(
        JSON.stringify({
          ok: true,
          count: 1,
          frames: Array.from({ length: 120 }, (_, index) => ({
            snapshotId: `s${index}`,
            tradingDate: '2026-08-02',
            slotTime: `14:${String(index % 60).padStart(2, '0')}`,
            totalCount: 200,
          })),
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      )
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    const url = `${baseUrl}/api/ranktrend/rank-series?snapshot_type=half_hour&codes=000001`
    const headers = { 'accept-encoding': 'gzip' }

    const first = await fetch(url, { headers })
    assert.equal(first.status, 200)
    assert.equal(first.headers.get('content-encoding'), 'gzip')
    assert.equal((await first.json()).ok, true)

    const second = await fetch(url, { headers })
    assert.equal(second.status, 200)
    assert.equal(second.headers.get('content-encoding'), 'gzip')
    assert.equal((await second.json()).ok, true)
    assert.equal(upstreamCalls, 1)
  } finally {
    server.close()
  }
})

test('quant board proxy serves plain responses to clients without gzip support', async () => {
  let upstreamCalls = 0
  const app = createProxyApp({
    logRequests: false,
    fetchImpl: async () => {
      upstreamCalls += 1
      return new Response(
        JSON.stringify({
          ok: true,
          count: 1,
          frames: Array.from({ length: 120 }, (_, index) => ({
            snapshotId: `s${index}`,
            tradingDate: '2026-08-02',
            slotTime: `14:${String(index % 60).padStart(2, '0')}`,
            totalCount: 200,
          })),
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      )
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    const url = `${baseUrl}/api/ranktrend/rank-series?snapshot_type=half_hour&codes=000001`
    const headers = { 'accept-encoding': 'identity' }
    const first = await fetch(url, { headers })
    assert.equal(first.headers.get('content-encoding'), null)
    assert.equal((await first.json()).ok, true)

    const second = await fetch(url, { headers })
    assert.equal(second.headers.get('content-encoding'), null)
    assert.equal((await second.json()).ok, true)
    assert.equal(upstreamCalls, 1)
  } finally {
    server.close()
  }
})

test('unknown routes return structured 404', async () => {
  const { server, baseUrl } = await listen(createProxyApp({ logRequests: false }))
  try {
    const response = await fetch(`${baseUrl}/api/nonexistent-xyz`)
    const body = await response.json()

    assert.equal(response.status, 404)
    assert.equal(body.ok, false)
    assert.equal(body.errorCode, 'proxy_route_not_found')
  } finally {
    server.close()
  }
})
