import { spawn } from 'node:child_process'
import os from 'node:os'

const TEST_TEXT = '热榜异动本地语音测试，当前语音提醒正常'
const MAX_TEXT_LENGTH = 200

export function createWindowsSapiVoice() {
  return {
    isSupported() {
      return os.platform() === 'win32'
    },
    speak(text) {
      if (os.platform() !== 'win32') {
        return Promise.reject(new Error('local voice only supports Windows SAPI'))
      }
      return speakWithPowerShell(text)
    },
    stop() {},
  }
}

export function registerLocalVoiceRoutes(app, context = {}) {
  const localVoice = context.localVoice || createWindowsSapiVoice()
  const queue = []
  let speaking = false

  async function drainQueue() {
    if (speaking) return
    const text = queue.shift()
    if (!text) return

    speaking = true
    try {
      await localVoice.speak(text)
    } catch (error) {
      console.warn('[local-voice] speak failed:', error?.message || error)
    } finally {
      speaking = false
      void drainQueue()
    }
  }

  function enqueue(text) {
    queue.push(text)
    void drainQueue()
  }

  app.get('/api/local-voice/status', (req, res) => {
    res.json({
      ok: true,
      source: 'local-voice',
      supported: Boolean(localVoice.isSupported()),
      queueLength: queue.length + (speaking ? 1 : 0),
    })
  })

  app.post('/api/local-voice/speak', (req, res) => {
    const text = normalizeSpeechText(req.body?.text)
    if (!text) {
      res.status(400).json({
        ok: false,
        source: 'local-voice',
        errorCode: 'local_voice_empty_text',
        message: 'speech text is empty',
      })
      return
    }

    if (!localVoice.isSupported()) {
      res.status(503).json({
        ok: false,
        source: 'local-voice',
        errorCode: 'local_voice_unsupported',
        message: 'local voice is not supported on this host',
      })
      return
    }

    enqueue(text)
    res.json({
      ok: true,
      source: 'local-voice',
      queued: true,
      queueLength: queue.length + (speaking ? 1 : 0),
    })
  })

  app.post('/api/local-voice/test', (req, res) => {
    if (!localVoice.isSupported()) {
      res.status(503).json({
        ok: false,
        source: 'local-voice',
        errorCode: 'local_voice_unsupported',
        message: 'local voice is not supported on this host',
      })
      return
    }

    enqueue(TEST_TEXT)
    res.json({
      ok: true,
      source: 'local-voice',
      queued: true,
      queueLength: queue.length + (speaking ? 1 : 0),
    })
  })

  app.post('/api/local-voice/stop', (req, res) => {
    queue.length = 0
    localVoice.stop()
    res.json({
      ok: true,
      source: 'local-voice',
      queueLength: 0,
    })
  })
}

function normalizeSpeechText(value) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.slice(0, MAX_TEXT_LENGTH)
}

function speakWithPowerShell(text) {
  const escapedText = text.replace(/'/g, "''")
  const script = [
    'Add-Type -AssemblyName System.Speech',
    '$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer',
    '$speaker.Rate = 1',
    '$speaker.Volume = 100',
    `$speaker.Speak('${escapedText}')`,
  ].join('; ')

  return new Promise((resolve, reject) => {
    const child = spawn('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script], {
      windowsHide: true,
    })
    child.on('error', reject)
    child.on('exit', (code) => {
      if (code === 0) {
        resolve()
        return
      }
      reject(new Error(`powershell speech exited with code ${code}`))
    })
  })
}
