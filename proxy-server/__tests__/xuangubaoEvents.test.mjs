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

test('xuangubao events proxies stock and sector event history with sanitized default types', async () => {
  const requestedUrls = []
  const plainClient = {
    async get(url) {
      requestedUrls.push(url)
      return {
        data: {
          code: 20000,
          data: {
            stock_abnormal_event_data: [
              { id: 1, event_type: 10001, title: 'stock event' },
            ],
            plate_abnormal_event_data: [
              { id: 2, event_type: 11000, title: 'sector event' },
            ],
          },
        },
      }
    },
  }
  const app = createProxyApp({
    logRequests: false,
    clients: { client: plainClient, plainClient },
  })
  const { server, baseUrl } = await listen(app)

  try {
    const response = await fetch(`${baseUrl}/api/xuangubao/events`)
    const body = await response.json()
    const upstreamUrl = new URL(requestedUrls[0])

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.equal(body.source, 'xuangubao-events')
    assert.equal(body.upstreamCode, 20000)
    assert.deepEqual(body.data, [
      { id: 1, event_type: 10001, title: 'stock event' },
      { id: 2, event_type: 11000, title: 'sector event' },
    ])
    assert.equal(upstreamUrl.searchParams.get('count'), '100')
    assert.match(upstreamUrl.searchParams.get('types'), /10001/)
    assert.match(upstreamUrl.searchParams.get('types'), /11000/)
    assert.match(upstreamUrl.searchParams.get('types'), /11001/)
  } finally {
    server.close()
  }
})

test('xuangubao events clamps count and keeps requested sector event types', async () => {
  let requestedUrl = ''
  const plainClient = {
    async get(url) {
      requestedUrl = url
      return { data: { code: 0, data: [] } }
    },
  }
  const app = createProxyApp({
    logRequests: false,
    clients: { client: plainClient, plainClient },
  })
  const { server, baseUrl } = await listen(app)

  try {
    const response = await fetch(`${baseUrl}/api/xuangubao/events?count=500&types=10001,11000,11001,10005`)
    const body = await response.json()
    const upstreamUrl = new URL(requestedUrl)

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.equal(upstreamUrl.searchParams.get('count'), '200')
    assert.equal(upstreamUrl.searchParams.get('types'), '10001,11000,11001,10005')
  } finally {
    server.close()
  }
})

test('xuangubao events falls back to default types when requested types are unsupported', async () => {
  let requestedUrl = ''
  const plainClient = {
    async get(url) {
      requestedUrl = url
      return { data: { code: 0, data: [] } }
    },
  }
  const app = createProxyApp({
    logRequests: false,
    clients: { client: plainClient, plainClient },
  })
  const { server, baseUrl } = await listen(app)

  try {
    const response = await fetch(`${baseUrl}/api/xuangubao/events?types=99999`)
    const body = await response.json()
    const upstreamUrl = new URL(requestedUrl)

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.match(upstreamUrl.searchParams.get('types'), /10001/)
    assert.doesNotMatch(upstreamUrl.searchParams.get('types'), /99999/)
  } finally {
    server.close()
  }
})

test('xuangubao events returns degraded empty data when upstream fails', async () => {
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
  })
  const { server, baseUrl } = await listen(app)

  try {
    const response = await fetch(`${baseUrl}/api/xuangubao/events`)
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(body.ok, false)
    assert.equal(body.degraded, true)
    assert.equal(body.source, 'xuangubao-events')
    assert.equal(body.errorCode, 'upstream_network_error')
    assert.deepEqual(body.data, [])
  } finally {
    server.close()
  }
})
