import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

test('login credentials live in .env.local instead of server.js', () => {
  const serverSource = fs.readFileSync(new URL('../server.js', import.meta.url), 'utf8')
  const envPath = new URL('../.env.local', import.meta.url)

  assert.doesNotMatch(serverSource, /xq_a_token=/)
  assert.doesNotMatch(serverSource, /xq_id_token=/)
  if (fs.existsSync(envPath)) {
    const envSource = fs.readFileSync(envPath, 'utf8')
    assert.match(envSource, /^XUEQIU_COOKIE=/m)
  }
})
