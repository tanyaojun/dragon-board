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
    const reviewFields = {
      lateBaselineAt: '2026-05-22T09:24:05+08:00',
      lateBaselinePrice: 35.3,
      lateBaselinePct: -2.49,
      lateBaselineAmount: 4_500_000,
      finalBaselineAt: '2026-05-22T09:25:00+08:00',
      finalBaselinePrice: 35.68,
      finalBaselinePct: -1.44,
      finalBaselineAmount: 6_000_000,
      auctionPriceLiftPctPoint: 1.87,
      latePriceLiftPctPoint: 1.05,
      auctionAmountDelta: 4_000_000,
      lateAmountDelta: 1_500_000,
      auctionAmountLiftRatio: 2,
      lateAmountLiftRatio: 0.33,
      priceVolumeConfirmed: true,
      liquidityTier: 'active',
      liquidityTierMode: 'review_only',
      liquidityTierBasis: 'amount=56000000;volume=14950000',
      liquidityTierThresholds:
        'openingLiquidityMinAmount=5000000;minCurrentAmount=30000000;hotAmount=100000000;minCurrentVolume=1000000',
      liquidityTierVersion: 'liquidity-review.v1',
    }
    const { response, body } = await postSignal(baseUrl, 'web', signal(reviewFields))

    assert.equal(response.status, 200)
    assert.equal(body.ok, true)
    assert.equal(body.accepted, true)
    assert.equal(body.isNew, true)
    assert.equal(body.dedupeAction, 'created')
    assert.equal(body.voiceOwner, 'web')
    assert.deepEqual(body.sources, ['web'])
    assert.equal(body.canonicalSignal.code, '002552')
    assert.equal(body.canonicalSignal.lateBaselinePrice, 35.3)
    assert.equal(body.canonicalSignal.lateAmountDelta, 1_500_000)
    assert.equal(body.canonicalSignal.liquidityTier, 'active')
    assert.equal(body.canonicalSignal.liquidityTierBasis, reviewFields.liquidityTierBasis)
    assert.equal(body.canonicalSignal.liquidityTierThresholds, reviewFields.liquidityTierThresholds)
    assert.equal(body.canonicalSignal.liquidityTierVersion, 'liquidity-review.v1')
    assert.equal(body.reportsBySource.web.liquidityTierMode, 'review_only')
    assert.equal(body.reportsBySource.web.liquidityTierBasis, reviewFields.liquidityTierBasis)

    const todayResponse = await fetch(`${baseUrl}/api/opening-signals/today?tradingDate=2026-05-22`)
    const today = await todayResponse.json()
    assert.equal(todayResponse.status, 200)
    assert.equal(today.ok, true)
    assert.equal(today.signals.length, 1)
    assert.equal(today.signals[0].canonicalSignal.code, '002552')
    assert.equal(today.signals[0].canonicalSignal.lateBaselinePrice, 35.3)
    assert.equal(today.signals[0].canonicalSignal.liquidityTierThresholds, reviewFields.liquidityTierThresholds)
    assert.equal(today.signals[0].reportsBySource.web.liquidityTier, 'active')
    assert.equal(today.signals[0].reportsBySource.web.liquidityTierBasis, reviewFields.liquidityTierBasis)
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
    assert.equal(first.body.voiceOwner, 'web')

    const second = await postSignal(baseUrl, 'desktop', signal({ confidence: 'critical', score: 93 }))
    assert.equal(second.response.status, 200)
    assert.equal(second.body.isNew, false)
    assert.equal(second.body.dedupeAction, 'upgraded')
    assert.equal(second.body.voiceOwner, 'none')
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

