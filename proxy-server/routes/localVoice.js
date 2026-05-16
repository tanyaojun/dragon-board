const DEFAULT_WORKER_URL = 'http://127.0.0.1:32145'
const MAX_TEXT_LENGTH = 200

export function createVoiceWorkerClient(options = {}) {
  const baseUrl = String(options.baseUrl || process.env.VOICE_WORKER_URL || DEFAULT_WORKER_URL).replace(/\/$/, '')
  const fetcher = options.fetcher || globalThis.fetch?.bind(globalThis)
  const timeoutMs = Number(options.timeoutMs || 1500)

  async function request(path, init = {}) {
    if (!fetcher) throw new Error('fetch is not available')

    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const response = await fetcher(`${baseUrl}${path}`, {
        ...init,
        signal: controller.signal,
      })
      const payload = await safeJson(response)
      if (!response.ok || payload?.ok === false) {
        throw new Error(payload?.message || `voice worker request failed: ${response.status}`)
      }
      return payload || {}
    } finally {
      clearTimeout(timer)
    }
  }

  return {
    async status() {
      return request('/status')
    },
    async speak(text, options = {}) {
      return request('/speak', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text, rate: options.rate, volume: options.volume, voice: options.voice }),
      })
    },
    async test(options = {}) {
      return request('/test', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ rate: options.rate, volume: options.volume, voice: options.voice }),
      })
    },
    async stop() {
      return request('/stop', { method: 'POST' })
    },
  }
}

export function registerLocalVoiceRoutes(app, context = {}) {
  const localVoice = context.localVoice || createVoiceWorkerClient()

  app.get('/api/local-voice/status', async (req, res) => {
    try {
      const status = await localVoice.status()
      res.json({
        ok: true,
        source: 'local-voice',
        workerOnline: true,
        supported: Boolean(status.supported),
        engine: status.engine || 'unknown',
        voice: status.voice || '',
        voices: normalizeVoices(status.voices),
        speaking: Boolean(status.speaking),
        queueLength: Number(status.queueLength || 0),
      })
    } catch (error) {
      res.json(buildWorkerOfflineEnvelope(error))
    }
  })

  app.post('/api/local-voice/speak', async (req, res) => {
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

    try {
      const result = await localVoice.speak(text, {
        rate: normalizeRate(req.body?.rate),
        volume: normalizeVolume(req.body?.volume),
        voice: normalizeVoice(req.body?.voice),
      })
      res.json({
        ok: true,
        source: 'local-voice',
        queued: result.queued !== false,
        queueLength: Number(result.queueLength || 0),
      })
    } catch (error) {
      res.status(503).json(buildWorkerOfflineEnvelope(error))
    }
  })

  app.post('/api/local-voice/test', async (req, res) => {
    try {
      const result = await localVoice.test({
        rate: normalizeRate(req.body?.rate),
        volume: normalizeVolume(req.body?.volume),
        voice: normalizeVoice(req.body?.voice),
      })
      res.json({
        ok: true,
        source: 'local-voice',
        queued: result.queued !== false,
        queueLength: Number(result.queueLength || 0),
      })
    } catch (error) {
      res.status(503).json(buildWorkerOfflineEnvelope(error))
    }
  })

  app.post('/api/local-voice/stop', async (req, res) => {
    try {
      const result = await localVoice.stop()
      res.json({
        ok: true,
        source: 'local-voice',
        queueLength: Number(result.queueLength || 0),
      })
    } catch (error) {
      res.status(503).json(buildWorkerOfflineEnvelope(error))
    }
  })
}

function normalizeSpeechText(value) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.slice(0, MAX_TEXT_LENGTH)
}

function normalizeRate(value) {
  const rate = Number(value)
  if (!Number.isFinite(rate)) return undefined
  return Math.round(Math.min(1.8, Math.max(0.6, rate)) * 100) / 100
}

function normalizeVolume(value) {
  const volume = Number(value)
  if (!Number.isFinite(volume)) return undefined
  return Math.round(Math.min(100, Math.max(0, volume)))
}

function normalizeVoice(value) {
  const voice = String(value || '').trim()
  return voice || undefined
}

function normalizeVoices(value) {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => {
      if (!item || typeof item !== 'object') return null
      const name = normalizeVoice(item.name ?? item.Name)
      if (!name) return null
      return {
        name,
        culture: normalizeVoice(item.culture ?? item.Culture),
        gender: normalizeVoice(item.gender ?? item.Gender),
      }
    })
    .filter(Boolean)
}

async function safeJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function buildWorkerOfflineEnvelope(error) {
  return {
    ok: false,
    source: 'local-voice',
    workerOnline: false,
    supported: false,
    queueLength: 0,
    errorCode: 'local_voice_worker_offline',
    message: error?.message || 'local voice worker is offline',
  }
}
