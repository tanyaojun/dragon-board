import assert from 'node:assert/strict'
import test from 'node:test'

test('xueqiu hotlist does not expose upstream failures as HTTP 500', async () => {
  const response = await fetch('http://localhost:3000/api/xueqiu/hot')
  const body = await response.json()

  assert.equal(response.status, 200)
  assert.ok(Array.isArray(body.data?.items))
  if (body.degraded) {
    assert.deepEqual(body.data.items, [])
    assert.match(body.reason, /^upstream_\d+|.+/)
  }
})
