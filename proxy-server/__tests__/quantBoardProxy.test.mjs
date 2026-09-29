import assert from 'node:assert/strict'
import test from 'node:test'

import { quantBoardTargetBase, shouldProxyToQuantBoard } from '../routes/quantBoardProxy.js'


test('theme heat summary and stock detail use QuantBoard proxy prefix', () => {
  assert.equal(shouldProxyToQuantBoard('/api/themes/heat'), true)
  assert.equal(shouldProxyToQuantBoard('/api/themes/heat/AI/stocks'), true)
  assert.equal(shouldProxyToQuantBoard('/api/themes/fund-rows'), true)
})

test('theme stock volume series (history tab) proxies to QuantBoard', () => {
  assert.equal(
    shouldProxyToQuantBoard(
      '/api/themes/stock-volume-series?theme_name=%E5%85%B3%E7%A8%8E%E6%88%98%E6%A6%82%E5%BF%B5',
    ),
    true,
  )
  assert.equal(shouldProxyToQuantBoard('/api/themes/stock-volume-series'), true)
})

test('theme momentum summary proxies to QuantBoard (v2 4th dimension)', () => {
  assert.equal(shouldProxyToQuantBoard('/api/theme-momentum/summary'), true)
  assert.equal(
    shouldProxyToQuantBoard('/api/theme-momentum/summary?dataset_id=dragonboard_live&snapshot_type=half_hour'),
    true,
  )
})


test('deprecated theme batch route is not captured by QuantBoard proxy', () => {
  assert.equal(shouldProxyToQuantBoard('/api/themes/batch'), false)
})

test('hotlist sentiment series proxies to QuantBoard (prefix boundary safe)', () => {
  assert.equal(shouldProxyToQuantBoard('/api/hotlist-sentiment/series'), true)
  assert.equal(
    shouldProxyToQuantBoard('/api/hotlist-sentiment/series?dataset_id=dragonboard_live&days=3'),
    true,
  )
  assert.equal(shouldProxyToQuantBoard('/api/hotlist-sentimentx/series'), false)
})

test('hotlist jev observe-track routes proxy to QuantBoard (prefix boundary safe)', () => {
  assert.equal(shouldProxyToQuantBoard('/api/hotlist-jev/series'), true)
  assert.equal(
    shouldProxyToQuantBoard('/api/hotlist-jev/series?dataset_id=dragonboard_live&date=2026-10-08'),
    true,
  )
  assert.equal(shouldProxyToQuantBoard('/api/hotlist-jev/evaluate'), true)
  assert.equal(shouldProxyToQuantBoard('/api/hotlist-jevx/series'), false)
})


test('QuantBoard target honors configured API base', () => {
  const previous = process.env.QUANT_BOARD_API_BASE
  process.env.QUANT_BOARD_API_BASE = 'http://127.0.0.1:8001/'
  try {
    assert.equal(quantBoardTargetBase(), 'http://127.0.0.1:8001')
  } finally {
    if (previous === undefined) delete process.env.QUANT_BOARD_API_BASE
    else process.env.QUANT_BOARD_API_BASE = previous
  }
})
