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
