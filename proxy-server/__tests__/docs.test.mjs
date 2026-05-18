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

test('openapi json documents the proxy server routes', async () => {
  const { server, baseUrl } = await listen(createProxyApp({ logRequests: false, port: 3000 }))
  try {
    const response = await fetch(`${baseUrl}/openapi.json`)
    const body = await response.json()

    assert.equal(response.status, 200)
    assert.equal(body.openapi, '3.1.0')
    assert.equal(body.info.title, 'Dragon Board Proxy API')
    assert.equal(body.servers[0].url, 'http://localhost:3000')
    assert.ok(body.paths['/api/eastmoney/hot'].post)
    assert.ok(body.paths['/api/quotes/eastmoney'].get)
    assert.ok(body.paths['/api/cache/startup-bundle'].get)
    assert.ok(body.paths['/api/cache/startup-bundle'].post)
    assert.ok(body.paths['/api/market/overview'].get)
    assert.ok(body.paths['/api/tdx/{entry}'].post)
  } finally {
    server.close()
  }
})

test('docs route serves local swagger ui shell', async () => {
  const { server, baseUrl } = await listen(createProxyApp({ logRequests: false }))
  try {
    const response = await fetch(`${baseUrl}/docs`)
    const html = await response.text()

    assert.equal(response.status, 200)
    assert.match(response.headers.get('content-type'), /text\/html/)
    assert.match(html, /SwaggerUIBundle/)
    assert.match(html, /\/openapi\.json/)
    assert.match(html, /\/docs-assets\/swagger-ui\.css/)
  } finally {
    server.close()
  }
})