test('opening signal route authorizes voice once for each opening action stage', async () => {
  const app = createProxyApp({ logRequests: false })
  const { server, baseUrl } = await listen(app)

  try {
    const preopen = await postSignal(baseUrl, 'web', signal({
      confidence: 'strong',
      score: 78,
      triggerAt: '2026-05-22T09:25:12+08:00',
      intradayStatus: 'preopen_candidate',
      intradayOutcome: 'preopen_candidate',
      intradayNote: '竞价量价齐升，等待开盘承接验证',
    }))
    assert.equal(preopen.body.voiceOwner, 'web')

    const pending = await postSignal(baseUrl, 'web', signal({
      confidence: 'strong',
      score: 82,
      triggerAt: '2026-05-22T09:30:06+08:00',
      intradayStatus: 'pending',
      intradayOutcome: 'pending',
    }))
    assert.equal(pending.body.dedupeAction, 'upgraded')
    assert.equal(pending.body.voiceOwner, 'web')
    assert.equal(pending.body.canonicalSignal.intradayStatus, 'pending')

    const duplicatePending = await postSignal(baseUrl, 'desktop', signal({
      confidence: 'critical',
      score: 96,
      triggerAt: '2026-05-22T09:30:08+08:00',
      intradayStatus: 'pending',
      intradayOutcome: 'pending',
    }))
    assert.equal(duplicatePending.body.voiceOwner, 'none')
    assert.equal(duplicatePending.body.voiceGrantedStages.preopen_candidate, 'web')
    assert.equal(duplicatePending.body.voiceGrantedStages.pending, 'web')
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

test('opening signal route lets intraday outcome update canonical signal', async () => {
  const app = createProxyApp({ logRequests: false })
  const { server, baseUrl } = await listen(app)

  try {
    const first = await postSignal(baseUrl, 'web', signal({
      confidence: 'strong',
      score: 82,
      intradayStatus: 'pending',
      intradayOutcome: 'pending',
    }))
    assert.equal(first.body.voiceOwner, 'web')

    const failed = await postSignal(baseUrl, 'web', signal({
      confidence: 'watch',
      score: 10,
      triggerAt: '2026-05-22T09:42:00+08:00',
      intradayStatus: 'failed',
      intradayOutcome: 'failed_open_dump',
      intradayStatusAt: '2026-05-22T09:42:00+08:00',
      intradayNote: '跌破开盘/昨收支撑，疑似竞价诱多',
    }))

    assert.equal(failed.response.status, 200)
    assert.equal(failed.body.dedupeAction, 'upgraded')
    assert.equal(failed.body.voiceOwner, 'none')
    assert.equal(failed.body.canonicalSignal.intradayStatus, 'failed')
    assert.equal(failed.body.canonicalSignal.intradayOutcome, 'failed_open_dump')
    assert.equal(failed.body.canonicalSignal.confidence, 'watch')
  } finally {
    server.close()
  }
})

test('opening signal route does not authorize stale strong voice when failed signal stays canonical', async () => {
  const app = createProxyApp({ logRequests: false })
  const { server, baseUrl } = await listen(app)

  try {
    const failed = await postSignal(baseUrl, 'web', signal({
      confidence: 'strong',
      score: 10,
      triggerAt: '2026-05-22T09:42:00+08:00',
      intradayStatus: 'failed',
      intradayOutcome: 'failed_open_dump',
      intradayStatusAt: '2026-05-22T09:42:00+08:00',
    }))
    assert.equal(failed.body.voiceOwner, 'none')
    assert.equal(failed.body.voiceGrantedTo, null)
    assert.equal(failed.body.canonicalSignal.intradayStatus, 'failed')

    const staleStrong = await postSignal(baseUrl, 'desktop', signal({
      confidence: 'strong',
      score: 90,
      triggerAt: '2026-05-22T09:30:08+08:00',
      intradayStatus: 'pending',
      intradayOutcome: 'pending',
    }))

    assert.equal(staleStrong.response.status, 200)
    assert.equal(staleStrong.body.dedupeAction, 'merged')
    assert.equal(staleStrong.body.voiceOwner, 'none')
    assert.equal(staleStrong.body.voiceGrantedTo, null)
    assert.equal(staleStrong.body.canonicalSignal.intradayStatus, 'failed')
    assert.equal(staleStrong.body.canonicalSignal.source, 'web')
  } finally {
    server.close()
  }
})
