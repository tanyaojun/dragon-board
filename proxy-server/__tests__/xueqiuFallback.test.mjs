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

test('xueqiu hotlist does not expose upstream failures as HTTP 500', async () => {
  const plainClient = {
    async get() {
      const error = new Error('upstream unavailable')
      error.code = 'ECONNRESET'
      throw error
    },
  }
  const app = createProxyApp({
    logRequests: false,
    clients: { client: plainClient, plainClient },
    readConfig: () => 'xueqiu-cookie=present',
  })
  const { server, baseUrl } = await listen(app)

  try {
    const response = await fetch(`${baseUrl}/api/xueqiu/hot`)
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(body.degraded, true)
    assert.equal(body.errorCode, 'upstream_network_error')
    assert.deepEqual(body.data.data.items, [])
  } finally {
    server.close()
  }
})
