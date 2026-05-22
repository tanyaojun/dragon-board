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

function signal(overrides = {}) {
  return {
    tradingDate: '2026-05-22',
    code: '002552',
    name: '宝鼎科技',
    signalType: 'opening_weak_to_strong',
    confidence: 'strong',
    score: 82,
    triggerAt: '2026-05-22T09:30:06+08:00',
    dryRun: false,
    variant: 'auction_gap_reversal',
    ...overrides,
  }
}

async function postSignal(baseUrl, source, payload) {
  const response = await fetch(`${baseUrl}/api/opening-signals`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ source, signal: payload }),
  })
  return { response, body: await response.json() }
}

test('opening signal route creates and queries today signals', async () => {
  const app = createProxyApp({ logRequests: false })
  const { server, baseUrl } = await listen(app)

  try {
    const { response, body } = await postSignal(baseUrl, 'web', signal())

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.equal(body.accepted, true)
    assert.equal(body.isNew, true)
    assert.equal(body.dedupeAction, 'created')
    assert.equal(body.voiceOwner, 'web')
    assert.deepEqual(body.sources, ['web'])
    assert.equal(body.canonicalSignal.code, '002552')

    const todayResponse = await fetch(`${baseUrl}/api/opening-signals/today?tradingDate=2026-05-22`)
    const today = await todayResponse.json()
    assert.equal(todayResponse.status, 200)
    assert.equal(today.ok, true)
    assert.equal(today.signals.length, 1)
    assert.equal(today.signals[0].canonicalSignal.code, '002552')
  } finally {
    server.close()
  }
})

test('opening signal route upgrades canonical signal and preserves reports by source', async () => {
  const app = createProxyApp({ logRequests: false })
  const { server, baseUrl } = await listen(app)

  try {
    const first = await postSignal(baseUrl, 'web', signal({ confidence: 'watch', score: 52 }))
    assert.equal(first.body.dedupeAction, 'created')
    assert.equal(first.body.voiceOwner, 'none')

    const second = await postSignal(baseUrl, 'desktop', signal({ confidence: 'critical', score: 93 }))
    assert.equal(second.response.status, 200)
    assert.equal(second.body.isNew, false)
    assert.equal(second.body.dedupeAction, 'upgraded')
    assert.equal(second.body.voiceOwner, 'desktop')
    assert.deepEqual(second.body.sources, ['web', 'desktop'])
    assert.equal(second.body.canonicalSignal.confidence, 'critical')
    assert.equal(second.body.canonicalSignal.score, 93)
    assert.equal(second.body.reportsBySource.web.confidence, 'watch')
    assert.equal(second.body.reportsBySource.desktop.confidence, 'critical')
  } finally {
    server.close()
  }
})

test('opening signal route authorizes voice only once per dedupe key', async () => {
  const app = createProxyApp({ logRequests: false })
  const { server, baseUrl } = await listen(app)

  try {
    const first = await postSignal(baseUrl, 'web', signal({ confidence: 'strong', score: 80 }))
    const second = await postSignal(baseUrl, 'desktop', signal({ confidence: 'critical', score: 98 }))

    assert.equal(first.body.voiceOwner, 'web')
    assert.equal(second.body.dedupeAction, 'upgraded')
    assert.equal(second.body.voiceOwner, 'none')
    assert.equal(second.body.voiceGrantedTo, 'web')
    assert.equal(second.body.canonicalSignal.confidence, 'critical')
  } finally {
    server.close()
  }
})

test('opening signal route grants desktop first voice and suppresses later web report', async () => {
  const app = createProxyApp({ logRequests: false })
  const { server, baseUrl } = await listen(app)

  try {
    const first = await postSignal(baseUrl, 'desktop', signal({ confidence: 'critical', score: 96 }))
    const second = await postSignal(baseUrl, 'web', signal({ confidence: 'strong', score: 82 }))

    assert.equal(first.body.voiceOwner, 'desktop')
    assert.equal(second.body.voiceOwner, 'none')
    assert.equal(second.body.voiceGrantedTo, 'desktop')
    assert.deepEqual(second.body.sources, ['desktop', 'web'])
  } finally {
    server.close()
  }
})

test('opening signal route suppresses dry-run voice and rejects invalid payloads', async () => {
  const app = createProxyApp({ logRequests: false })
  const { server, baseUrl } = await listen(app)

  try {
    const dryRun = await postSignal(baseUrl, 'desktop', signal({ dryRun: true, confidence: 'critical' }))
    assert.equal(dryRun.body.voiceOwner, 'none')
    assert.equal(dryRun.body.canonicalSignal.dryRun, true)

    const invalidResponse = await fetch(`${baseUrl}/api/opening-signals`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ source: 'web', signal: { code: 'abc' } }),
    })
    const invalid = await invalidResponse.json()
    assert.equal(invalidResponse.status, 400)
    assert.equal(invalid.ok, false)
    assert.equal(invalid.errorCode, 'opening_signal_invalid')
  } finally {
    server.close()
  }
})

test('opening signal route lets real signal replace previous dry-run report', async () => {
  const app = createProxyApp({ logRequests: false })
  const { server, baseUrl } = await listen(app)

  try {
    const dryRun = await postSignal(baseUrl, 'web', signal({ dryRun: true, confidence: 'critical', score: 95 }))
    assert.equal(dryRun.body.voiceOwner, 'none')
    assert.equal(dryRun.body.canonicalSignal.dryRun, true)

    const real = await postSignal(baseUrl, 'desktop', signal({ dryRun: false, confidence: 'strong', score: 82 }))
    assert.equal(real.response.status, 200)
    assert.equal(real.body.dedupeAction, 'upgraded')
    assert.equal(real.body.voiceOwner, 'desktop')
    assert.equal(real.body.canonicalSignal.dryRun, false)
    assert.equal(real.body.canonicalSignal.source, 'desktop')
  } finally {
    server.close()
  }
})
