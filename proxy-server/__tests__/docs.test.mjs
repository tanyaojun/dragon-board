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
    assert.equal(body.paths['/api/quotes/eastmoney'], undefined)
    assert.equal(body.paths['/api/quotes/tencent/minute'], undefined)
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
    assert.equal(body.paths['/api/big-order/ths-detail'], undefined)
    assert.equal(
      body.paths['/api/big-order/longhu/all-day'].get.responses[200].content['application/json'].schema.$ref,
      '#/components/schemas/BigOrderEnvelope',
    )
    assert.deepEqual(body.components.schemas.BigOrderEnvelope.required, [
      'ok',
      'source',
      'stockCode',
      'sessionDate',
      'fetchedAt',
      'servedAt',
      'data',
    ])
    assert.ok(body.components.schemas.BigOrderEnvelope.properties.data.properties.dragonMeta)
    assert.deepEqual(body.components.schemas.BigOrderDragonMeta.required, ['cache'])
    assert.ok(body.components.schemas.BigOrderDragonMeta.properties.cache.properties.uiStale)
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
    assert.deepEqual(
      body.paths['/api/opening-signals'].post.requestBody.content['application/json'].schema.properties.signal.required,
      ['stage', 'status', 'code', 'name', 'time', 'price', 'pct', 'amount', 'voiceEligible', 'reason'],
    )
    assert.equal(
      body.paths['/api/opening-signals'].post.requestBody.content['application/json'].schema.properties.signal
        .additionalProperties,
      false,
    )
    assert.deepEqual(openingSignalProperties.stage.enum, [
      'auctionConditionPassed',
      'auctionConditionFailed',
      'gapAlert',
      'noGap',
      'trendConfirm',
      'trendWeak',
      'optionalFinalStatus',
    ])
    assert.equal(openingSignalProperties.voiceEligible.type, 'boolean')
    assert.ok(openingSignalProperties.reason)
    assert.deepEqual(Object.keys(openingSignalProperties).sort(), [
      'amount',
      'code',
      'name',
      'pct',
      'price',
      'reason',
      'stage',
      'status',
      'time',
      'voiceEligible',
    ])
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
