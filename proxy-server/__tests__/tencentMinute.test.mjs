import assert from 'node:assert/strict'
import test from 'node:test'

import { createProxyApp } from '../app.js'

test('retired Tencent minute route is absent', async () => {
  const app = createProxyApp({ logRequests: false })
  const server = app.listen(0, '127.0.0.1')
  await new Promise((resolve) => server.once('listening', resolve))
  try {
    const address = server.address()
    const response = await fetch(
      `http://127.0.0.1:${address.port}/api/quotes/tencent/minute?code=002297`,
    )
    assert.equal(response.status, 404)
  } finally {
    server.close()
  }
})
