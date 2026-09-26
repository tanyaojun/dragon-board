import assert from 'node:assert/strict'
import test from 'node:test'

import { shouldProxyToQuantBoard } from '../routes/quantBoardProxy.js'

test('theme-rotation prefix is forwarded to QuantBoard', () => {
  // 2026-09-27 轮动状态页签缺口修复：/api/theme-rotation/* 必须转发到 8000，
  // 否则前端命中 proxy_route_not_found 404（theme-momentum 同款前缀对照）
  assert.equal(shouldProxyToQuantBoard('/api/theme-rotation/summary'), true)
  assert.equal(shouldProxyToQuantBoard('/api/theme-rotation/summary?snapshot_type=half_hour'), true)
})

test('theme-momentum prefix remains forwarded (regression guard)', () => {
  assert.equal(shouldProxyToQuantBoard('/api/theme-momentum/summary'), true)
})

test('unknown api prefixes still fall through to local routes', () => {
  assert.equal(shouldProxyToQuantBoard('/api/notifications/list'), false)
})
