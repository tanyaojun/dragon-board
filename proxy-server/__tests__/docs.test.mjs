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
    assert.equal(
      body.paths['/api/cache/startup-bundle'].post.requestBody.content['application/json'].schema.properties.key
        .pattern,
      '^[0-9A-Za-z:_-]{1,120}$',
    )
    assert.deepEqual(
      body.paths['/api/cache/startup-bundle'].post.requestBody.content['application/json'].schema.required,
      ['key', 'bundle'],
    )
    assert.ok(body.paths['/api/market/overview'].get)
    assert.ok(body.paths['/api/tdx/{entry}'].post)
    assert.ok(body.paths['/api/tdx-blocks'].get)
    assert.ok(body.paths['/api/tdx-blocks/codes'].get)
    assert.equal(body.paths['/api/tdx-blocks/codes'].get.tags[0], 'tdx-blocks')
    assert.ok(body.paths['/api/opening-signals'].post)
    assert.ok(body.paths['/api/opening-signals/today'].get)
    assert.deepEqual(
      body.paths['/api/opening-signals'].post.requestBody.content['application/json'].schema.required,
      ['source', 'signal'],
    )
    const openingSignalProperties =
      body.paths['/api/opening-signals'].post.requestBody.content['application/json'].schema.properties.signal.properties
    assert.deepEqual(openingSignalProperties.liquidityTier.enum, ['unknown', 'thin', 'normal', 'active', 'hot'])
    assert.equal(openingSignalProperties.liquidityTierMode.const, 'review_only')
    assert.ok(openingSignalProperties.lateBaselinePrice)
    assert.ok(openingSignalProperties.auctionAmountDelta)
    assert.ok(openingSignalProperties.liquidityTierThresholds)
    assert.deepEqual(openingSignalProperties.intradayStatus.enum, [
      'preopen_candidate',
      'pending',
      'confirmed',
      'failed',
      'watch',
    ])
    assert.deepEqual(openingSignalProperties.intradayOutcome.enum, [
      'preopen_candidate',
      'pending',
      'confirmed_strong',
      'failed_open_dump',
      'watch_only',
    ])
    assert.ok(openingSignalProperties.intradayStatusAt)
    assert.ok(openingSignalProperties.intradayPrice)
    assert.ok(openingSignalProperties.intradayPct)
    assert.ok(openingSignalProperties.intradayAmount)
    assert.ok(openingSignalProperties.intradayNote)
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
