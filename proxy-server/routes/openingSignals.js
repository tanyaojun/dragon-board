import { sendBadRequest } from '../helpers/response.js'

const SIGNAL_TYPE = 'opening_weak_to_strong'
const SOURCE_PRIORITY = new Map([
  ['desktop', 3],
  ['web', 2],
])
const CONFIDENCE_PRIORITY = new Map([
  ['critical', 3],
  ['strong', 2],
  ['watch', 1],
])

export function registerOpeningSignalRoutes(app, context = {}) {
  const store = context.openingSignalStore || createOpeningSignalStore()

  app.post('/api/opening-signals', (req, res) => {
    const source = normalizeSource(req.body?.source)
    const signal = normalizeSignal(req.body?.signal)
    if (!source || !signal) {
      sendBadRequest(res, 'opening_signal_invalid', 'opening signal payload is invalid')
      return
    }

    const result = store.upsert(source, signal)
    res.json({
      ok: true,
      accepted: true,
      ...result,
    })
  })

  app.get('/api/opening-signals/today', (req, res) => {
    const tradingDate = normalizeTradingDate(req.query?.tradingDate) || todayShanghai()
    res.json({
      ok: true,
      tradingDate,
      signals: store.list(tradingDate),
    })
  })
}

export function createOpeningSignalStore() {
  const records = new Map()

  return {
    upsert(source, signal) {
      const key = dedupeKey(signal)
      const now = new Date().toISOString()
      const previous = records.get(key)
      const report = { ...signal, source }

      if (!previous) {
        const voiceOwner = shouldGrantVoice(signal) ? source : 'none'
        const record = {
          dedupeKey: key,
          canonicalSignal: report,
          reportsBySource: { [source]: report },
          sources: [source],
          firstTriggerAt: signal.triggerAt,
          lastReportedAt: now,
          voiceGrantedTo: voiceOwner === 'none' ? null : source,
        }
        records.set(key, record)
        return serializeRecord(record, {
          isNew: true,
          dedupeAction: 'created',
          voiceOwner,
        })
      }

      const reportsBySource = { ...previous.reportsBySource, [source]: report }
      const sources = mergeSources(previous.sources, source)
      const canonicalSignal = chooseCanonical([...Object.values(reportsBySource)])
      const dedupeAction = canonicalSignal === previous.canonicalSignal ? 'merged' : 'upgraded'
      const voiceOwner = previous.voiceGrantedTo || !shouldGrantVoice(signal) ? 'none' : source
      const next = {
        ...previous,
        canonicalSignal,
        reportsBySource,
        sources,
        firstTriggerAt: earlierIso(previous.firstTriggerAt, signal.triggerAt),
        lastReportedAt: now,
        voiceGrantedTo: previous.voiceGrantedTo || (voiceOwner === 'none' ? null : source),
      }
      records.set(key, next)
      return serializeRecord(next, {
        isNew: false,
        dedupeAction,
        voiceOwner,
      })
    },
    list(tradingDate) {
      return [...records.values()]
        .filter(record => record.canonicalSignal.tradingDate === tradingDate)
        .sort((a, b) => compareIso(b.firstTriggerAt, a.firstTriggerAt))
        .map(record => serializeRecord(record, { isNew: false, dedupeAction: 'cached', voiceOwner: 'none' }))
    },
  }
}

function serializeRecord(record, meta) {
  return {
    ...meta,
    dedupeKey: record.dedupeKey,
    canonicalSignal: record.canonicalSignal,
    reportsBySource: record.reportsBySource,
    sources: record.sources,
    firstTriggerAt: record.firstTriggerAt,
    lastReportedAt: record.lastReportedAt,
    voiceGrantedTo: record.voiceGrantedTo,
  }
}

function normalizeSource(value) {
  const source = String(value || '').trim()
  return source === 'web' || source === 'desktop' ? source : ''
}

function normalizeSignal(value) {
  if (!value || typeof value !== 'object') return null
  const tradingDate = normalizeTradingDate(value.tradingDate)
  const code = normalizeCode(value.code)
  const signalType = String(value.signalType || '').trim()
  if (!tradingDate || !code || signalType !== SIGNAL_TYPE) return null

  return {
    ...value,
    tradingDate,
    code,
    signalType,
    name: normalizeText(value.name, 24) || code,
    confidence: normalizeConfidence(value.confidence),
    score: normalizeScore(value.score),
    triggerAt: normalizeIso(value.triggerAt) || new Date().toISOString(),
    dryRun: Boolean(value.dryRun),
  }
}

function normalizeTradingDate(value) {
  const text = String(value || '').trim()
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : ''
}

function normalizeCode(value) {
  const code = String(value || '').replace(/\D/g, '')
  return /^\d{6}$/.test(code) ? code : ''
}

function normalizeText(value, maxLength) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, maxLength)
}

function normalizeConfidence(value) {
  const text = String(value || '').trim()
  return CONFIDENCE_PRIORITY.has(text) ? text : 'watch'
}

function normalizeScore(value) {
  const score = Number(value)
  if (!Number.isFinite(score)) return 0
  return Math.max(0, Math.min(100, Math.round(score)))
}

function normalizeIso(value) {
  const timestamp = Date.parse(String(value || ''))
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : ''
}

function dedupeKey(signal) {
  return `${signal.tradingDate}:${signal.code}:${signal.signalType}`
}

function shouldGrantVoice(signal) {
  return !signal.dryRun && CONFIDENCE_PRIORITY.get(signal.confidence) >= CONFIDENCE_PRIORITY.get('strong')
}

function mergeSources(previous, source) {
  return previous.includes(source) ? previous : [...previous, source]
}

function chooseCanonical(reports) {
  return [...reports].sort(compareSignals)[0]
}

function compareSignals(left, right) {
  if (Boolean(left.dryRun) !== Boolean(right.dryRun)) {
    return left.dryRun ? 1 : -1
  }

  const confidenceDiff =
    (CONFIDENCE_PRIORITY.get(right.confidence) || 0) - (CONFIDENCE_PRIORITY.get(left.confidence) || 0)
  if (confidenceDiff !== 0) return confidenceDiff

  const scoreDiff = Number(right.score || 0) - Number(left.score || 0)
  if (scoreDiff !== 0) return scoreDiff

  const sourceDiff = (SOURCE_PRIORITY.get(right.source) || 0) - (SOURCE_PRIORITY.get(left.source) || 0)
  if (sourceDiff !== 0) return sourceDiff

  return compareIso(left.triggerAt, right.triggerAt)
}

function earlierIso(left, right) {
  return compareIso(left, right) <= 0 ? left : right
}

function compareIso(left, right) {
  return Date.parse(left || '') - Date.parse(right || '')
}

function todayShanghai() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const byType = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return `${byType.year}-${byType.month}-${byType.day}`
}
