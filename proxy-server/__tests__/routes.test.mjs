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

test('quote routes return structured 400 when codes are missing', async () => {
  const { server, baseUrl } = await listen(createProxyApp({ logRequests: false }))
  try {
    const response = await fetch(`${baseUrl}/api/quotes/tencent`)
    const body = await response.json()

    assert.equal(response.status, 400)
    assert.equal(body.ok, false)
    assert.equal(body.degraded, false)
    assert.equal(body.errorCode, 'missing_codes')
  } finally {
    server.close()
  }
})

test('quote routes reject malformed stock codes instead of padding them', async () => {
  const { server, baseUrl } = await listen(createProxyApp({ logRequests: false }))
  try {
    const response = await fetch(`${baseUrl}/api/quotes/tencent?codes=abc,1`)
    const body = await response.json()

    assert.equal(response.status, 400)
    assert.equal(body.ok, false)
    assert.equal(body.degraded, false)
    assert.equal(body.errorCode, 'missing_codes')
  } finally {
    server.close()
  }
})

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

test('unknown routes return structured 404', async () => {
  const { server, baseUrl } = await listen(createProxyApp({ logRequests: false }))
  try {
    const response = await fetch(`${baseUrl}/api/quotes/smart?codes=000001`)
    const body = await response.json()

    assert.equal(response.status, 404)
    assert.equal(body.ok, false)
    assert.equal(body.errorCode, 'proxy_route_not_found')
  } finally {
    server.close()
  }
})
