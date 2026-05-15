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

test('local voice exposes status and queues speak requests through injected engine', async () => {
  const spoken = []
  const localVoice = {
    isSupported: () => true,
    speak: async (text) => {
      spoken.push(text)
    },
    stop: () => {
      spoken.push('STOP')
    },
  }
  const app = createProxyApp({ logRequests: false, localVoice })
  const { server, baseUrl } = await listen(app)

  try {
    const statusResponse = await fetch(`${baseUrl}/api/local-voice/status`)
    const statusBody = await statusResponse.json()
    assert.equal(statusResponse.status, 200)
    assert.equal(statusBody.ok, true)
    assert.equal(statusBody.supported, true)

    const speakResponse = await fetch(`${baseUrl}/api/local-voice/speak`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: '中南文化即将打开涨停' }),
    })
    const speakBody = await speakResponse.json()
    assert.equal(speakResponse.status, 200)
    assert.equal(speakBody.ok, true)
    assert.equal(speakBody.queued, true)
    assert.deepEqual(spoken, ['中南文化即将打开涨停'])

    const testResponse = await fetch(`${baseUrl}/api/local-voice/test`, { method: 'POST' })
    const testBody = await testResponse.json()
    assert.equal(testResponse.status, 200)
    assert.equal(testBody.ok, true)
    assert.equal(spoken[1], '热榜异动本地语音测试，当前语音提醒正常')

    const stopResponse = await fetch(`${baseUrl}/api/local-voice/stop`, { method: 'POST' })
    const stopBody = await stopResponse.json()
    assert.equal(stopResponse.status, 200)
    assert.equal(stopBody.ok, true)
    assert.equal(spoken[2], 'STOP')
  } finally {
    server.close()
  }
})

test('local voice rejects empty speak text', async () => {
  const app = createProxyApp({ logRequests: false })
  const { server, baseUrl } = await listen(app)

  try {
    const response = await fetch(`${baseUrl}/api/local-voice/speak`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: '   ' }),
    })
    const body = await response.json()

    assert.equal(response.status, 400)
    assert.equal(body.ok, false)
    assert.equal(body.errorCode, 'local_voice_empty_text')
  } finally {
    server.close()
  }
})
