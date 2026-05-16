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

test('local voice proxies status and commands to voice worker', async () => {
  const calls = []
  const localVoice = {
    status: async () => ({ supported: true, engine: 'volcengine', queueLength: 0, speaking: false }),
    speak: async (text, options) => calls.push(['speak', text, options]),
    test: async (options) => calls.push(['test', options]),
    stop: async () => calls.push(['stop']),
  }
  const app = createProxyApp({ logRequests: false, localVoice })
  const { server, baseUrl } = await listen(app)

  try {
    const statusResponse = await fetch(`${baseUrl}/api/local-voice/status`)
    const statusBody = await statusResponse.json()
    assert.equal(statusResponse.status, 200)
    assert.equal(statusBody.ok, true)
    assert.equal(statusBody.supported, true)
    assert.equal(statusBody.workerOnline, true)
    assert.equal(statusBody.engine, 'volcengine')

    const speakResponse = await fetch(`${baseUrl}/api/local-voice/speak`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: '中南文化即将打开涨停', rate: 1.2, volume: 80 }),
    })
    const speakBody = await speakResponse.json()
    assert.equal(speakResponse.status, 200)
    assert.equal(speakBody.ok, true)
    assert.equal(speakBody.queued, true)
    assert.deepEqual(calls, [['speak', '中南文化即将打开涨停', { rate: 1.2, volume: 80 }]])

    const testResponse = await fetch(`${baseUrl}/api/local-voice/test`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ rate: 0.8, volume: 55 }),
    })
    const testBody = await testResponse.json()
    assert.equal(testResponse.status, 200)
    assert.equal(testBody.ok, true)
    assert.deepEqual(calls[1], ['test', { rate: 0.8, volume: 55 }])

    const stopResponse = await fetch(`${baseUrl}/api/local-voice/stop`, { method: 'POST' })
    const stopBody = await stopResponse.json()
    assert.equal(stopResponse.status, 200)
    assert.equal(stopBody.ok, true)
    assert.deepEqual(calls[2], ['stop'])
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

test('local voice reports worker offline without invoking PowerShell fallback', async () => {
  const localVoice = {
    status: async () => {
      throw new Error('connect ECONNREFUSED')
    },
    speak: async () => {
      throw new Error('connect ECONNREFUSED')
    },
    test: async () => {
      throw new Error('connect ECONNREFUSED')
    },
    stop: async () => {
      throw new Error('connect ECONNREFUSED')
    },
  }
  const app = createProxyApp({ logRequests: false, localVoice })
  const { server, baseUrl } = await listen(app)

  try {
    const statusResponse = await fetch(`${baseUrl}/api/local-voice/status`)
    const statusBody = await statusResponse.json()
    assert.equal(statusResponse.status, 200)
    assert.equal(statusBody.ok, false)
    assert.equal(statusBody.supported, false)
    assert.equal(statusBody.workerOnline, false)
    assert.equal(statusBody.errorCode, 'local_voice_worker_offline')

    const speakResponse = await fetch(`${baseUrl}/api/local-voice/speak`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: '中南文化即将打开涨停' }),
    })
    const speakBody = await speakResponse.json()
    assert.equal(speakResponse.status, 503)
    assert.equal(speakBody.ok, false)
    assert.equal(speakBody.errorCode, 'local_voice_worker_offline')
  } finally {
    server.close()
  }
})
