import assert from 'node:assert/strict'
import test from 'node:test'

import { quantBoardTargetBase, shouldProxyToQuantBoard } from '../routes/quantBoardProxy.js'


test('theme heat summary and stock detail use QuantBoard proxy prefix', () => {
  assert.equal(shouldProxyToQuantBoard('/api/themes/heat'), true)
  assert.equal(shouldProxyToQuantBoard('/api/themes/heat/AI/stocks'), true)
})


test('deprecated theme batch route is not captured by QuantBoard proxy', () => {
  assert.equal(shouldProxyToQuantBoard('/api/themes/batch'), false)
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
