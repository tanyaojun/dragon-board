import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildBadRequestEnvelope,
  buildDeprecatedEnvelope,
  buildDegradedEnvelope,
  classifyUpstreamError,
} from '../helpers/response.js'

test('builds a structured degraded envelope without leaking sensitive headers', () => {
  const error = new Error('Request failed with status code 503')
  error.response = {
    status: 503,
    headers: {
      'set-cookie': ['xq_a_token=secret'],
      cookie: 'xq_id_token=secret',
      'content-type': 'text/html',
    },
  }
  error.config = {
    url: 'https://stock.xueqiu.com/v5/stock/hot_stock/list.json?Token=secret&DeviceID=device-1&page=1',
    headers: {
      Cookie: 'xq_a_token=secret',
      Referer: 'https://xueqiu.com/',
    },
  }

  const envelope = buildDegradedEnvelope({
    source: 'xueqiu',
    error,
    fallbackData: { data: { items: [] } },
  })

  assert.equal(envelope.ok, false)
  assert.equal(envelope.degraded, true)
  assert.equal(envelope.source, 'xueqiu')
  assert.equal(envelope.errorCode, 'upstream_503')
  assert.deepEqual(envelope.data, { data: { items: [] } })
  assert.equal(JSON.stringify(envelope).includes('secret'), false)
  assert.equal(JSON.stringify(envelope).includes('device-1'), false)
  assert.equal(JSON.stringify(envelope).includes('xq_a_token'), false)
  assert.equal(envelope.details.upstreamUrl.includes('Token='), false)
  assert.equal(envelope.details.upstreamUrl.includes('DeviceID='), false)
  assert.equal(envelope.details.upstreamUrl.includes('page=1'), true)
})

test('classifies timeout and network errors for retryable upstream failures', () => {
  assert.equal(classifyUpstreamError({ code: 'ECONNABORTED' }), 'upstream_timeout')
  assert.equal(classifyUpstreamError({ code: 'ETIMEDOUT' }), 'upstream_timeout')
  assert.equal(classifyUpstreamError({ code: 'ENOTFOUND' }), 'upstream_network_error')
  assert.equal(classifyUpstreamError({ response: { status: 429 } }), 'upstream_429')
})

test('builds bad request and deprecated envelopes with stable fields', () => {
  assert.deepEqual(buildBadRequestEnvelope('missing_codes', '缺少 codes 参数'), {
    ok: false,
    degraded: false,
    source: 'proxy',
    errorCode: 'missing_codes',
    message: '缺少 codes 参数',
  })

  assert.deepEqual(
    buildDeprecatedEnvelope({
      source: 'theme',
      message: '已迁移到 QuantBoard',
      data: { items: [] },
    }),
    {
      ok: false,
      degraded: true,
      deprecated: true,
      source: 'theme',
      errorCode: 'proxy_endpoint_deprecated',
      message: '已迁移到 QuantBoard',
      data: { items: [] },
    },
  )
})
