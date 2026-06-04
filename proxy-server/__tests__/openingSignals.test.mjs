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
    code: '002552',
    name: '宝鼎科技',
    time: '2026-06-03T09:30:00+08:00',
    stage: 'gapAlert',
    status: 'gapAlert',
    price: 10.35,
    pct: 3.5,
    amount: 8_000_000,
    voiceEligible: true,
    reason: '09:30较09:25明显改善，开盘承接转强',
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

test('opening signal route stores and lists stage-based opening checkpoints', async () => {
  const app = createProxyApp({ logRequests: false })
  const { server, baseUrl } = await listen(app)

  try {
    const created = await postSignal(baseUrl, 'web', signal({
      stage: 'auctionConditionPassed',
      status: 'auctionConditionPassed',
      voiceEligible: false,
      time: '2026-06-03T09:25:00+08:00',
    }))

    assert.equal(created.response.status, 200)
    assert.equal(created.body.ok, true)
    assert.equal(created.body.accepted, true)
    assert.equal(created.body.voiceOwner, 'none')
    assert.equal(created.body.canonicalSignal.stage, 'auctionConditionPassed')
    assert.deepEqual(Object.keys(created.body.canonicalSignal).sort(), [
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

    const todayResponse = await fetch(`${baseUrl}/api/opening-signals/today?tradingDate=2026-06-03`)
    const today = await todayResponse.json()
    assert.equal(todayResponse.status, 200)
    assert.equal(today.signals.length, 1)
    assert.equal(today.signals[0].canonicalSignal.stage, 'auctionConditionPassed')
  } finally {
    server.close()
  }
})

test('opening signal route authorizes voice only for gapAlert and trendConfirm stages', async () => {
  const app = createProxyApp({ logRequests: false })
  const { server, baseUrl } = await listen(app)

  try {
    const candidate = await postSignal(baseUrl, 'web', signal({
      stage: 'auctionConditionPassed',
      status: 'auctionConditionPassed',
      voiceEligible: false,
      time: '2026-06-03T09:25:00+08:00',
    }))
    assert.equal(candidate.body.voiceOwner, 'none')

    const gap = await postSignal(baseUrl, 'web', signal({
      stage: 'gapAlert',
      status: 'gapAlert',
      voiceEligible: true,
      time: '2026-06-03T09:30:00+08:00',
    }))
    assert.equal(gap.body.dedupeAction, 'upgraded')
    assert.equal(gap.body.voiceOwner, 'web')
    assert.equal(gap.body.voiceGrantedStages.gapAlert, 'web')

    const duplicateGap = await postSignal(baseUrl, 'desktop', signal({
      stage: 'gapAlert',
      status: 'gapAlert',
      voiceEligible: true,
      time: '2026-06-03T09:30:01+08:00',
    }))
    assert.equal(duplicateGap.body.voiceOwner, 'none')
    assert.equal(duplicateGap.body.voiceGrantedStages.gapAlert, 'web')

    const trend = await postSignal(baseUrl, 'desktop', signal({
      stage: 'trendConfirm',
      status: 'trendConfirm',
      voiceEligible: true,
      time: '2026-06-03T09:35:00+08:00',
    }))
    assert.equal(trend.body.voiceOwner, 'desktop')
    assert.equal(trend.body.voiceGrantedStages.trendConfirm, 'desktop')

    const final = await postSignal(baseUrl, 'web', signal({
      stage: 'optionalFinalStatus',
      status: 'optionalFinalStatus',
      voiceEligible: false,
      time: '2026-06-03T10:00:00+08:00',
    }))
    assert.equal(final.body.voiceOwner, 'none')
    assert.equal(final.body.canonicalSignal.stage, 'optionalFinalStatus')
  } finally {
    server.close()
  }
})

test('opening signal route rejects invalid payloads', async () => {
  const app = createProxyApp({ logRequests: false })
  const { server, baseUrl } = await listen(app)

  try {
    const invalidResponse = await fetch(`${baseUrl}/api/opening-signals`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ source: 'web', signal: { code: 'abc' } }),
    })
    const invalid = await invalidResponse.json()
    assert.equal(invalidResponse.status, 400)
    assert.equal(invalid.ok, false)
    assert.equal(invalid.errorCode, 'opening_signal_invalid')

    const extraFieldResponse = await fetch(`${baseUrl}/api/opening-signals`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        source: 'web',
        signal: signal({
          score: 99,
          confidence: 1,
        }),
      }),
    })
    const extraField = await extraFieldResponse.json()
    assert.equal(extraFieldResponse.status, 400)
    assert.equal(extraField.ok, false)
    assert.equal(extraField.errorCode, 'opening_signal_invalid')
  } finally {
    server.close()
  }
})
